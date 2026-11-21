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


def test_live_answer_headline_is_the_answer_not_an_abstention(monkeypatch):
    """Live check 2026-11-19: "Is Python 3.9 still supported?" cited endoflife.date
    and still read "Not enough evidence — no document is about the asked product"."""
    from answer_agent import PresentedAnswer
    shown = []
    for fn in ("markdown", "write", "caption"):
        monkeypatch.setattr(app_1.st, fn, lambda s, *a, **k: shown.append(str(s)))
    app_1._tab_short({"decision": None, "original_query": "Is Python 3.9 still supported?",
                      "live": {"kind": "eol", "source": "endoflife.date", "n": 1, "error": None,
                               "resolved": True, "answer_only": True}},
                     PresentedAnswer("Python 3.9 reached end of life on 2025-10-31 [S1].", "llm"))
    assert shown[1] == "### Python 3.9 reached end of life on 2025-10-31."   # headlines drop [S1]
    assert any("End of life question → endoflife.date" in s for s in shown)
    assert not any("Not enough evidence" in s or "Which product" in s for s in shown)


@pytest.mark.parametrize("q", ["Is requests 2.31.0 safe? (pip)", "How do I fix EACCES on npm install?"])
def test_package_ecosystem_questions_pass_the_entry_gate_when_live(q):
    """Live check 2026-11-19: both were declined as "Not a software update question"."""
    assert app_1._off_topic_note(q, live=True) is None
    assert app_1._off_topic_note(q) is not None          # web off: unchanged


def test_off_topic_how_to_stays_declined_when_live():
    assert app_1._off_topic_note("How do I bake bread?", live=True)


def test_osv_rows_are_attributed_to_osv_in_sources(monkeypatch):
    """Live check 2026-11-19: OSV advisories were listed as "CISA KEV / NVD"."""
    monkeypatch.setattr(live_sources, "_get_json", lambda url, post=None, timeout=10: (
        ({"vulns": [{"id": "GHSA-x", "aliases": ["CVE-2024-1"], "summary": "s",
                     "affected": [{"ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.32.0"}]}]}]}]}, None)
        if post else ({"info": {"version": "2.34.2"}}, None)))
    pkg = live_sources.package_safety("Is requests 2.31.0 safe? (pip)")
    rows = app_1._source_rows({"decision_advisories": pkg["verdict_docs"]})
    assert [r["Tier"] for r in rows] == ["OSV"]



def test_cve_question_keeps_its_verdict_with_web_on(empty_lake, monkeypatch):
    """Review #1: "fix" made this a how-to, and "Patch now" disappeared."""
    adv = {"title": "Chrome CVE-2024-1234", "notes": "CVE-2024-1234 use after free in Google Chrome",
           "url": "https://nvd.nist.gov/vuln/detail/CVE-2024-1234", "is_cve": True, "product": "chrome"}
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda *a, **k: ({"community": [], "releases": [], "cve": [adv]}, []))
    r = app_1.run_pipeline("Does Chrome 131 fix CVE-2024-1234?", show_steps=False, web_fallback=True)
    assert r["decision"] is not None and not r["live"]["answer_only"]
    assert r["web"][-1]["url"] == "https://www.githubstatus.com"   # appended, not leading


def test_clean_package_result_carries_no_verdict(empty_lake, monkeypatch):
    """Review #10: with no OSV hit the feed pool is unscoped, and its "safe" would be a false green."""
    monkeypatch.setattr(live_sources, "package_safety", lambda q: {
        "verdict_docs": [], "answer_docs": [dict(ANSWER_DOC)], "meta": dict(PKG_META)})
    r = app_1.run_pipeline("Is the requests package safe to use?", show_steps=False, web_fallback=True)
    assert r["decision"] is None and r["live"]["answer_only"]


def test_a_vendorless_question_gets_only_on_subject_community_posts(empty_lake, monkeypatch):
    # The community feed ignores `q`; the subject filter only ran when a
    # catalog vendor was detected, so this question got the whole global feed.
    posts = [{"title": "Edge hijacked by organization", "subreddit": "MicrosoftEdge"},
             {"title": "CrowdStrike outage took down our fleet", "subreddit": "sysadmin"}]
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda *a, **k: ({"community": [dict(p) for p in posts],
                                          "releases": [], "cve": []}, []))
    q = "Any news on the CrowdStrike outage?"
    import grounding
    assert grounding.ground(q).vendors == []          # precondition: no catalog vendor
    r = app_1.run_pipeline(q, show_steps=False, web_fallback=False)
    assert [p["title"] for p in r["community"]] == ["CrowdStrike outage took down our fleet"]


@pytest.mark.parametrize("q", ["Is GitHub down?", "Is Python 3.9 still supported?"])
def test_outage_and_eol_questions_decline_when_web_search_is_off(q):
    """Live check 2026-11-20: with web search off, "Is GitHub down?" got a
    patch_urgently verdict from unrelated GitHub Actions advisories."""
    assert "Web search" in app_1._needs_live_note(q, live=False)
    assert app_1._needs_live_note(q, live=True) is None


@pytest.mark.parametrize("q", ["Is it safe to update Firefox?", "Is zoom better or teams?",
                               "Latest Node.js version?"])
def test_feed_questions_are_not_declined_for_a_live_source(q):
    assert app_1._needs_live_note(q, live=False) is None
