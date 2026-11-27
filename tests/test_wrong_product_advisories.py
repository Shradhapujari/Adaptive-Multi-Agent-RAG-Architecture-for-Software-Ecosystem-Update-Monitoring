"""Advisories for other software must not turn a product's answer to Patch now.

Rows copied from the 2026-11-23 model-free console sweep:
  "What is the latest version of VS Code?" -> Collabora "Built-in CODE Server"
  "Latest Windows 11 version?" -> hMailServer's Windows installer, a WordPress plugin
  "What is the newest version of Java?" -> KEV rows the console itself labels legacy
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decide


def _kev(vendor_project, product, desc, date="2026-10-23", doc_id="k1"):
    return {"doc_id": doc_id, "source": "cisa_kev", "date": date,
            "title": f"[CISA KEV] {product} Vulnerability — {product}",
            "text": f"{desc} (CVE-2026-110447)", "kev_vendor": vendor_project,
            "kev_product": product}


def _nvd(text, doc_id="n1"):
    return {"doc_id": doc_id, "source": "nvd", "date": "20261111",
            "text": text, "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-126625"}


def _verdict(pool, vendor, q="What is the latest version?"):
    return decide.decide(pool, q, vendors=[vendor]).verdict


# ── KEV: one shared word is not the product ──────────────────────────────

def test_collabora_code_server_is_not_vs_code():
    row = _kev("Collabora", "Online – Built-in CODE Server",
               "Collabora Online – Built-in CODE Server contains an OS command injection vulnerability.")
    assert not decide.kev_owns(row, ["vs code"])
    assert _verdict([row], "vs code") != "patch_urgently"


def test_code_aurora_is_not_vs_code():
    row = _kev("Code Aurora", "ACDB Audio Driver",
               "Code Aurora ACDB Audio Driver contains a stack-based buffer overflow.")
    assert not decide.kev_owns(row, ["vs code"])


def test_a_single_word_product_still_matches_its_kev_row():
    row = _kev("Zimbra", "Collaboration (ZCS)", "Zimbra Collaboration contains an RCE.")
    assert decide.kev_owns(row, ["zimbra"])
    row = _kev("Jenkins", "Jenkins Script Console", "Jenkins contains a code injection flaw.")
    assert decide.kev_owns(row, ["jenkins"])


def test_a_two_word_product_named_whole_still_matches():
    row = _kev("Apache", "HTTP Server", "Apache HTTP Server contains a path traversal.")
    assert decide.kev_owns(row, ["apache http server"])


# ── NVD: Windows as another product's platform ───────────────────────────

HMAIL = ("Incorrect default permissions in the Windows installer of Progressive Robot "
         "hMailServer 6.3.7 allow a local authenticated user to run code as the administrator")
WP_PLUGIN = ("The OpenStation: Desktop Windows, Dock & Virtual Desktops for WP Admin plugin "
             "for WordPress is vulnerable to authorization bypass in all versions up to, "
             "and including, 1.1.16.")
REAL_WINDOWS = ("Use after free in Windows Win32K - GRFX allows an authorized attacker "
                "to elevate privileges locally.")


def test_another_products_windows_installer_is_not_windows():
    assert _verdict([_nvd(HMAIL)], "windows") != "patch_urgently"


def test_a_wordpress_plugin_named_after_windows_is_not_windows():
    assert _verdict([_nvd(WP_PLUGIN)], "windows") != "patch_urgently"


def test_a_real_windows_advisory_still_counts():
    assert _verdict([_nvd(REAL_WINDOWS)], "windows") == "patch_urgently"


def test_a_wordpress_plugin_still_counts_for_the_plugin_itself():
    text = ("The Elementor Website Builder plugin for WordPress is vulnerable to "
            "stored XSS in all versions up to, and including, 3.20.1.")
    assert _verdict([_nvd(text)], "elementor") == "patch_urgently"


# ── KEV entries the console shows as legacy history ──────────────────────

def test_a_legacy_kev_row_does_not_drive_patch_now():
    row = {**_kev("Oracle", "Java SE", "Oracle Java SE contains an unspecified vulnerability.",
                  date="2022-05-25"), "legacy": True}
    assert decide.kev_owns(row, ["java"])
    assert _verdict([row], "java") != "patch_urgently"


def test_console_tags_old_kev_rows_legacy(monkeypatch):
    import app_1
    from datetime import datetime
    monkeypatch.setattr(app_1, "_clock", lambda: datetime(2026, 11, 23))
    old = _kev("Oracle", "Java SE", "x", date="2022-05-25", doc_id="old")
    new = _kev("Oracle", "Java SE", "y", date="2026-11-01", doc_id="new")
    shown = {r["doc_id"]: r for r in app_1._show_cve([new, old], 5)}
    assert shown["old"].get("legacy") is True
    assert not shown["new"].get("legacy")


# ── The release feed's advisory rows: the list the answer shows ──────────

def test_release_feed_rows_for_other_products_are_not_windows():
    import vendor
    assert not vendor.advisory_names_vendor({"notes": HMAIL}, "windows")
    assert not vendor.advisory_names_vendor({"notes": WP_PLUGIN}, "windows")
    assert vendor.advisory_names_vendor({"notes": REAL_WINDOWS}, "windows")


def test_a_plugin_named_for_the_product_stays_the_products():
    import vendor
    text = ("The Elementor Website Builder plugin for WordPress is vulnerable to "
            "stored XSS in all versions up to, and including, 3.20.1.")
    assert vendor.advisory_names_vendor({"notes": text}, "elementor")
    assert not vendor.other_wordpress_plugin(text, "elementor")
    assert vendor.other_wordpress_plugin(WP_PLUGIN, "windows")


def test_verdict_pool_keeps_the_legacy_tag():
    import app_1
    row = {**_kev("Oracle", "Java SE", "Oracle Java SE contains an unspecified vulnerability.",
                  date="2022-05-25"), "legacy": True,
           "url": "https://nvd.nist.gov/vuln/detail/CVE-2013-0422"}
    pool = app_1._decide_pool({"cve": [row]})
    assert pool[0].get("legacy") is True
    assert decide.decide(pool, "What is the newest version of Java?",
                         vendors=["java"]).verdict != "patch_urgently"


# ── Another product's name right before an owned product's ───────────────

import pytest


@pytest.mark.parametrize("text", [
    "OpenClaw Windows Node before 2026.7.1 contains an incomplete validation vulnerability "
    "that lets remote callers run commands on the Windows host.",
    "Maono Link 3.8.13 MaonoAiServices Windows service allows local privilege escalation.",
    "An issue in iTerm2 macOS before 3.6.12 allows code execution.",
])
def test_another_products_name_before_the_product_is_not_it(text):
    import vendor
    want = "macos" if "macOS" in text else "windows"
    assert vendor.foreign_name_before(text, want)
    assert not vendor.advisory_names_vendor({"notes": text}, want)
    assert _verdict([_nvd(text)], want) != "patch_urgently"


@pytest.mark.parametrize("text, want", [
    (REAL_WINDOWS, "windows"),
    ("Windows Kernel Elevation of Privilege Vulnerability allows a local attacker to gain SYSTEM.", "windows"),
    ("Out-of-bounds read in Microsoft Windows SMB allows an attacker to disclose memory.", "windows"),
    ("The Windows Common Log File System driver allows elevation of privilege.", "windows"),
    ("Use after free in Google Chrome prior to 158.0 allowed a remote attacker to execute code.", "chrome"),
    ("Microsoft Edge (Chromium-based) Spoofing Vulnerability allows spoofing.", "edge"),
    ("Canonical Ubuntu 24.04 allows local root.", "ubuntu"),
])
def test_the_owners_own_advisories_still_count(text, want):
    import vendor
    assert not vendor.foreign_name_before(text, want)


@pytest.mark.parametrize("text", [
    "SumatraPDF is a multi-format reader for Windows. In 3.6.1 and earlier, it embeds text "
    "in quoted Windows command lines.",
    "When password authentication is used with the Windows port of wolfSSHd, the Windows "
    "logon token is not released.",
    "CrowdStrike released a security update to address a vulnerability in the Falcon sensor "
    "for Windows.",
])
def test_console_lists_only_advisories_the_verdict_accepts(text):
    import app_1
    from vendor import VendorMatch
    row = {"is_cve": True, "notes": text, "product": "windows",
           "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-107802"}
    assert app_1._on_subject([row], [VendorMatch(name="windows", matched="Windows")]) == []


def test_console_still_lists_a_real_windows_advisory():
    import app_1
    from vendor import VendorMatch
    row = {"is_cve": True, "notes": REAL_WINDOWS, "product": "windows",
           "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-1"}
    assert app_1._on_subject([row], [VendorMatch(name="windows", matched="Windows")]) == [row]


def test_a_leading_cve_id_is_not_a_foreign_name():
    import vendor
    text = "CVE-2026-2001 Linux kernel before 6.17.2 contains a use-after-free."
    assert not vendor.foreign_name_before(text, "linux")
    row = {"doc_id": "n1", "source": "nvd", "title": "CVE-2026-2001",
           "text": "Linux kernel before 6.17.2 contains a use-after-free. (CVE-2026-2001)"}
    assert _verdict([row], "linux") == "patch_urgently"


@pytest.mark.parametrize("text, want", [
    ("In Eclipse BaSyx Java Server SDK versions 2.0.0-milestone-10 to 2.0.0-milestone-16, "
     "the destination validation is missing.", "insufficient_evidence"),
    ("Vulnerability in the Java SE product of Oracle Java SE (component: Hotspot) allows takeover.",
     "patch_urgently"),
    ("A flaw in OpenJDK Java allows sandbox bypass.", "patch_urgently"),
])
def test_java_advisories_belong_to_oracle_or_openjdk(text, want):
    row = {"doc_id": "n1", "source": "nvd", "date": "20261111", "title": "CVE-2026-135125",
           "text": f"{text} (CVE-2026-135125)",
           "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-135125"}
    assert decide.decide([row], "What is the newest version of Java?",
                         vendors=["java"]).verdict == want


# ── 2026-11-25 sweep: plugins, bundlers, possessives, legacy text ────────

def _nvd_row(text):
    return {"doc_id": "n1", "source": "nvd", "date": "20261124", "title": "CVE-2026-136214",
            "text": f"{text} (CVE-2026-136214)",
            "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-136214"}


@pytest.mark.parametrize("want, text", [
    ("wordpress", "Astra WordPress theme before 4.14.0 contains an improper input neutralization vulnerability."),
    ("wordpress", "Prevent Direct Access – Protect WordPress Files plugin before 2.8.9.2 contains an "
                  "information disclosure vulnerability."),
    ("wordpress", "The Synoptic Web Designer: best WordPress design tool WordPress plugin through 1.12 "
                  "does not perform any capability check."),
    ("python", "Python Packaging Authority pip Configuration File Incorrect Permission Assignment "
               "Local Privilege Escalation Vulnerability."),
    ("python", "Flowintel's community data launcher script passes the admin API key as a command-line "
               "argument to a child Python helper process."),
    ("openssl", "An uncontrolled search path vulnerability (CWE-427) in statically linked OpenSSL "
                "libraries within Netskope Client (stAgentSvc.exe) on Windows allows code execution."),
    ("openssl", "A high privileged remote attacker can perform an OpenSSL code injection in the "
                "backends ImportPKCS12 function leading to code execution."),
])
def test_another_products_advisory_is_not_the_product(want, text):
    assert decide.decide([_nvd_row(text)], f"Any security issues in {want}?",
                         vendors=[want]).verdict != "patch_urgently"


@pytest.mark.parametrize("want, text", [
    ("openssl", "Issue summary: A QUIC peer that sends many small out-of-order STREAM fragments may "
                "cause OpenSSL to buffer a large amount of data."),
    ("python", "Python's tarfile module before 3.14.1 allows path traversal."),
    ("wordpress", "WordPress Core before 6.8.2 allows stored XSS via the theme customizer."),
])
def test_the_products_own_advisory_still_counts(want, text):
    assert decide.decide([_nvd_row(text)], f"Any security issues in {want}?",
                         vendors=[want]).verdict == "patch_urgently"


def test_zimbra_is_detected_and_owns_its_kev_rows():
    import vendor
    assert [v.name for v in vendor.detect_vendors("Is it safe to update Zimbra?")] == ["zimbra"]
    assert decide.kev_owns(_kev("Synacor", "Zimbra Collaboration Suite (ZCS)", "XSS"), ["zimbra"])
    assert not decide.kev_owns(_kev("Cisco", "Secure Firewall ASA Software", "NULL deref"), ["zimbra"])


def test_console_list_reads_the_kb_exclusions():
    import app_1
    from vendor import VendorMatch
    row = {"is_cve": True, "product": "python", "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-136440",
           "notes": "Python Packaging Authority pip Configuration File Incorrect Permission Assignment."}
    assert app_1._on_subject([row], [VendorMatch(name="python", matched="Python")]) == []


def test_legacy_kev_rows_are_not_said_to_apply():
    import answer_agent as A
    ev = [A.Evidence(label="Security Advisory - CVE-2013-0422 (CISA US-CERT), 2022-05-25",
                     kind="advisory", title="Oracle JRE Remote Code Execution Vulnerability",
                     source="cisa_kev", security=True, legacy=True)]
    text = A.deterministic_paragraph("What is the newest version of Java?", ev)
    assert "apply" not in text and "older advisory record(s)" in text


def test_a_bare_link_is_not_quoted_as_a_note():
    import answer_agent as A
    assert A._BARE_URL.match("https://en.wikipedia.org/wiki/WordPress")
    assert not A._BARE_URL.match("Fixes a crash, see https://x.org/1")


# ── "safe" must not stand on a search that never reached the product ────

def _pipeline(monkeypatch, fetch):
    import app_1, nvd
    from app_1 import Rewrite
    monkeypatch.setattr(app_1, "union_fetch", lambda *a, **k: [])
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda *a, **k: ({"community": [], "releases": [], "cve": []}, []))
    monkeypatch.setattr(app_1, "rewrite_query", lambda q: Rewrite(q, "rule-based"))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    monkeypatch.setattr(nvd, "fetch", fetch)
    return app_1.run_pipeline("Any security issues in Python?", show_steps=False)


def _foreign(i):
    return {"title": f"CVE-2026-{9000 + i} — Acme{i} is a Python package", "source": "nvd",
            "url": f"https://nvd.nist.gov/vuln/detail/CVE-2026-{9000 + i}", "date": "2026-11-20",
            "text": f"Acme{i} is a Python package. Prior to 1.{i} it allows code execution.",
            "is_cve": True}


def test_a_page_of_other_products_leaves_cves_unchecked(monkeypatch):
    import app_1
    r = _pipeline(monkeypatch, lambda kw, limit=5, *a, **k: [_foreign(i) for i in range(limit)])
    assert any(e["agent"] == "NVD (crowded)" for e in r["errors"])
    assert "cve" in app_1._unchecked(r["errors"])


def test_the_projects_own_name_is_searched_and_counts(monkeypatch):
    import app_1
    own = {"title": "CVE-2026-82049 — In CPython 3.13 and earlier, the tarfile module",
           "source": "nvd", "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-82049",
           "date": "2026-09-14", "is_cve": True,
           "text": "In CPython 3.13 and earlier, the tarfile module's extraction filters are "
                   "vulnerable to crafted archives."}
    asked = []

    def fetch(kw, limit=5, *a, **k):
        asked.append(kw)
        return [own] if kw == "cpython" else [_foreign(i) for i in range(limit)]
    r = _pipeline(monkeypatch, fetch)
    assert "cpython" in asked
    assert [d["url"].rsplit("/", 1)[-1] for d in r["cve"] if "82049" in d["url"]] == ["CVE-2026-82049"]
    assert not any(e["agent"] == "NVD (crowded)" for e in r["errors"])


def test_an_nvd_outage_leaves_cves_unchecked():
    import app_1
    assert app_1._unchecked([{"agent": "NVD", "error": "HTTPError: 503"}]) == {"cve"}


def test_safe_needs_the_cve_source_read():
    rel = {"doc_id": "r1", "source": "releases", "date": "2026-10-25",
           "text": "Python 3.14.10 released with bug fixes."}
    assert decide.decide([rel], "Any security issues in Python?", vendors=["python"]).verdict == "safe"
    assert decide.decide([rel], "Any security issues in Python?", vendors=["python"],
                         unchecked={"cve"}).verdict == "insufficient_evidence"


PULP = ("A **server-side request forgery** flaw has been found in the get_remote_artifact_url() "
        "function in pulp_python/app/models.py of the pull-through caching feature in the "
        "**pulp_python** package. The function uses the redirect query parameter as the URL to "
        "download. A network attacker who can reach the content app of a Python distribution "
        "that has a remote can choose the URL.")
TARFILE = ("In CPython 3.13 and earlier, the tarfile\xa0module's data\xa0and tar extraction filters "
           "are vulnerable to crafted archives containing a hard link to a symbolic link.")


def test_a_package_named_after_python_is_not_python():
    # The subject stops at the first sentence; "a Python distribution" two
    # sentences on is where the package runs, not what it is.
    assert decide.decide([_nvd_row(PULP)], "Any security issues in Python?",
                         vendors=["python"]).verdict != "patch_urgently"


def test_cpython_rows_reach_the_console_list_and_the_verdict():
    import app_1, vendor
    from vendor import VendorMatch
    row = {"is_cve": True, "source": "nvd", "text": TARFILE, "detail": TARFILE, "notes": TARFILE,
           "title": "CVE-2026-82049 — " + TARFILE[:60],
           "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-82049"}
    assert vendor.advisory_names_vendor(row, "python")
    assert app_1._on_subject([row], [VendorMatch(name="python", matched="Python")]) == [row]
    assert decide.decide([_nvd_row(TARFILE)], "Any security issues in Python?",
                         vendors=["python"]).verdict == "patch_urgently"


def test_a_crowded_page_is_not_a_degraded_fetch(monkeypatch):
    import app_1
    r = _pipeline(monkeypatch, lambda kw, limit=5, *a, **k: [_foreign(i) for i in range(limit)])
    assert r["decision"].get("evidence_class") != "degraded"


# GitHub's CNA writes "<weakness> was identified in GitHub Enterprise Server"
# and fixes "in versions 3.17.12": the product is in neither the subject nor
# the fix clause, so all GHES advisories read as not-about-GitHub and the
# sweep-5 GitHub answer listed four CVEs under insufficient_evidence.
_GHES = ("A stored cross-site scripting vulnerability was identified in GitHub "
         "Enterprise Server that allowed an organization member with permission to "
         "manage custom-property definitions to inject scripts. This vulnerability "
         "affected all versions of GitHub Enterprise Server prior to 3.23 and was "
         "fixed in versions 3.17.12, 3.18.6.")


def test_an_identified_in_advisory_names_its_product():
    assert _verdict([_nvd(_GHES)], "github",
                    q="Any security vulnerabilities in GitHub?") == "patch_urgently"


def test_identified_in_another_product_is_still_not_this_one():
    # VulDB's shape; the GitHub word is the bug tracker, not the product.
    text = ("A weakness has been identified in AIP-PUB ACPs-community up to 2.2.0. "
            "The reported GitHub issue was closed.")
    assert _verdict([_nvd(text)], "github",
                    q="Any security vulnerabilities in GitHub?") != "patch_urgently"
