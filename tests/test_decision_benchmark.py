"""The decision sheet must be balanced, evidence-bearing and rule-checkable."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from build_decision_benchmark import asks, build, VERDICTS  # noqa: E402


def test_asks_prefers_the_most_specific_attribute():
    assert asks("Is CVE-2026-1234 fixed in Fedora 44?") == "cve"
    assert asks("When is iOS 26.1 coming out?") == "date"
    assert asks("What is the latest version of Firefox?") == "version"
    assert asks("Did the 6.8 kernel break grub for anyone else?") == "stance"
    assert asks("Thoughts on the new Arch install guide") == "other"


def test_sheet_is_stratified_with_empty_slots_and_pool_evidence():
    recs = [{"id": i, "query": f"q{i}", "category": c, "ecosystem": e, "vendor": e}
            for i, (c, e) in enumerate([(c, e) for c in "AB" for e in "xy"] * 3)]
    pools = {r["id"]: [{"doc_id": f"d{r['id']}", "title": "t"}] for r in recs}
    rows = build(recs, pools, n=4)
    assert sorted(r["category"] for r in rows) == ["A", "A", "B", "B"]
    assert all(r["a1"]["verdict"] is None and r["a2"]["evidence_doc_ids"] == [] for r in rows)
    assert all(r["evidence"][0]["doc_id"] == f"d{r['id']}" for r in rows)
    assert rows[0]["a1"] is not rows[0]["a2"]
    assert VERDICTS == ("act", "hold", "insufficient_evidence")
