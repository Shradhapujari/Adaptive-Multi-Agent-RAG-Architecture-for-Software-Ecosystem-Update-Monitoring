"""
The cascade grades the top-N of the base its spec names.

Only `embed` was honoured: `llm12@bm25:<model>` and `llm12@none:<model>` both
graded the top-N of the bm25+embed RRF fusion and were then reported under the
base the operator had asked for. An ablation sweep may fail, but it may not
quietly measure a different arm than the one it prints -- which is the reason
`resolve_rank_tiers` and `resolve_rank_query` raise on a typo rather than
falling back to a default.

Offline: the embedding ranker and the grading model are both stubbed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rerank  # noqa: E402
from eval_harness import rerank_bench  # noqa: E402

# "alpha" wins on words, "beta" wins on the (stubbed) embedding. Two bases that
# disagree is the whole point: it is what makes the base observable in the order.
POOL = [
    {"doc_id": "d0", "title": "kernel panic after update", "text": "kernel panic update"},
    {"doc_id": "d1", "title": "unrelated", "text": "cooking recipes"},
    {"doc_id": "d2", "title": "also unrelated", "text": "holiday photos"},
]
QUERY = "kernel panic update"


class _StubEmbed(rerank.Reranker):
    """Ranks the pool in reverse: the opposite of what bm25 does on POOL."""

    spec = "embed:stub"

    def scores(self, query, docs):
        return [float(i) for i in range(len(docs))]


@pytest.fixture
def scorer(monkeypatch):
    monkeypatch.setattr(rerank, "make_reranker", lambda spec: _StubEmbed())
    monkeypatch.setattr(rerank_bench, "make_client", lambda spec: object())

    def build(spec):
        s = rerank_bench.Scorer(spec)
        # Grade everything 0, so the base order alone decides the result.
        monkeypatch.setattr(s, "_grade", lambda q, d: 0)
        return s

    return build


def test_the_named_base_is_the_one_that_ranks(scorer):
    bm25_order = scorer("bm25").order(QUERY, POOL)
    embed_order = scorer("embed").order(QUERY, POOL)
    assert bm25_order != embed_order, "the two bases must disagree for this to test anything"

    assert scorer("llm3@bm25:m").order(QUERY, POOL) == bm25_order
    assert scorer("llm3@embed:m").order(QUERY, POOL) == embed_order
    assert scorer("llm3@none:m").order(QUERY, POOL) == list(range(len(POOL)))
    assert scorer("llm3@rrf:m").order(QUERY, POOL) == scorer("rrf").order(QUERY, POOL)


def test_an_unknown_base_is_refused(scorer):
    with pytest.raises(ValueError, match="unknown cascade base"):
        scorer("llm12@bm52:m")


def test_the_grade_outranks_the_base_within_the_head(scorer, monkeypatch):
    """The base decides the head; the grade reorders it. Both, not either."""
    s = rerank_bench.Scorer("llm2@bm25:m")
    monkeypatch.setattr(s, "_grade", lambda q, d: 2 if d["doc_id"] == "d1" else 0)
    head = s.order(QUERY, POOL)[:2]
    bm25_head = scorer("bm25").order(QUERY, POOL)[:2]
    assert set(head) == set(bm25_head), "the head is still the base's top-2"
    assert POOL[head[0]]["doc_id"] == "d1", "and the graded document leads it"
