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


def test_a_name_that_is_also_a_word_is_searched_with_its_owner_word(monkeypatch):
    """"edge" alone returned other products' advisories (2026-11-19); the
    search is "microsoft edge", from vendor_kb.json `name_requires`."""
    asked = []
    monkeypatch.setattr(app_1, "union_fetch", lambda *a, **k: [])
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda *a, **k: ({"community": [], "releases": [], "cve": []}, []))
    monkeypatch.setattr(app_1, "rewrite_query", lambda q: Rewrite(q, "rule-based"))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    monkeypatch.setattr(nvd, "fetch", lambda kw, *a, **k: asked.append(kw) or [])
    app_1.run_pipeline("Is it safe to update Edge?", show_steps=False)
    assert asked == ["microsoft edge"]
    asked.clear()
    app_1.run_pipeline("Is it safe to update Chrome?", show_steps=False)
    assert asked == ["chrome"]


def test_a_product_with_no_kev_rows_is_asked_for_by_name(monkeypatch):
    """The KEV search is by query word: "WebRTC" took both slots with Google's
    Chromium WebRTC rows and Edge's own never arrived (2026-11-20). Only a
    product with no recent KEV row among those that arrived is asked for."""
    import multiagent_rag_v3 as marag
    monkeypatch.setenv("MARAG_RERANK", "bm25")   # no Ollama round trips
    edge = {"title": "[CISA KEV] Microsoft Internet Explorer and Edge Information Disclosure "
                     "Vulnerability \u2014 Internet Explorer and Edge",
            "subreddit": "CISA US-CERT", "source": "cisa_kev", "score": 0, "tier": 1,
            "verified": True, "url": "https://nvd.nist.gov/vuln/detail/CVE-2016-3351",
            "date": "2022-05-24", "cve_id": "CVE-2016-3351", "kev_vendor": "Microsoft",
            "kev_product": "Internet Explorer and Edge",
            "detail": "An information disclosure vulnerability exists in Internet Explorer and Edge."}
    asked = []
    monkeypatch.setattr(marag, "fetch_cisa_kev", lambda q, **k: asked.append(q) or [edge])
    monkeypatch.setattr(app_1, "union_fetch", lambda *a, **k: [])
    monkeypatch.setattr(app_1, "rewrite_query", lambda q: Rewrite(q, "rule-based"))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    monkeypatch.setattr(nvd, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda *a, **k: ({"community": [], "releases": [], "cve": []}, []))
    r = app_1.run_pipeline("Edge WebRTC vulnerability", show_steps=False)
    assert asked == ["microsoft edge"]
    assert [d["cve_id"] for d in r["cve"]] == ["CVE-2016-3351"]
    asked.clear()      # already has a recent Edge row: no second ask
    from datetime import timedelta
    recent = {**edge, "date": (app_1._clock().date() - timedelta(days=30)).isoformat()}
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda *a, **k: ({"community": [], "releases": [], "cve": [recent]}, []))
    app_1.run_pipeline("Edge WebRTC vulnerability", show_steps=False)
    assert asked == []


def test_edge_component_question_adds_chromium_upstream_rows_that_stay_out_of_the_verdict(monkeypatch):
    """Edge's records never name WebRTC, Chrome's do: the engine's CVEs are
    listed, tagged, and never counted for Microsoft's verdict."""
    monkeypatch.setenv("MARAG_RERANK", "bm25")
    edge = {"title": "CVE-2026-1 — Use after free in Microsoft Edge (Chromium-based) allows an attacker",
            "source": "nvd", "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-1", "cve_id": "CVE-2026-1",
            "date": "2026-11-10", "detail": "Use after free in Microsoft Edge (Chromium-based)",
            "severity": "HIGH", "is_cve": True, "verified": True, "tier": 1}
    chrome = {**edge, "title": "CVE-2026-2 — Use after free in WebRTC in Google Chrome prior to 158",
              "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-2", "cve_id": "CVE-2026-2",
              "detail": "Use after free in WebRTC in Google Chrome prior to 158"}
    monkeypatch.setattr(nvd, "fetch", lambda kw, *a, **k: [chrome] if kw == "chrome webrtc" else [edge])
    monkeypatch.setattr(app_1, "union_fetch", lambda *a, **k: [])
    monkeypatch.setattr(app_1, "terminal_sources", lambda *a, **k: ({"community": [], "releases": [], "cve": []}, []))
    monkeypatch.setattr(app_1, "rewrite_query", lambda q: Rewrite(q, "rule-based"))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    import multiagent_rag_v3 as marag
    monkeypatch.setattr(marag, "fetch_cisa_kev", lambda *a, **k: [])
    r = app_1.run_pipeline("WebRTC in Edge", show_steps=False)
    titles = [d["title"] for d in r["cve"]]
    assert any(t.startswith("[Chromium upstream") and "WebRTC" in t for t in titles)
    assert any("Microsoft Edge" in t and not t.startswith("[Chromium") for t in titles)
    r = app_1.run_pipeline("Is it safe to update Edge?", show_steps=False)
    assert not any(d["title"].startswith("[Chromium upstream") for d in r["cve"])
