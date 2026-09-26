"""
The demo ranks its pools with the same reranker the terminal does.

Nothing in `run_pipeline` ranked: `union_fetch` orders by window membership,
the vendor and intent filters only drop, and the pools were then truncated to
`limit` in whatever order the feed returned them -- newest-first from
releasetrain, vote order from Reddit. The terminal ranks the same pool through
`rerank.py`, so the demo and the measured arm disagreed about which five
documents a question retrieves, which is the one thing the evaluation is
about.

No network: `union_fetch`, the rewriter and the vendor-subreddit fetch are
stubbed, and the reranker is pinned to BM25, which needs no model.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

import app_1  # noqa: E402
import rerank  # noqa: E402
from app_1 import Rewrite  # noqa: E402

QUERY = "What broke printing in the latest Windows update?"

# Fetch order, deliberately worst-first: the printing thread is what the
# question asks for and the feed returns it last, because it is the oldest.
# Eight documents rather than two because BM25 takes its IDF from the pool and
# a two-document pool floors every term to zero -- real pools are `limit * 10`.
_NOISE = ["Wallpaper engine on Windows 11", "Weekly discussion thread",
          "Windows 11 taskbar is still bad", "Best Windows terminal font?",
          "Windows update stuck at la 91%", "Windows 11 vs 10 for gaming",
          "Dual boot Windows and Fedora"]
POOL = [
    {"product": "Windows", "title": t, "text": "windows update discussion",
     "date": f"202609{20 + i:02d}", "url": f"u{i}"}
    for i, t in enumerate(_NOISE)
] + [
    {"product": "Windows", "title": "KB5101650 breaks printing",
     "text": "printing broken after the update", "date": "20260901",
     "url": "u9"},
]


@pytest.fixture
def stubbed(monkeypatch):
    # `MARAG_RERANK` is read into `DEFAULT_SPEC` at import, so setting the
    # environment variable here would come too late; `get_reranker()` reads
    # the module attribute on every call.
    monkeypatch.setattr(rerank, "DEFAULT_SPEC", "bm25")
    monkeypatch.setattr(app_1, "union_fetch",
                        lambda fn, phrasings, limit, tr=None: [dict(d) for d in POOL])
    monkeypatch.setattr(app_1, "rewrite_query",
                        lambda q: Rewrite("windows printing bug", "rule-based"))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda query, rewritten, already: (
                            {"community": [], "releases": [], "cve": []}, []))


def test_the_pool_is_ranked_not_just_truncated(stubbed):
    results = app_1.run_pipeline(QUERY, show_steps=False, limit=3)
    titles = [d["title"] for d in results["community"]]
    assert titles[0] == "KB5101650 breaks printing", titles


def test_a_short_limit_keeps_the_relevant_document(stubbed):
    # The regression in one line: cutting fetch order to 1 dropped the only
    # document that answered the question.
    results = app_1.run_pipeline(QUERY, show_steps=False, limit=1)
    assert [d["title"] for d in results["community"]] == \
        ["KB5101650 breaks printing"]


def test_a_release_row_is_not_an_empty_document_to_the_ranker(monkeypatch):
    # Release rows carried their text in `notes`, which `rerank.doc_text()`
    # does not read, so every release scored 0 and the pool stayed in fetch
    # order however it was ranked.
    monkeypatch.setattr(app_1, "_get_json", lambda *a, **k: {"versions": [
        {"versionProductName": "Windows", "versionNumber": "11.26100",
         "versionReleaseDate": "20260901", "isCve": False,
         "versionReleaseNotes": "fixes a print spooler regression"},
    ]})
    row = app_1.fetch_release_notes("windows", limit=5)[0]
    # Scored, not just present: BM25 takes its IDF from the pool, so the
    # comparison needs a pool to discriminate within.
    assert "print spooler" in rerank.doc_text(row)
    # Three, not two: with N=2 the IDF of a term in one document floors to 0.
    pool = [dict(row, title=f"Windows v11.2609{i} — wallpaper picker", url=f"u{i}")
            for i in (7, 8)] + [row]
    assert rerank.BM25Reranker().rank("print spooler", pool, top_k=3)[0] is row


def test_the_ranker_used_is_reported(stubbed):
    results = app_1.run_pipeline(QUERY, show_steps=False, limit=3)
    assert results["rerank"]["spec"] == "bm25"
    assert results["rerank"]["degraded"] is False
