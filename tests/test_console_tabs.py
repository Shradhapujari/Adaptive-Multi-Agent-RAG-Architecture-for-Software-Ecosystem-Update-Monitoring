"""The Decision console's Short Answer and Sources tabs, and the on-topic test
under them. Each case is a defect seen live on 2026-10-22:

  * "What is the latest version of Node.js?" showed 🔴 Patch urgently as its
    short answer; the version was only in the Long Answer.
  * "Is it safe to update Firefox right now?" decided on 8 NVD advisories the
    Sources tab never listed (held back from display by the opinion intent).
  * "What is the latest version of Zig?" was never ABSENT, because "what" is a
    content token to the harness scorer and every document contains it.
"""
from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_1
import graph
from eval_harness.generators import doc_id


def _rel(version, day, **kw):
    return {"title": f"Node.js v{version} — notes", "product": "Node.js", "version": version,
            "date": day, "url": f"https://nodejs.org/{version}", "is_cve": False, **kw}


def test_question_words_do_not_make_a_document_on_topic():
    chat = {"title": "what a week", "text": "what happened to my build"}
    zig = {"title": "Zig 0.15 released", "text": "zig"}
    assert graph.on_topic("What is the latest version of Zig?", [chat]) == []
    assert graph.on_topic("What is the latest version of Zig?", [zig]) == [zig]
    assert graph.classify("What is the latest version of Zig?", [chat])[0] is graph.Evidence.ABSENT


def test_latest_release_is_highest_shipped_version_not_newest_row():
    rows = [_rel("26.11.0", "20261001"),
            _rel("26.12.0", "20261014"),
            _rel("25.9.9", "20261020"),                         # backfilled older line
            _rel("27.0.0", "20270101"),                         # scheduled, not shipped
            _rel("26.99.0", "20261015", is_cve=True)]           # advisory row
    best = app_1._latest_release(rows, "What is the latest version of Node.js?", today=date(2026, 10, 22))
    assert best["version"] == "26.12.0"


def test_a_date_question_naming_a_version_gets_that_versions_row():
    rows = [_rel("26.11.0", "20261001"), _rel("26.12.0", "20261014")]
    best = app_1._latest_release(rows, "When was Node.js 26.11.0 released?", today=date(2026, 10, 22))
    assert best["version"] == "26.11.0"


def test_no_shipped_release_means_no_short_answer_value():
    assert app_1._latest_release([_rel("26.99.0", "20261015", is_cve=True)], "latest node?",
                                 today=date(2026, 10, 22)) is None


def test_sources_list_the_advisories_held_back_for_the_verdict():
    adv = {"title": "Firefox v157.0 — Mitigation bypass, CVE-2026-11111", "notes": "fixed in Firefox 157.0.1",
           "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-11111", "version": "157.0", "is_cve": True}
    post = {"title": "bookmarks gone", "redditId": "abc", "tier": 2, "url": "https://reddit.com/x"}
    results = {"releases": [], "cve": [], "community": [post], "decision_advisories": [adv],
               "decision": {"evidence_doc_ids": [doc_id(adv)]}}
    rows = app_1._source_rows(results)
    nvd = [r for r in rows if r["Tier"] == "CISA KEV / NVD"]
    assert len(nvd) == 1
    assert nvd[0]["id"] == doc_id(adv)                 # same id the console cites
    assert "CVE-2026-11111" in nvd[0]["Version/CVE"]
    assert nvd[0]["Verdict"] == "cited"
    assert [r["Tier"] for r in rows if r["Title"] == "bookmarks gone"] == ["Reddit / Forums"]


def test_sources_mark_what_the_answer_cites_apart_from_the_verdict():
    from answer_agent import collect_evidence, PresentedAnswer
    rel = _rel("26.12.1", "20261020")
    post = {"title": "npm broke", "url": "https://reddit.com/y"}
    results = {"releases": [rel], "cve": [], "community": [post], "decision": None}
    ev = collect_evidence(results)
    text = f"Node.js v26.12.1 shipped [{ev[0].label}]."
    rows = app_1._source_rows(results, PresentedAnswer(text, "llm", evidence=ev))
    assert {r["Title"]: r["Answer"] for r in rows} == {rel["title"]: "cited", "npm broke": ""}


def test_sources_tab_shows_only_cited_rows(monkeypatch):
    # The tab's count is the answer's: 15 retrieved rows beside an answer
    # citing 7 was the mismatch the advisor saw (2026-11-17).
    from answer_agent import collect_evidence, PresentedAnswer
    rel = _rel("26.12.1", "20261020")
    post = {"title": "npm broke", "url": "https://reddit.com/y"}
    results = {"releases": [rel], "cve": [], "community": [post], "decision": None}
    ev = collect_evidence(results)
    shown, notes = [], []
    monkeypatch.setattr(app_1.st, "dataframe", lambda rows, **kw: shown.extend(rows))
    monkeypatch.setattr(app_1.st, "caption", notes.append)
    app_1._tab_sources(results, PresentedAnswer(f"Shipped [{ev[0].label}].", "llm", evidence=ev))
    assert [r["Title"] for r in shown] == [rel["title"]]
    assert notes == ["1 cited · 1 more retrieved, not cited"]


def test_chrome_headline_is_the_stable_channel_not_the_highest_feed_tag(monkeypatch):
    from types import SimpleNamespace
    feed = [{"product": "Chrome", "version": "159.0.8147", "date": "20261106", "is_cve": False,
             "title": "Chrome v159.0.8147", "url": ""}]
    results = {"grounding": SimpleNamespace(vendor_names=["chrome"]), "releases": feed}

    class _Resp:
        def json(self):
            return {"releases": [{"version": "157.0.8103.79",
                                  "serving": {"startTime": "2026-11-19T20:21:11Z"}}]}
    app_1._stable_release.cache_clear()
    monkeypatch.setattr(app_1.requests, "get", lambda *a, **k: _Resp())
    assert app_1._headline_release(results, "Is it safe to update Chrome?")["version"] == "157.0.8103.79"
    # A question naming a version keeps the feed row.
    assert app_1._headline_release(results, "When was Chrome 159.0.8147 released?")["version"] == "159.0.8147"

    # API down: fall back to the feed rather than show nothing.
    app_1._stable_release.cache_clear()
    monkeypatch.setattr(app_1.requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert app_1._headline_release(results, "Latest Chrome version?")["version"] == "159.0.8147"
    app_1._stable_release.cache_clear()


def test_firefox_and_edge_headlines_use_the_vendors_stable_channel(monkeypatch):
    from types import SimpleNamespace
    firefox = {"releases": {
        "firefox-160.0": {"version": "160.0", "date": "2026-11-10", "category": "major"},
        "firefox-160.0.1": {"version": "160.0.1", "date": "2026-11-17", "category": "stability"},
        "firefox-161.0b5": {"version": "161.0b5", "date": "2026-11-18", "category": "dev"},
        "firefox-153.7.0esr": {"version": "153.7.0esr", "date": "2026-11-18", "category": "esr"}}}
    edge = [{"Product": "Beta", "Releases": [{"Platform": "Windows", "ProductVersion": "159.0.1",
                                               "PublishedTime": "2026-11-18T00:00:00"}]},
            {"Product": "Stable", "Releases": [{"Platform": "Windows", "ProductVersion": "158.0.4370.33",
                                                 "PublishedTime": "2026-11-19T21:17:00"}]}]

    class _Resp:
        def __init__(self, j): self.j = j
        def json(self): return self.j
    monkeypatch.setattr(app_1.requests, "get",
                        lambda url, **k: _Resp(firefox if "mozilla" in url else edge))
    app_1._stable_release.cache_clear()
    ff = {"grounding": SimpleNamespace(vendor_names=["firefox"]),
          "releases": [{"product": "Firefox", "version": "160.0.0", "date": "20261110", "is_cve": False}]}
    rel = app_1._headline_release(ff, "Is it safe to update Firefox?")
    assert (rel["version"], rel["date"]) == ("160.0.1", "20261117")
    # Edge has no feed rows; the stable API alone gives the headline.
    ms = {"grounding": SimpleNamespace(vendor_names=["microsoft", "edge"]), "releases": []}
    assert app_1._headline_release(ms, "Latest Microsoft Edge version?")["version"] == "158.0.4370.33"
    app_1._stable_release.cache_clear()
