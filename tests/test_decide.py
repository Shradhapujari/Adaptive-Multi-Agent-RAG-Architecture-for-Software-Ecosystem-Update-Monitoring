"""decide(): each verdict needs its obligation, and silence is an abstention.

The pool is the harness's normalized doc shape (doc_id/source/title/text/date);
no model, no network. One case per rule, one for precedence, one for the
version gate, one for the three-class collapse.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import decide as D

Q = "Is Ubuntu 24.04 safe to upgrade to?"
V = ["Ubuntu"]


def _d(i, source, title, text="", date=""):
    return {"doc_id": f"d{i}", "source": source, "title": title, "text": text, "date": date}


def test_empty_pool_abstains_with_no_evidence():
    d = D.decide([], Q, V)
    assert d.verdict == "insufficient_evidence" and d.stop_reason == "no_evidence"
    assert d.evidence == [] and set(d.probes_wanted) == {"release", "cve", "community"}
    assert D.render(d, []) == D.REFUSAL


def test_off_product_documents_are_not_evidence():
    pool = [_d(1, "vendor_releases", "Fedora 42 released", "fixes many bugs")]
    d = D.decide(pool, Q, V)
    assert d.verdict == "insufficient_evidence" and d.stop_reason == "no_evidence"


def test_release_note_alone_is_safe_with_low_confidence_and_open_probes():
    pool = [_d(1, "vendor_releases", "Ubuntu 24.04.1 LTS released", "point release")]
    d = D.decide(pool, Q, V)
    assert d.verdict == "safe" and d.evidence == ["d1"]
    assert d.confidence < 1.0 and set(d.probes_wanted) == {"cve", "community"}


def test_k_problem_reports_and_no_fix_is_hold():
    pool = [_d(1, "vendor_reddit", "Ubuntu 24.04 broke my wifi", date="2026-05-02"),
            _d(2, "vendor_reddit", "24.04 upgrade stuck at boot on ubuntu", date="2026-05-03"),
            _d(3, "vendor_releases", "Ubuntu 24.04 LTS released", date="2026-04-25")]
    d = D.decide(pool, Q, V)
    assert d.verdict == "hold" and set(d.evidence) == {"d1", "d2"}
    assert d.obligations["no_newer_fix_release"] is True


def test_one_report_is_not_a_hold():
    pool = [_d(1, "vendor_reddit", "Ubuntu 24.04 broke my wifi", date="2026-05-02"),
            _d(3, "vendor_releases", "Ubuntu 24.04 LTS released", date="2026-04-25")]
    assert D.decide(pool, Q, V).verdict == "safe"


def test_newer_fix_release_turns_hold_into_caveat():
    pool = [_d(1, "vendor_reddit", "Ubuntu 24.04 broke my wifi", date="2026-05-02"),
            _d(2, "vendor_reddit", "24.04 ubuntu boot loop", date="2026-05-03"),
            _d(3, "vendor_releases", "Ubuntu 24.04.1 fixes wifi regression", date="2026-06-01")]
    d = D.decide(pool, Q, V)
    assert d.verdict == "update_with_caveat" and "d3" in d.evidence


def test_breaking_change_in_release_note_is_a_caveat():
    pool = [_d(1, "vendor_releases", "Ubuntu 24.04", "Breaking change: PPAs are no longer supported")]
    assert D.decide(pool, Q, V).verdict == "update_with_caveat"


def test_advisory_with_cve_outranks_everything():
    pool = [_d(1, "cisa_kev", "[CISA KEV] Ubuntu kernel flaw", "CVE-2026-1234 exploited", "2026-05-01"),
            _d(2, "vendor_reddit", "Ubuntu 24.04 broke wifi", date="2026-05-02"),
            _d(3, "vendor_reddit", "ubuntu 24.04 crash", date="2026-05-02")]
    d = D.decide(pool, Q, V)
    assert d.verdict == "patch_urgently" and d.evidence == ["d1"]
    # KEV rows name a product, not an affected range: still patch, less sure
    assert d.confidence == 0.8
    pool[0]["text"] += " affects 24.04"
    assert D.decide(pool, Q, V).confidence == 1.0


def test_cve_id_in_the_url_counts():
    # KEV rows carry the id in the NVD link, not the headline (normalize_doc
    # drops cve_id); 757 of the sheet's KEV documents are like this.
    pool = [dict(_d(1, "cisa_kev", "[CISA KEV] Ubuntu kernel flaw", "exploited in the wild"),
                 url="https://nvd.nist.gov/vuln/detail/CVE-2026-1234")]
    assert D.decide(pool, Q, V).verdict == "patch_urgently"


def test_advisory_without_cve_id_is_not_an_advisory():
    pool = [_d(1, "cisa_kev", "Ubuntu something", "no id here")]
    assert D.decide(pool, Q, V).verdict != "patch_urgently"


def test_asked_version_gates_the_evidence():
    pool = [_d(1, "vendor_releases", "Ubuntu 22.04.5 released", "point release")]
    d = D.decide(pool, Q, V)                       # asks about 24.04, note is 22.04
    assert d.verdict == "insufficient_evidence" and d.stop_reason == "evidence_insufficient"
    assert d.obligations == dict(d.obligations, about_product=True, version_matched=False)
    assert D.decide(pool, "Is Ubuntu safe to upgrade?", V).verdict == "safe"   # no version asked


def test_prefix_version_match():
    pool = [_d(1, "vendor_releases", "Ubuntu 24.04.2 LTS", "point release")]
    assert D.decide(pool, Q, V).verdict == "safe"


def test_collapse_and_render():
    assert {D.COLLAPSE[v] for v in D.VERDICTS} == {"act", "hold", "insufficient_evidence"}
    pool = [_d(1, "vendor_releases", "Ubuntu 24.04.1 LTS released")]
    d = D.decide(pool, Q, V)
    assert d.verdict3 == "act"
    assert D.render(d, pool).startswith("Safe to update:") and "[Ubuntu 24.04.1" in D.render(d, pool)
    assert d.as_dict()["evidence_doc_ids"] == ["d1"]


def test_no_vendor_falls_back_to_question_overlap():
    pool = [_d(1, "vendor_releases", "Synology DSM 7.2.2 released", "NAS firmware")]
    assert D.decide(pool, "Synology DSM 7.2.2 upgrade safe?", []).verdict == "safe"
    assert D.decide(pool, "Is my toaster safe?", []).verdict == "insufficient_evidence"
