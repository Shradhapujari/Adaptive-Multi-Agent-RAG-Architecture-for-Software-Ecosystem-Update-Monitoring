"""CISA KEV rows carry the affected vendor and product as fields. Ownership is
read from those, not from the description text: a homonym (VMware "SD-WAN
Edge", Cisco "IOS") must not turn Edge or iOS red, and Chrome's KEV rows --
filed as Google "Chromium V8" -- must count for Chrome.

(vendorProject, product) pairs are copied from the live catalogue, 2026-11-12.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decide


def _kev(vendor_project, product, desc, cve="CVE-2026-1001"):
    return {"doc_id": "k1", "source": "cisa_kev",
            "title": f"[CISA KEV] {product} Vulnerability — {product}",
            "text": f"{desc} ({cve})", "kev_vendor": vendor_project, "kev_product": product}


CASES = [
    # (asked product, row, expected verdict)
    ("edge", _kev("VMware", "SD-WAN Edge", "VMware SD-WAN Edge contains a command injection vulnerability."),
     "insufficient_evidence"),
    ("edge", _kev("Microsoft", "Edge", "Microsoft Edge contains a memory corruption vulnerability."),
     "patch_urgently"),
    ("ios", _kev("Cisco", "IOS and IOS XE Software", "Cisco IOS and IOS XE Software contain a denial-of-service vulnerability."),
     "insufficient_evidence"),
    ("ios", _kev("Apple", "iOS and iPadOS", "Apple iOS and iPadOS contain a memory corruption vulnerability."),
     "patch_urgently"),
    ("chrome", _kev("Google", "Chromium V8", "Google Chromium V8 contains a type confusion vulnerability."),
     "patch_urgently"),
    ("linux", _kev("Android", "Kernel", "Android Linux kernel contains a use-after-free vulnerability."),
     "insufficient_evidence"),
    ("linux", _kev("Linux", "Kernel", "Linux kernel contains a use-after-free vulnerability."),
     "patch_urgently"),
    ("windows", _kev("Microsoft", "Win32k", "Microsoft Win32k contains a privilege escalation vulnerability."),
     "patch_urgently"),
    ("windows", _kev("Intel", "Ethernet Diagnostics Driver for Windows",
                     "Intel Ethernet Diagnostics Driver for Windows contains a vulnerability."),
     "insufficient_evidence"),
    ("windows", _kev("Microsoft", "Office", "Microsoft Office contains a remote code execution vulnerability."),
     "insufficient_evidence"),
    ("node.js", _kev("Npm package", "System Information Library for Node.JS",
                     "Node.JS System Information Library contains a command injection vulnerability."),
     "insufficient_evidence"),
    # Apple files many rows as "Multiple Products"; the description decides.
    ("macos", _kev("Apple", "Multiple Products", "Apple iOS, iPadOS, and macOS contain a type confusion vulnerability."),
     "patch_urgently"),
    # A product with no owner on file still reads the structured fields,
    # with the platform after "for" cut off.
    ("teams", _kev("Mattermost", "Server", "Mattermost Teams edition contains an IDOR vulnerability."),
     "insufficient_evidence"),
]


@pytest.mark.parametrize("product,row,want", CASES, ids=[f"{p}-{r['kev_vendor']}-{r['kev_product']}" for p, r, _ in CASES])
def test_kev_ownership_reads_the_structured_fields(product, row, want):
    d = decide.decide([row], f"Is it safe to update {product}?", vendors=[product])
    assert d.verdict == want, d.rationale


def test_a_row_without_the_fields_keeps_the_text_rule():
    # Recorded corpora predate the fields; their verdicts must not move.
    row = {"doc_id": "k1", "source": "cisa_kev", "title": "",
           "text": "Microsoft Edge contains a memory corruption vulnerability (CVE-2026-1001)."}
    assert decide.decide([row], "Is it safe to update Edge?", vendors=["edge"]).verdict == "patch_urgently"


def test_any_asked_product_may_own_the_row():
    # Grounding can return more than one name ("edge", "safe").
    row = _kev("Microsoft", "Edge", "Microsoft Edge contains a memory corruption vulnerability.")
    assert decide.decide([row], "Is it safe to update Edge?", vendors=["edge", "safe"]).verdict == "patch_urgently"


# ---- the fetcher keeps the fields and matches whole words ------------------

CATALOG = (
    {"cveID": "CVE-2026-0001", "vendorProject": "Microsoft", "product": "Windows",
     "vulnerabilityName": "Microsoft Windows SMB Missing Authentication Vulnerability",
     "shortDescription": "Microsoft Windows SMB contains a missing authentication vulnerability that this exploit uses.",
     "dateAdded": "2026-10-01"},
    {"cveID": "CVE-2026-0002", "vendorProject": "Google", "product": "Chromium V8",
     "vulnerabilityName": "Google Chromium V8 Type Confusion Vulnerability",
     "shortDescription": "Google Chromium V8 contains a type confusion vulnerability.",
     "dateAdded": "2026-10-02"},
    {"cveID": "CVE-2026-0003", "vendorProject": "VMware", "product": "SD-WAN Edge",
     "vulnerabilityName": "VMware SD-WAN Edge Command Injection Vulnerability",
     "shortDescription": "VMware SD-WAN Edge contains a command injection vulnerability.",
     "dateAdded": "2026-10-03"},
)


@pytest.fixture
def marag(monkeypatch):
    import multiagent_rag_v3 as m
    monkeypatch.setattr(m, "_kev_catalog", lambda bucket: CATALOG)
    return m


def test_fetch_keeps_vendor_and_product(marag):
    rows = marag.fetch_cisa_kev("Is it safe to update Chrome?", limit=3)
    assert [(r["kev_vendor"], r["kev_product"], r["cve_id"]) for r in rows] == \
        [("Google", "Chromium V8", "CVE-2026-0002")]


def test_fetch_ignores_function_words(marag):
    # "is"/"it" used to match as substrings of every description ("this",
    # "missing"), so an unrelated Windows row came back for a Node.js question.
    assert marag.fetch_cisa_kev("Is it safe to update Node.js?", limit=3) == []


def test_fetch_returns_the_homonym_and_decide_drops_it(marag):
    rows = marag.fetch_cisa_kev("Is it safe to update Edge?", limit=3)
    assert [r["kev_vendor"] for r in rows] == ["VMware"]
    row = dict(rows[0], doc_id="k", text=rows[0]["detail"])
    assert decide.decide([row], "Is it safe to update Edge?", vendors=["edge"]).verdict \
        == "insufficient_evidence"


def test_decide_pool_carries_the_fields():
    import app_1
    row = {"title": "[CISA KEV] x", "detail": "Google Chromium V8 contains a flaw (CVE-2026-0002).",
           "source": "cisa_kev", "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-0002",
           "kev_vendor": "Google", "kev_product": "Chromium V8"}
    pool = app_1._decide_pool({"cve": [row]})
    assert pool[0]["kev_vendor"] == "Google" and pool[0]["kev_product"] == "Chromium V8"
    assert decide.decide(pool, "Is it safe to update Chrome?", vendors=["chrome"]).verdict == "patch_urgently"


def test_console_scopes_kev_rows_by_ownership_not_by_forum_filter():
    # vendor.filter_community is the Reddit filter; it dropped Chrome's
    # "Chromium V8" rows before decide ever saw them, and kept VMware's
    # "SD-WAN Edge" for an Edge question.
    import app_1
    import grounding

    def kev(vp, prod, desc, cve):
        return {"title": f"[CISA KEV] {prod} Vulnerability — {prod}", "subreddit": "CISA US-CERT",
                "source": "cisa_kev", "url": f"https://nvd.nist.gov/vuln/detail/{cve}",
                "detail": desc, "kev_vendor": vp, "kev_product": prod}
    v8 = kev("Google", "Chromium V8", "Google Chromium V8 contains a type confusion vulnerability.", "CVE-2026-0002")
    sdwan = kev("VMware", "SD-WAN Edge", "VMware SD-WAN Edge contains a command injection vulnerability.", "CVE-2026-0003")
    edge = kev("Microsoft", "Edge", "Microsoft Edge contains a memory corruption vulnerability.", "CVE-2026-0004")
    assert app_1._scope_cve([v8, sdwan], grounding.ground("Is it safe to update Chrome?")) == [v8]
    assert app_1._scope_cve([v8, sdwan, edge], grounding.ground("Is it safe to update Edge?")) == [edge]
