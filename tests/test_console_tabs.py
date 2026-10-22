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
