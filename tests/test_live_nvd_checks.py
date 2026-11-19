"""The live NVD feed reaches the CVE pool scoped by owner, and the sidebar's
Vendor check really switches that scoping (2026-11-15)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_1  # noqa: E402
import nvd  # noqa: E402
from app_1 import Rewrite  # noqa: E402

CHROME = {"title": "CVE-2026-1 — Use after free in Skia in Google Chrome prior to 157.0.8103.78",
          "source": "nvd", "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-1", "date": "2026-11-11",
          "text": "Use after free in Skia in Google Chrome prior to 157.0.8103.78 allows a remote attacker "
                  "to exploit heap corruption via a crafted HTML page. (Chromium security severity: High)",
          "is_cve": True}
HONO = {"title": "CVE-2026-2 — Hono is a Web application framework",
        "source": "nvd", "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-2", "date": "2026-11-13",
        "text": "Hono is a Web application framework that runs on any JavaScript runtime. Prior to 4.9 "
                "a request from chrome could bypass CSRF checks.", "is_cve": True}


def _run(monkeypatch, **checks):
    monkeypatch.setattr(app_1, "union_fetch", lambda *a, **k: [])
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda *a, **k: ({"community": [], "releases": [], "cve": []}, []))
    monkeypatch.setattr(app_1, "rewrite_query", lambda q: Rewrite(q, "rule-based"))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    monkeypatch.setattr(nvd, "fetch", lambda *a, **k: [CHROME, HONO])
    r = app_1.run_pipeline("Is it safe to update Chrome?", show_steps=False, checks=checks)
    return {d["url"].rsplit("/", 1)[-1] for d in r["cve"]}


def test_nvd_rows_are_scoped_to_the_owner(monkeypatch):
    assert _run(monkeypatch) == {"CVE-2026-1"}


def test_vendor_check_off_keeps_every_nvd_row(monkeypatch):
    assert _run(monkeypatch, vendor_check=False) == {"CVE-2026-1", "CVE-2026-2"}


def test_vendor_filter_may_empty_the_release_pool(monkeypatch):
    # 2026-11-17: rows with product "vulnerability" were restored as Zig releases.
    junk = [{"product": "vulnerability", "version": "10.3.26", "date": "2026-11-01",
             "notes": "Path Traversal", "url": "https://x/1", "is_cve": False}]
    monkeypatch.setattr(app_1, "union_fetch", lambda fn, *a, **k: junk if fn.__name__ == "fetch" and a and "zig" in a[0] else [])
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda *a, **k: ({"community": [], "releases": junk, "cve": []}, []))
    monkeypatch.setattr(app_1, "rewrite_query", lambda q: Rewrite(q, "rule-based"))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    monkeypatch.setattr(nvd, "fetch", lambda *a, **k: [])
    r = app_1.run_pipeline("What is the latest version of Zig?", show_steps=False)
    assert r["releases"] == []


def test_a_component_in_the_question_is_searched_with_its_product(monkeypatch):
    """"Any WebRTC vulnerabilities in Chrome?" searches NVD for "chrome webrtc"
    first; the newest-N "chrome" search held 1 WebRTC CVE in 20 (2026-11-19)."""
    asked = []
    monkeypatch.setattr(app_1, "union_fetch", lambda *a, **k: [])
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda *a, **k: ({"community": [], "releases": [], "cve": []}, []))
    monkeypatch.setattr(app_1, "rewrite_query", lambda q: Rewrite(q, "rule-based"))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    monkeypatch.setattr(nvd, "fetch", lambda kw, *a, **k: asked.append(kw) or [])
    app_1.run_pipeline("Any WebRTC vulnerabilities in Chrome?", show_steps=False)
    assert asked == ["chrome webrtc", "chrome"]
    asked.clear()
    app_1.run_pipeline("Is it safe to update Chrome?", show_steps=False)
    assert asked == ["chrome"]
