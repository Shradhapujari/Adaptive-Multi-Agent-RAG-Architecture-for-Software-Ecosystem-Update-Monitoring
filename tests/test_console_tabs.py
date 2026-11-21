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


def test_a_named_version_missing_from_the_feed_is_no_headline():
    # Live, 2026-11-21: "Did rust-lang rust v1.92.0 ship?" was answered
    # "rust v1.100.0" because 1.92.0 was not among the rows fetched.
    rows = [_rel("1.100.0", "20261120"), _rel("1.99.1", "20261111")]
    assert app_1._latest_release(rows, "Did rust-lang rust v1.92.0 ship?",
                                 today=date(2026, 11, 21)) is None
    # A date-shaped version is a named version too: no Arch row, no headline.
    assert app_1._latest_release(rows, "Should I upgrade to Arch v2026.01.01?",
                                 today=date(2026, 11, 21)) is None


def test_a_short_named_version_picks_the_newest_of_its_line():
    rows = [_rel("26.11.0", "20261001"), _rel("26.11.2", "20261015"),
            _rel("26.12.0", "20261020"), _rel("v26.10.1", "20260920")]
    best = app_1._latest_release(rows, "Is 26.11 still supported?", today=date(2026, 10, 22))
    assert best["version"] == "26.11.2"
    # A leading "v" on the row's version still matches.
    best = app_1._latest_release(rows, "When did 26.10.1 ship?", today=date(2026, 10, 22))
    assert best["version"] == "v26.10.1"
    # "26.1" is not a prefix of "26.11.x" or "26.12.0".
    assert app_1._latest_release(rows, "When did 26.1 ship?", today=date(2026, 10, 22)) is None


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


def test_chrome_release_rows_are_labelled_with_their_channel(monkeypatch):
    lists = {"stable": ["158.0.8127.36", "157.0.8103.79"], "extended": [], "beta": ["158.0.8127.18"],
             "dev": [], "canary": ["160.0.8170.0"]}

    class _Resp:
        def __init__(self, url): self.ch = url.split("/channels/")[1].split("/")[0]
        def json(self): return {"versions": [{"version": v} for v in lists[self.ch]]}
    monkeypatch.setattr(app_1.requests, "get", lambda url, **k: _Resp(url))
    app_1._chrome_channels.cache_clear()
    rows = [{"Release": f"Chrome v{v}", "Date": "20261118"} for v in ("160.0.8170", "158.0.8127", "159.0.8147")]
    got = app_1._label_channels(rows)
    assert [r["Channel"] for r in got] == ["canary", "stable", "not shipped"]
    assert list(got[0]) == ["Release", "Channel", "Date"]
    # No Chrome row: no lookup, rows unchanged.
    ff = [{"Release": "Firefox v160.0.0", "Date": "20261110"}]
    assert app_1._label_channels(ff) == ff
    # API down: no Channel column rather than a wrong one.
    app_1._chrome_channels.cache_clear()
    monkeypatch.setattr(app_1.requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert "Channel" not in app_1._label_channels(rows)[0]
    app_1._chrome_channels.cache_clear()


def test_unshipped_chrome_builds_are_dropped_before_the_answer(monkeypatch):
    monkeypatch.setattr(app_1, "_chrome_channels", lambda _h: {
        "157.0.8103": "stable", "159.0.8154": "beta", "160.0.8157": "dev", "160.0.8170": "canary"})
    rows = [{"product": "Chrome", "version": v, "is_cve": False}
            for v in ("157.0.8103", "159.0.8154", "160.0.8157", "160.0.8170", "159.0.8147")]
    adv = {"product": "chrome", "version": "160.0.8170", "is_cve": True}    # advisory: kept
    ff = {"product": "Firefox", "version": "160.0.0", "is_cve": False}       # not Chrome: kept
    kept = app_1._drop_prerelease(rows + [adv, ff])
    assert [r["version"] for r in kept] == ["157.0.8103", "159.0.8154", "160.0.8170", "160.0.0"]
    assert adv in kept and ff in kept
    # API down: nothing dropped.
    monkeypatch.setattr(app_1, "_chrome_channels", lambda _h: {})
    assert app_1._drop_prerelease(rows) == rows


def test_kev_rows_survive_the_cut():
    import app_1
    rows = [{"id": f"nvd{i}"} for i in range(5)] + [{"id": "kev", "kev_vendor": "Google"}]
    top = app_1._kev_first(rows)[:5]
    assert top[0]["id"] == "kev" and [r["id"] for r in top[1:]] == ["nvd0", "nvd1", "nvd2", "nvd3"]


def test_component_notice_only_where_the_vendor_names_no_component():
    import app_1
    from vendor import detect_vendors
    g = lambda q: type("G", (), {"vendors": detect_vendors(q)})()
    assert app_1._unfocused_components(g("WebRTC in Edge")) == ["webrtc in edge"]
    assert app_1._unfocused_components(g("WebRTC in Chrome")) == []


def test_a_safety_question_keeps_the_full_advisory_lookback():
    """'right now' is a one-day window; a safety verdict still needs last week's CVEs."""
    from temporal import resolve_temporal
    q = "Is it safe to update Firefox right now?"
    assert app_1._nvd_days(q, resolve_temporal(q)) == 90
    q = "Any critical Linux updates today?"
    assert app_1._nvd_days(q, resolve_temporal(q)) == 1
