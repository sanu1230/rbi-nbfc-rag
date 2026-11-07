import json
import os

MANIFEST_PATH = os.path.join(os.path.dirname(__file__),"..", "data", "manifest.json")

ALLOWED_URL_PREFIXES = (
    "https://rbi.org.in/",
    "https://www.indiacode.nic.in/"
)

NEW_FIELDS = (
    "landing_page_url", "applies_to", "effective_date", "notification_number",
    "issuing_department", "supersedes", "title_short", "retrieved_on",
)

def load_manifest():
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)

def test_manifest_is_valid_json():
    data = load_manifest()
    assert isinstance(data, list), "Manifest should be a list of entries"
    assert len(data) > 0

def test_doc_ids_are_unique():
    data = load_manifest()
    doc_ids = [entry["doc_id"] for entry in data]
    assert len(doc_ids) == len(set(doc_ids)), "Duplicate doc_id found in manifest"

def test_sha256_are_unique():
    data = load_manifest()
    sha256_hashes = [entry["sha256"] for entry in data]
    assert len(sha256_hashes) == len(set(sha256_hashes)), "Duplicate sha256 hash found in manifest"

def test_required_fields_present():
    data = load_manifest()
    for r in data:
        for field in ("doc_id", "file", "title", "entity", "sha256"):
            assert field in r, f"Missing {field} in {r.get('doc_id')}"
            assert r[field], f"empty {field} in {r.get('doc_id')}"


def test_source_page_url_domains():
    data = load_manifest()
    for r in data:
        url = r.get("source_page_url")
        if url is None:
            continue
        assert url.startswith(ALLOWED_URL_PREFIXES), (
            f"unexpected source_page_url domain in {r.get('doc_id')}: {url}"
        )

def test_dpdp_act_url_is_egazette():
    data = load_manifest()
    r = next(x for x in data if x["doc_id"] == "dpdp_act_2023")
    assert r["source_page_url"].startswith("https://egazette.gov.in/"), (
        f"dpdp_act_2023 source_page_url is {r['source_page_url']!r}, expected an egazette.gov.in URL"
    )


def test_all_new_fields_present():
    data = load_manifest()
    for r in data:
        for field in NEW_FIELDS:
            assert field in r, f"missing {field} in {r.get('doc_id')}"