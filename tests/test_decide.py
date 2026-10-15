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


# ── an advisory's subject, not merely its words ──────────────────────────────
# A product name anywhere in an advisory is how the product also gets
# mentioned in a sentence about something else. Real rows, from the store and
# the 200-question sheet.

LQ = "Any critical Linux kernel vulnerabilities right now?"
LV = ["Linux kernel"]


def test_an_advisory_about_another_product_is_not_evidence():
    """CVE-2026-79920, as /api/v/?q=linux returns it: product "linux",
    version "2.2.16", and a description about Ajenti. It was answering
    "any critical Linux kernel vulnerabilities?" with `patch_urgently`."""
    pool = [_d(1, "nvd", "linux v2.2.16 — Ajenti is a Linux & BSD modular server admin panel",
               "Ajenti is a Linux & BSD modular server admin panel. Prior to version "
               "2.2.16, any authenticated user can call /api/core/tasks/start")]
    d = D.decide(pool, LQ, LV)
    assert d.verdict == "insufficient_evidence", d.rationale
    assert not d.obligations["advisory_with_cve"]


def test_the_products_own_advisory_still_orders_a_patch():
    pool = [_d(1, "cisa_kev", "[CISA KEV] Linux Kernel Out-of-Bounds Write Vulnerability",
               "Linux Kernel contains an out-of-bounds write vulnerability in the "
               "ebtables SNAT target. CVE-2026-1234")]
    assert D.decide(pool, LQ, LV).verdict == "patch_urgently"


def test_a_word_shared_with_another_vendors_advisory_is_not_a_product_match():
    """From the sheet: a Linux question cited an Apple advisory because
    "kernel" appears in "kernel privileges", and a MySQL question cited
    Metabase because "sql" appears in "SQL Injection"."""
    apple = [_d(1, "cisa_kev", "[CISA KEV] Apple iOS and iPadOS Use-After-Free Vulnerability",
                "Apple iOS and iPadOS contain a use-after-free vulnerability. An app may "
                "be able to execute arbitrary code with kernel privileges. CVE-2026-2222")]
    assert D.decide(apple, LQ, LV).verdict != "patch_urgently"
    metabase = [_d(1, "cisa_kev", "[CISA KEV] Metabase SQL Injection Vulnerability",
                   "Metabase contains a SQL Injection vulnerability that allows an "
                   "unauthenticated remote attacker to inject SQL. CVE-2026-3333")]
    assert D.decide(metabase, "mysql.connector connection issue", ["MySQL / SQL"]).verdict \
        != "patch_urgently"


def test_a_weakness_first_advisory_naming_the_product_in_its_fix_clause_counts():
    """The live NVD feed files Firefox advisories weakness-first: the flaw is
    the subject, the product shows up only in the fix clause. The subject rule
    dropped these as not-about-Firefox, so after the citable_kinds fix "Is it
    safe to update Firefox right now?" still fell back to a green on the real
    feed. Naming the product as the thing patched is a product match."""
    pool = [_d(1, "nvd", "firefox v157.0.1 — Mitigation bypass in File Handling",
               "Mitigation bypass in the File Handling component. This "
               "vulnerability was fixed in Firefox 157.0.1. CVE-2026-106016")]
    assert D.decide(pool, "Is it safe to update Firefox right now?",
                    ["firefox"]).verdict == "patch_urgently"


def test_a_fix_clause_naming_another_vendor_is_still_not_a_product_match():
    """The fallback must not re-admit the cross-vendor rows the subject rule
    exists to reject: the capture stops at the comma, so only "Metabase 1.2"
    is tested, not the trailing MySQL mention."""
    pool = [_d(1, "nvd", "metabase — path traversal",
               "A path traversal vulnerability was fixed in Metabase 1.2, which "
               "also ships a MySQL connector. CVE-2026-3333")]
    assert D.decide(pool, "mysql.connector connection issue",
                    ["MySQL"]).verdict != "patch_urgently"


def test_an_advisory_with_no_readable_subject_is_left_alone():
    """NVD's other opener names the product after the predicate-free clause
    "In the Linux kernel, ...". The rule abstains rather than guessing."""
    pool = [_d(1, "nvd", "linux v6.19.0 — In the Linux kernel, a vulnerability",
               "In the Linux kernel, the following vulnerability has been resolved: "
               "net/mlx5e: fix a leak. CVE-2026-4444")]
    assert D.decide(pool, LQ, LV).verdict == "patch_urgently"


def test_the_subject_rule_does_not_reach_community_posts():
    """A post opens with whatever its author typed; the convention is the
    advisory catalogues', not Reddit's."""
    pool = [_d(1, "reddit_live", "Updates are broken after the Linux kernel upgrade",
               "Updates are broken for me, the kernel panics on boot", date="2026-10-01"),
            _d(2, "reddit_live", "Anyone else? Linux kernel update crashes",
               "same here, it crashes every boot", date="2026-10-02")]
    assert D.decide(pool, LQ, LV).verdict == "hold"


# ── a platform the product runs ON is not the product ───────────────────────
# Observed 2026-10-15 on "MacOS updates with negative community reaction":
# the gate returned "Patch now: 10 advisory document(s)" and cited VeraCrypt
# and Open Computer Use. Both pass the subject rule honestly -- "macOS" really
# is in their subject -- but it is there as the platform they run on, not as
# the product the advisory is about.

MQ = "MacOS updates with negative community reaction"
MV = ["macOS"]


def test_an_advisory_for_another_product_running_on_the_platform_is_not_evidence():
    veracrypt = [_d(1, "nvd", "macos v1.26.29 — VeraCrypt 1.26.29 (FUSE-T build) on macOS",
                    "VeraCrypt 1.26.29 (FUSE-T build) on macOS systems allows a local "
                    "attacker to bypass the passcode. CVE-2026-7777")]
    assert D.decide(veracrypt, MQ, MV).verdict != "patch_urgently"
    ocu = [_d(1, "nvd", "macos v1.0.0 — Open Computer Use through 1.0.0 on macOS",
              "Open Computer Use through 1.0.0 on macOS contains improper "
              "authentication. CVE-2026-8888")]
    assert D.decide(ocu, MQ, MV).verdict != "patch_urgently"


def test_the_platforms_own_advisory_still_orders_a_patch():
    pool = [_d(1, "cisa_kev", "[CISA KEV] Apple macOS Improper Authentication Vulnerability",
               "Apple macOS contains an improper authentication vulnerability that "
               "allows a local attacker to obtain sensitive information. CVE-2026-9999")]
    assert D.decide(pool, MQ, MV).verdict == "patch_urgently"


def test_a_product_named_before_its_platform_is_still_its_own_advisory():
    """"Firefox for iOS ..." is a Firefox advisory, not an iOS one."""
    row = ("Firefox for iOS directly interpolated the page's HTML language attribute "
           "into translation JavaScript, allowing attacker-controlled markup to "
           "execute code. This vulnerability was fixed in Firefox for iOS 157.1. "
           "CVE-2026-103418")
    ff = [_d(1, "nvd", "firefox v157.1.0 — Firefox for iOS", row)]
    assert D.decide(ff, "Is it safe to update Firefox right now?",
                    ["firefox"]).verdict == "patch_urgently"
    assert D.decide(ff, "Any critical iOS vulnerabilities?",
                    ["Apple iOS"]).verdict != "patch_urgently"
