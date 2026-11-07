"""Build data/manifest.json from the RBI NBFC / DPDP PDF corpus.

Read-only on the PDFs. No network access. Deterministic and idempotent.
Fully regenerated from the PDFs and the mapping on every run - this script
never reads an existing manifest.json, so there is no carry-over of old values.
"""
import datetime
import hashlib
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
OUT_PATH = os.path.join(DATA_DIR, "manifest.json")

MAPPING = {
    12931: "Miscellaneous",
    12932: "Non-Operative Financial Holding Companies",
    12933: "Microfinance Institution",
    12934: "Peer to Peer Lending Platform",
    12935: "Mortgage Guarantee Companies",
    12936: "Account Aggregator",
    12937: "Core Investment Companies",
    12938: "Standalone Primary Dealers",
    12939: "Housing Finance Companies",
    12940: "Climate Finance and Management of Climate Change Risks",
    12941: "Managing Risks in Outsourcing",
    12942: "Responsible Business Conduct",
    12943: "Know Your Customer",
    12944: "Prudential Norms on Declaration of Dividends",
    12945: "Financial Statements: Presentation and Disclosures",
    12946: "Treatment of Wilful Defaulters and Large Defaulters",
    12947: "Resolution of Stressed Assets",
    12948: "Income Recognition, Asset Classification and Provisioning",
    12949: "Asset Liability Management",
    12950: "Classification, Valuation and Operation of Investment Portfolio",
    12951: "Securitisation Transactions",
    12952: "Transfer and Distribution of Credit Risk",
    12953: "Concentration Risk Management",
    12954: "Credit Risk Management",
    12955: "Credit Information Reporting",
    12956: "Credit Cards: Issuance and Conduct",
    12957: "Credit Facilities",
    12958: "Acceptance of Public Deposits",
    12959: "Prudential Norms on Capital Adequacy",
    12960: "Governance",
    12961: "Undertaking of Financial Services",
    12962: "Branch Authorisation",
    12963: "Voluntary Amalgamation",
    12964: "Acquisition of Shareholding or Control",
    12965: "Registration, Exemptions and Framework for Scale Based Regulation",
    13274: "Internal Ombudsman",
    12848: "Digital Lending",
}
URL_PATTERN = "https://rbi.org.in/SCRIPTs/BS_ViewMasDirections.aspx?id={}"
DPDP_ACT_EGAZETTE_URL = "https://egazette.gov.in/WriteReadData/2023/248045.pdf"
DPDP_ACT_LANDING_URL = "https://www.indiacode.nic.in/handle/123456789/22037"
DPDP_RULES_2025_URL = "https://www.meity.gov.in/static/uploads/2025/11/53450e6e5dc0bfa85ebd78686cadad39.pdf"
DPDP_RULES_2025_ISSUE_DATE = "2025-11-13"  # G.S.R. 846(E), as given - not extracted/guessed

ALLOWED_DOC_TYPES = {"direction", "act", "rules", "explainer"}
DEVANAGARI_THRESHOLD = 50  # masthead alone runs ~15 chars; real bilingual body runs far higher

NBFC_SPECIFIC_TITLE_HINTS = [
    "housing finance companies",
    "core investment companies",
    "mortgage guarantee companies",
    "non operative financial holding companies",
    "standalone primary dealers",
    "digital lending",
]

MONTHS = (
    "january|february|march|april|may|june|july|august|"
    "september|october|november|december"
)


def norm(s):
    s = s.lower()
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\bcompany\b", "companies", s)
    return s.strip()


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def month_to_num(name):
    names = ["january", "february", "march", "april", "may", "june", "july",
             "august", "september", "october", "november", "december"]
    return names.index(name.lower()) + 1


def parse_long_date(text):
    """'November 28, 2025' or 'November 28 2025' -> '2025-11-28'."""
    m = re.search(r"(" + MONTHS + r")\.?\s+(\d{1,2}),?\s+(\d{4})", text, re.IGNORECASE)
    if m:
        mo = month_to_num(m.group(1))
        day = int(m.group(2))
        year = int(m.group(3))
        return "%04d-%02d-%02d" % (year, mo, day), m.group(0)
    return None, None


def parse_bracket_date(text):
    """'[11th August, 2023.]' -> '2023-08-11'."""
    m = re.search(r"\[\s*(\d{1,2})(?:st|nd|rd|th)?\s+(" + MONTHS + r")\.?,?\s+(\d{4})\.?\s*\]",
                   text, re.IGNORECASE)
    if m:
        day = int(m.group(1))
        mo = month_to_num(m.group(2))
        year = int(m.group(3))
        return "%04d-%02d-%02d" % (year, mo, day), m.group(0)
    return None, None


def extract_updated_as_on(text):
    m = re.search(r"updated\s+as\s+on\s+(" + MONTHS + r")\.?\s+(\d{1,2}),?\s+(\d{4})",
                  text, re.IGNORECASE)
    if m:
        mo = month_to_num(m.group(1))
        day = int(m.group(2))
        year = int(m.group(3))
        return "%04d-%02d-%02d" % (year, mo, day)
    return None


def extract_rbi_title(text):
    m = re.search(r"Reserve Bank of India\s*\(([^)]*)\)\s*Directions(?:,?\s*(\d{4}))?",
                  text, re.IGNORECASE | re.DOTALL)
    if not m:
        return None, None
    inner = re.sub(r"\s+", " ", m.group(1)).strip()
    year = m.group(2)
    if year:
        full_title = "Reserve Bank of India (%s) Directions, %s" % (inner, year)
    else:
        full_title = "Reserve Bank of India (%s) Directions" % inner
    return full_title, inner


def extract_dpdp_act_title(text):
    head = text[:400]
    has_title = re.search(r"DIGITAL PERSONAL DATA PROTECTION ACT,?\s*2023", head, re.IGNORECASE)
    has_act_no = re.search(r"\(\s*NO\.?\s*22\s*OF\s*2023\s*\)", head, re.IGNORECASE)
    if has_title and has_act_no:
        return "The Digital Personal Data Protection Act, 2023"
    return None


def title_from_filename(filename):
    name = os.path.splitext(filename)[0]
    name = re.sub(r"^(Gazette of India PDF - |Meity - )", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*\(updated as on[^)]*\)\s*", "", name, flags=re.IGNORECASE)
    return name.strip()


def classify_entity(title_text_for_match, filename):
    hay = norm(title_text_for_match) + " " + norm(filename)
    if "urban co operative banks" in hay or "urban co-operative banks" in title_text_for_match.lower():
        return "ucb"
    if "digital personal data protection" in hay or "dpdp" in norm(filename):
        return "dpdp"
    if "non banking financial companies" in hay:
        return "nbfc"
    for hint in NBFC_SPECIFIC_TITLE_HINTS:
        if hint in hay:
            return "nbfc"
    if "internal ombudsman" in hay:
        return "nbfc"
    return "other"


def match_source_url(rbi_topic_inner, title, entity):
    if entity == "dpdp":
        if "act" in title.lower():
            return DPDP_ACT_EGAZETTE_URL, None
        return None, None
    if rbi_topic_inner:
        topic = rbi_topic_inner
        topic = re.sub(r"^non[- ]banking financial companies\s*[-\u2013\u2014]\s*", "",
                        topic, flags=re.IGNORECASE)
        topic_n = norm(topic)
        for _id, mapped_topic in MAPPING.items():
            if norm(mapped_topic) == topic_n:
                return URL_PATTERN.format(_id), _id
        for _id, mapped_topic in MAPPING.items():
            if norm(mapped_topic) in topic_n or topic_n in norm(mapped_topic):
                return URL_PATTERN.format(_id), _id
    return None, None


def slugify(entity, topic_for_slug):
    s = norm(topic_for_slug)
    s = re.sub(r"\s+", "_", s).strip("_")
    return "%s_%s" % (entity, s)


def devanagari_char_count(text):
    return sum(1 for ch in text if 0x0900 <= ord(ch) <= 0x097F)


def detect_language(full_text):
    if devanagari_char_count(full_text) > DEVANAGARI_THRESHOLD:
        return "en+hi"
    return "en"


def is_dpdp_press_note_signature(full_text):
    head = full_text[:1000]
    has_notified = re.search(r"\bNotified\b", head, re.IGNORECASE)
    has_subtitle = re.search(r"Citizen-Centric Framework", head, re.IGNORECASE)
    return bool(has_notified and has_subtitle)


def title_short_for(entity, title, rbi_inner, matched_id):
    if entity == "dpdp":
        return "DPDP Act, 2023" if "act" in title.lower() else "DPDP Rules, 2025"
    if matched_id and matched_id in MAPPING:
        return MAPPING[matched_id]
    if rbi_inner:
        topic = re.sub(r"^non[- ]banking financial companies\s*[-\u2013\u2014]\s*", "",
                        rbi_inner, flags=re.IGNORECASE)
        return topic.strip()
    return title


def extract_notification_number(full_text):
    head = full_text[:1000]
    m = re.search(r"\bRBI/(?:[A-Za-z]+/)?\d{4}-\d{2}/\d+\b", head)
    if m:
        return m.group(0)
    m = re.search(r"\(\s*NO\.?\s*\d+\s*OF\s*\d{4}\s*\)", head, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", " ", m.group(0)).strip("() ")
    # G.S.R. search is not limited to head[:1000] - bilingual Gazette notifications
    # put a lengthy Hindi preamble before the English text, pushing the G.S.R.
    # reference well past the usual header window (confirmed on dpdp_rules_2025).
    m = re.search(r"G\.S\.R\.?\s*\d+\s*\(E\)", full_text, re.IGNORECASE)
    if m:
        return m.group(0)
    return None


def extract_issuing_department(notification_number):
    if not notification_number:
        return None
    m = re.match(r"RBI/([A-Za-z]+)/", notification_number)
    if m:
        return m.group(1)
    return None


def extract_effective_date(full_text, issue_date):
    head = full_text[:3000]
    m = re.search(
        r"come into force.{0,60}?(?:with effect from|from)\s+(" + MONTHS + r")\.?\s+(\d{1,2}),?\s+(\d{4})",
        head, re.IGNORECASE | re.DOTALL)
    if m:
        mo = month_to_num(m.group(1))
        day = int(m.group(2))
        year = int(m.group(3))
        return "%04d-%02d-%02d" % (year, mo, day), "text"
    return issue_date, "default_to_issue_date"


def extract_supersedes(full_text):
    m = re.search(
        r"stands?\s+repealed,?\s*as communicated vide circular\s*([A-Z0-9./\-]+)\s*dated\s*("
        + MONTHS + r")\.?\s+(\d{1,2}),?\s+(\d{4})",
        full_text, re.IGNORECASE)
    if m:
        circular = m.group(1)
        mo = month_to_num(m.group(2))
        day = int(m.group(3))
        year = int(m.group(4))
        date_str = "%04d-%02d-%02d" % (year, mo, day)
        return "repealed/superseded prior instructions per circular %s dated %s" % (circular, date_str)
    return None


def build_record(filename, path):
    import pymupdf

    doc = pymupdf.open(path)
    pages = doc.page_count
    text = ""
    for i in range(min(2, pages)):
        text += doc[i].get_text()
    full_text = text
    for i in range(2, pages):
        full_text += doc[i].get_text()
    doc.close()

    size = os.path.getsize(path)
    sha = sha256_of(path)
    retrieved_on = datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()

    notes = []

    rbi_title, rbi_inner = extract_rbi_title(text)
    dpdp_title = extract_dpdp_act_title(text)

    if rbi_title:
        title = rbi_title
        title_source = "text"
    elif dpdp_title:
        title = dpdp_title
        title_source = "text"
    else:
        title = title_from_filename(filename)
        title_source = "filename"
        notes.append("title taken from filename, not confirmed in extracted text")

    entity = classify_entity(title + " " + text[:500], filename)
    if entity == "ucb":
        notes.append("title indicates Urban Co-operative Banks, not NBFC - flagged, no NBFC URL assigned")
    if entity == "other":
        notes.append("entity could not be classified as nbfc/dpdp/ucb - flagged for manual review")

    updated_as_on = extract_updated_as_on(full_text)

    issue_date = None
    date_source = None
    if entity == "dpdp" and "act" in title.lower():
        d, matched = parse_bracket_date(text)
        if d:
            issue_date = d
            date_source = "text"
    if issue_date is None:
        header_text = text[:1500]
        header_text_wo_updated = re.sub(
            r"updated\s+as\s+on\s+" + "(" + MONTHS + r")\.?\s+\d{1,2},?\s+\d{4}",
            "", header_text, flags=re.IGNORECASE)
        d, matched = parse_long_date(header_text_wo_updated)
        if d:
            issue_date = d
            date_source = "text"

    if issue_date is None:
        if entity == "nbfc":
            issue_date = "2025-11-28"
            date_source = "default"
            notes.append("issue_date defaulted to 2025-11-28 (standard NBFC Master Direction date); not confirmed in text")
        else:
            notes.append("issue_date not found in text, left null")

    url, matched_id = match_source_url(rbi_inner, title, entity)
    if url is None and entity == "nbfc":
        notes.append("no matching source_page_url found in mapping - flagged")

    language = detect_language(full_text)
    landing_page_url = url

    if entity == "dpdp" and "act" in title.lower():
        doc_type = "act"
        landing_page_url = DPDP_ACT_LANDING_URL
    elif entity == "dpdp":
        if is_dpdp_press_note_signature(full_text):
            doc_type = "explainer"
            notes.append(
                "file still looks like the PIB press-note placeholder (title 'Notified' + "
                "'Citizen-Centric Framework' subtitle), not the Gazette notification - "
                "replace with G.S.R. 846(E) dated 2025-11-13"
            )
        else:
            doc_type = "rules"
            url = DPDP_RULES_2025_URL
            landing_page_url = DPDP_RULES_2025_URL
            matched_id = None
            if issue_date is None:
                issue_date = DPDP_RULES_2025_ISSUE_DATE
                date_source = "known"
                notes.append("issue_date set to 2025-11-13 (G.S.R. 846(E)), as provided - not found verbatim in text")
    else:
        doc_type = "direction"

    if entity == "nbfc":
        slug_topic = rbi_inner or title
        slug_topic = re.sub(r"^non[- ]banking financial companies\s*[-\u2013\u2014]\s*", "",
                             slug_topic, flags=re.IGNORECASE)
    elif entity == "dpdp":
        slug_topic = "act_2023" if "act" in title.lower() else "rules_2025"
    else:
        slug_topic = title
    doc_id = slugify(entity, slug_topic)

    title_short = title_short_for(entity, title, rbi_inner, matched_id)
    notification_number = extract_notification_number(full_text)
    issuing_department = extract_issuing_department(notification_number)
    effective_date, effective_date_source = extract_effective_date(full_text, issue_date)
    supersedes = extract_supersedes(full_text)
    applies_to = entity

    if title_source == "text" and (issue_date and date_source == "text"):
        parse_confidence = "high"
    elif title_source == "text":
        parse_confidence = "high" if entity != "other" else "medium"
    elif title_source == "filename":
        parse_confidence = "medium"
    else:
        parse_confidence = "low"

    if not full_text.strip():
        parse_confidence = "low"
        notes.append("no extractable text layer found - possibly scanned, OCR needed")

    version_date = updated_as_on or issue_date

    return {
        "doc_id": doc_id,
        "file": filename,
        "entity": entity,
        "doc_type": doc_type,
        "language": language,
        "title": title,
        "title_short": title_short,
        "issue_date": issue_date,
        "updated_as_on": updated_as_on,
        "version_date": version_date,
        "effective_date": effective_date,
        "notification_number": notification_number,
        "issuing_department": issuing_department,
        "supersedes": supersedes,
        "applies_to": applies_to,
        "source_page_url": url,
        "landing_page_url": landing_page_url,
        "retrieved_on": retrieved_on,
        "pdf_pages": pages,
        "bytes": size,
        "sha256": sha,
        "parse_confidence": parse_confidence,
        "notes": "; ".join(notes) if notes else None,
    }


def main():
    if os.path.isdir(RAW_DIR) and any(f.lower().endswith(".pdf") for f in os.listdir(RAW_DIR)):
        source_dir = RAW_DIR
    else:
        source_dir = DATA_DIR

    files = sorted(f for f in os.listdir(source_dir) if f.lower().endswith(".pdf"))

    records = []
    for f in files:
        rec = build_record(f, os.path.join(source_dir, f))
        records.append(rec)

    missing_version_date = [r["file"] for r in records if not r.get("version_date")]
    if missing_version_date:
        print("ERROR: version_date is null for the following files "
              "(both updated_as_on and issue_date missing):", file=sys.stderr)
        for f in missing_version_date:
            print("  ", f, file=sys.stderr)
        sys.exit(1)

    records.sort(key=lambda r: r["doc_id"])

    doc_ids = [r["doc_id"] for r in records]
    if len(doc_ids) != len(set(doc_ids)):
        dupes = sorted({d for d in doc_ids if doc_ids.count(d) > 1})
        print("ERROR: duplicate doc_id values produced:", dupes, file=sys.stderr)
        sys.exit(1)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
        f.write("\n")

    def ascii_safe(s):
        return str(s).encode("ascii", "replace").decode("ascii")

    print("Source folder:", source_dir)
    print("Output written to:", OUT_PATH)
    print("Output file modified at:",
          datetime.datetime.fromtimestamp(os.path.getmtime(OUT_PATH)).isoformat())
    print("Total PDFs processed:", len(records))
    print()

    dpdp_act_record = next((r for r in records if r["doc_id"] == "dpdp_act_2023"), None)
    print("--- Full dpdp_act_2023 record ---")
    if dpdp_act_record:
        print(json.dumps(dpdp_act_record, indent=2, ensure_ascii=False).encode("ascii", "replace").decode("ascii"))
    else:
        print("  NOT FOUND")
    print()

    print("%-55s %-8s %-10s %-6s %-14s %-8s %-6s" % (
        "doc_id", "entity", "doc_type", "lang", "updated_as_on", "conf", "url"))
    for r in records:
        print("%-55s %-8s %-10s %-6s %-14s %-8s %-6s" % (
            ascii_safe(r["doc_id"][:55]),
            r["entity"],
            r["doc_type"],
            r["language"],
            r["updated_as_on"] or "-",
            r["parse_confidence"],
            "yes" if r["source_page_url"] else "no",
        ))

    print()
    print("--- Validation report ---")
    print("Total PDFs found: %d (expected 39: 35 NBFC + Internal Ombudsman + Digital Lending + DPDP Act + DPDP Rules)"
          % len(records))

    matched_ids = set()
    for r in records:
        if r["source_page_url"] and "BS_ViewMasDirections" in r["source_page_url"]:
            m = re.search(r"id=(\d+)", r["source_page_url"])
            if m:
                matched_ids.add(int(m.group(1)))
    missing = sorted(set(MAPPING) - matched_ids)
    print()
    print("NBFC/Internal Ombudsman/Digital Lending mapping entries with NO matching PDF:")
    if missing:
        for i in missing:
            print("  %s %s" % (i, MAPPING[i]))
    else:
        print("  none")

    print()
    print("Records with null source_page_url:")
    for r in records:
        if r["source_page_url"] is None:
            print("  ", ascii_safe(r["doc_id"]))

    print()
    print("Records with null updated_as_on:")
    for r in records:
        if r["updated_as_on"] is None:
            print("  ", ascii_safe(r["doc_id"]))

    print()
    print("Non-nbfc/dpdp entities (ucb/other) - review:")
    for r in records:
        if r["entity"] in ("ucb", "other"):
            print("  ", ascii_safe(r["doc_id"]), r["entity"], ascii_safe(r["notes"] or ""))

    by_sha = {}
    for r in records:
        by_sha.setdefault(r["sha256"], []).append(r["doc_id"])
    dupes = {k: v for k, v in by_sha.items() if len(v) > 1}
    print()
    print("Duplicate sha256 groups among kept files:")
    if dupes:
        for sha, ids in dupes.items():
            print("  ", sha[:12], ids)
    else:
        print("  none")

    print()
    print("doc_type distribution:")
    for dt, count in Counter(r["doc_type"] for r in records).most_common():
        print("  ", dt, count)

    print()
    print("language distribution:")
    for lang, count in Counter(r["language"] for r in records).most_common():
        print("  ", lang, count)

    print()
    print("Records flagged as doc_type 'explainer' (not primary legal text):")
    for r in records:
        if r["doc_type"] == "explainer":
            print("  ", ascii_safe(r["doc_id"]), "-", ascii_safe(r["notes"] or ""))

    print()
    print("Records with null supersedes (no repeal/supersession reference found in text):")
    for r in records:
        if r["supersedes"] is None:
            print("  ", ascii_safe(r["doc_id"]))

    print()
    print("Records with null notification_number:")
    for r in records:
        if r["notification_number"] is None:
            print("  ", ascii_safe(r["doc_id"]))

    print()
    print("Records with parse_confidence low or notes present:")
    for r in records:
        if r["parse_confidence"] == "low" or r["notes"]:
            print("  ", ascii_safe(r["doc_id"]), r["parse_confidence"], "-", ascii_safe(r["notes"] or ""))


if __name__ == "__main__":
    main()
