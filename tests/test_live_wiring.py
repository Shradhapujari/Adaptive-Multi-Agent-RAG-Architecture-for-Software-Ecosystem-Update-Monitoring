"""The console routes outage, EOL, comparison, how-to and package questions to
live sources, behind the web-search toggle. Offline: every source is stubbed."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

import answer_agent  # noqa: E402
import app_1  # noqa: E402
import live_sources  # noqa: E402
import websearch  # noqa: E402
from app_1 import Rewrite  # noqa: E402

CVE_TEXT = ("requests 2.31.0: GHSA-9wx4-h78v-vm56 (CVE-2024-35195) Requests Session "
            "object does not verify requests after the first request. Fixed in 2.32.0.")
VERDICT_DOC = {"title": "GHSA-9wx4-h78v-vm56", "text": CVE_TEXT, "body": CVE_TEXT,
               "url": "https://osv.dev/vulnerability/GHSA-9wx4-h78v-vm56",
               "source": "cve", "is_cve": True, "date": "2024-05-20"}
ANSWER_DOC = {"title": "GHSA-9wx4-h78v-vm56", "text": "[untrusted:community] x [/untrusted]",
              "url": VERDICT_DOC["url"], "source": "live", "label": "OSV - GHSA-9wx4-h78v-vm56",
              "date": "2024-05-20", "host": "osv.dev"}
PKG_META = {"kind": "package_safety", "source": "OSV via PyPI, requests 2.31.0", "n": 1,
            "error": None, "resolved": True}


@pytest.fixture
def empty_lake(monkeypatch):
    monkeypatch.setattr(app_1, "union_fetch", lambda *a, **k: [])
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda *a, **k: ({"community": [], "releases": [], "cve": []}, []))
    monkeypatch.setattr(app_1, "rewrite_query", lambda q: Rewrite(q, "rule-based"))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    import nvd
    monkeypatch.setattr(nvd, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(websearch, "trusted",
                        lambda *a, **k: ([], {"backend": True, "n": 0, "used": True, "hosts": [], "error": None}))
    monkeypatch.setattr(websearch, "fallback",
                        lambda *a, **k: ([], {"backend": True, "n": 0, "used": True, "error": None}))
    monkeypatch.setattr(live_sources, "package_safety", lambda q: {
        "verdict_docs": [dict(VERDICT_DOC)], "answer_docs": [dict(ANSWER_DOC)], "meta": dict(PKG_META)})
    monkeypatch.setattr(live_sources, "fetch", lambda k, q: (
        [{"title": "status", "text": "[untrusted:community] ok [/untrusted]", "url": "https://www.githubstatus.com",
          "source": "live", "label": "Status page - githubstatus.com", "date": "", "host": "githubstatus.com"}],
        {"kind": k, "source": "GitHub status page", "n": 1, "error": None, "resolved": True}))


def test_osv_fixed_advisory_moves_the_verdict(empty_lake):
    r = app_1.run_pipeline("Is requests 2.31.0 safe? (pip)", show_steps=False, web_fallback=True)
    assert r["live"]["kind"] == "package_safety"
    assert r["decision"]["verdict"] == "patch_urgently"
    assert any(d.get("label") == "OSV - GHSA-9wx4-h78v-vm56" for d in r["web"])


def test_firefox_safety_stays_on_the_feed_path(empty_lake, monkeypatch):
    monkeypatch.setattr(live_sources, "package_safety", lambda q: pytest.fail("OSV on a feed question"))
    r = app_1.run_pipeline("Is it safe to update Firefox right now?", show_steps=False, web_fallback=True)
    assert r["live"] is None


def test_web_off_means_no_live_calls(empty_lake, monkeypatch):
    monkeypatch.setattr(live_sources, "fetch", lambda *a: pytest.fail("live read with web off"))
    monkeypatch.setattr(live_sources, "package_safety", lambda *a: pytest.fail("live read with web off"))
    r = app_1.run_pipeline("Is GitHub down?", show_steps=False, web_fallback=False)
    assert r["live"] is None


def test_trusted_and_live_docs_both_kept(empty_lake, monkeypatch):
    page = {"title": "vendor page", "text": "t", "url": "https://github.blog/x", "source": "web_trusted"}
    monkeypatch.setattr(websearch, "trusted",
                        lambda *a, **k: ([page], {"backend": True, "n": 1, "used": True, "hosts": [], "error": None}))
    r = app_1.run_pipeline("Is GitHub down?", show_steps=False, web_fallback=True)
    assert r["live"]["kind"] == "down_now"
    assert [d["url"] for d in r["web"]] == ["https://www.githubstatus.com", "https://github.blog/x"]


def test_live_label_is_used_as_evidence_label():
    w = {"title": "GitHub status", "text": "[untrusted:community] ok [/untrusted]",
         "url": "https://www.githubstatus.com", "source": "live",
         "label": "Status page - githubstatus.com", "date": ""}
    ev = answer_agent.collect_evidence({"web": [w]})
    assert ev[0].label == "Status page - githubstatus.com"


def test_resolved_live_source_passes_vendor_gate(monkeypatch):
    monkeypatch.setattr(answer_agent.vendor, "catalog_is_full", lambda: True)
    g = type("G", (), {"vendors": []})()
    q = "Is the Leftpad 1.3.0 package safe?"
    assert answer_agent.unresolved_products(q, {"grounding": g}) != []   # gate declines today
    assert answer_agent.unresolved_products(q, {"grounding": g, "live": {"resolved": True}}) == []


def test_eol_question_skips_fast_path(monkeypatch):
    monkeypatch.setattr(app_1.graph, "route_query", lambda q: ("fast", "single-product version lookup"))
    monkeypatch.setattr(app_1, "run_fast", lambda *a, **k: pytest.fail("fast path on a live question"))
    monkeypatch.setattr(app_1, "run_pipeline", lambda q, **kw: {"original_query": q, "route": None})
    monkeypatch.setattr(app_1, "present_answer", lambda *a, **k: None)
    app_1.ask("Is Python 3.9 still supported?", checks={"web_search": True})


def test_feed_question_keeps_the_fast_path(monkeypatch):
    called = []
    monkeypatch.setattr(app_1.graph, "route_query", lambda q: ("fast", "single-product version lookup"))
    monkeypatch.setattr(app_1, "run_fast", lambda *a, **k: called.append(1) or None)
    monkeypatch.setattr(app_1, "run_pipeline", lambda q, **kw: {"original_query": q, "route": None})
    monkeypatch.setattr(app_1, "present_answer", lambda *a, **k: None)
    app_1.ask("What is the latest Linux version?", checks={"web_search": True})
    assert called


def test_answer_only_question_shows_no_verdict(empty_lake, monkeypatch):
    """Only package safety gets a verdict; "Is GitHub down?" must not read "Patch now"."""
    adv = {"title": "GitHub Enterprise CVE-2026-9999", "notes": "CVE-2026-9999 in GitHub Enterprise Server",
           "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-9999", "is_cve": True, "product": "github"}
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda *a, **k: ({"community": [], "releases": [], "cve": [adv]}, []))
    r = app_1.run_pipeline("Is GitHub down?", show_steps=False, web_fallback=True)
    assert r["live"]["kind"] == "down_now" and r["decision"] is None


def test_live_docs_lead_the_web_pool(empty_lake, monkeypatch):
    pages = [{"title": f"vendor {i}", "text": "t", "url": f"https://python.org/{i}",
              "source": "web_trusted"} for i in range(4)]
    monkeypatch.setattr(websearch, "trusted",
                        lambda *a, **k: (pages, {"backend": True, "n": 4, "used": True, "hosts": [], "error": None}))
    r = app_1.run_pipeline("Is Python 3.9 still supported?", show_steps=False, web_fallback=True)
    ev = answer_agent.collect_evidence(r)
    assert "Status page - githubstatus.com" in [e.label for e in ev]   # the stubbed live doc
