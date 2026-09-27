"""
Three things the mixed-source pool broke, once the app stopped fetching only
from Reddit.

1. Every document's origin was rendered `r/<subreddit>`, because the retriever
   reuses that field to carry a publisher, a brand or a catalogue name. A
   Wccftech article was cited as "Community - r/Wccftech": a claim that a press
   report is a Reddit thread, made where the reader judges provenance.
2. The presenter sorted the community pool by upvotes. A press article carries
   score 0 by construction, so every non-Reddit source sorted last and was cut
   at `per_kind` -- the ranking decided which documents survived retrieval and
   was then thrown away before citation.
3. `find_thread` ranked the questions feed and took the best row with no test
   of whether it was about the question at all.

No network: the feed and the reranker input are stubbed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import answer_agent  # noqa: E402
import vendor  # noqa: E402
import yesno  # noqa: E402

NEWS = {"title": "Windows 11 Update Prevents You From Printing WPF Documents",
        "subreddit": "Wccftech", "source": "google_news", "score": 0,
        "url": "https://wccftech.com/x", "date": "2026-08-24",
        "sentiment": "Negative"}
POST = {"title": "[Bug] KB5101650 breaks printing", "subreddit": "windows",
        "source": "vendor_reddit", "score": 12, "url": "https://reddit.com/x",
        "date": "2026-09-02", "sentiment": "Negative"}
OWN = {"title": "windows PC unstable after update", "subreddit": "techsupport",
       "score": 4, "url": "https://reddit.com/y", "date": "2026-09-03",
       "sentiment": "Neutral"}
KEV = {"title": "[CISA KEV] Windows SmartScreen Bypass", "subreddit": "CISA",
       "source": "cisa_kev", "score": 0, "url": "https://cisa.gov/x",
       "date": "2026-09-01"}


@pytest.mark.parametrize("row,expected", [
    (NEWS, "Wccftech"),                 # a publisher is not a subreddit
    (KEV, "CISA"),                      # nor is an advisory catalogue
    (POST, "r/windows"),                # a Reddit row still reads as one
    (OWN, "r/techsupport"),             # no `source` means this app's own feed
    ({"subreddit": ""}, ""),
])
def test_a_document_is_named_by_where_it_came_from(row, expected):
    assert vendor.attribution(row) == expected


def test_citations_do_not_call_a_press_article_a_subreddit():
    ev = answer_agent.collect_evidence({"community": [NEWS, POST], "cve": [KEV]},
                                     per_kind=5)
    labels = [e.label for e in ev]
    assert any(l.startswith("Community - Wccftech") for l in labels), labels
    assert any(l.startswith("Community - r/windows") for l in labels), labels
    assert any(l.startswith("Security Discussion - CISA") for l in labels), labels
    assert not any("r/Wccftech" in l or "r/CISA" in l for l in labels), labels


def test_the_presenter_cites_in_ranked_order_not_upvote_order():
    # NEWS is first in the ranked pool and has 0 upvotes; POST has 12. Sorting
    # on upvotes put the article second, and with a pool deeper than per_kind
    # it dropped out of the citation entirely.
    ev = answer_agent.collect_evidence({"community": [NEWS, POST]}, per_kind=1)
    assert [e.title for e in ev] == [NEWS["title"]]


# ── find_thread ──────────────────────────────────────────────────────────

FEED = [
    {"title": "Gateway / pairing / auth dying after an update — what first?",
     "subreddit": "openclaw", "author_description": "every curl request bounced"},
    {"title": "fedora update", "subreddit": "fedora",
     "author_description": "did it delete your kernel and grub?"},
    # A third row, because BM25 takes its IDF from the pool and with N=2 every
    # term floors to 0 -- the real feed is 100 rows.
    {"title": "Best laptop for running Debian in 2026?", "subreddit": "linux",
     "author_description": "thinkpad or framework"},
]


@pytest.fixture
def feed(monkeypatch):
    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [dict(r) for r in FEED]}

    monkeypatch.setattr(yesno.requests if hasattr(yesno, "requests") else __import__("requests"),
                        "get", lambda *a, **k: _R())


def test_an_off_subject_thread_is_no_thread(feed):
    # Nothing in this feed is about printing. BM25 still has a best row.
    assert yesno.find_thread("What broke printing in the latest Windows update?",
                             must_mention=["printing", "broke"]) is None


def test_the_subject_word_may_live_in_the_body(feed):
    # "fedora update" is a bare title; the question is in author_description.
    t = yesno.find_thread("Did the latest Fedora 44 update delete your kernel?",
                          must_mention=["delete", "kernel", "grub"])
    assert t is not None and t["title"] == "fedora update"


def test_scope_can_empty_the_feed(feed):
    assert yesno.find_thread("anything", scope=lambda rows: []) is None


def test_with_no_subject_words_the_gate_does_not_fire(feed):
    # A question of nothing but generic words still gets the ranked winner,
    # rather than being silently denied a thread.
    assert yesno.find_thread("fedora update", must_mention=[]) is not None
