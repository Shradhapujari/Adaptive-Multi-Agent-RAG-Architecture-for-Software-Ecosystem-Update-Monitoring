"""
LLMCascadeReranker: grade the base ranker's top-N, re-sort the head, leave
the tail. Offline: the model call is stubbed, the base is BM25.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rerank  # noqa: E402

DOCS = [
    {"title": "firefox 148 release notes", "detail": "firefox 148 fixes crash on startup"},
    {"title": "firefox crash after update", "detail": "firefox keeps crashing since 148"},
    {"title": "chrome 156 release", "detail": "chrome stable channel update"},
    {"title": "firefox", "detail": "firefox"},
]
Q = "firefox crash after update to 148?"


class _Stub(rerank.LLMCascadeReranker):
    def __init__(self, grades, **kw):
        super().__init__(**kw)
        self._fake = grades

    def _generate(self, prompt):
        for title, g in self._fake.items():
            if f"Title: {title}\n" in prompt:
                return '{"relevance": %d}' % g
        return "not json"


def test_spec_parses_and_names_the_arm():
    assert rerank._LLM_SPEC_RE.match("llm20@embed:qwen2.5:7b-instruct").groups() == \
        ("20", "embed", "qwen2.5:7b-instruct")
    r = _Stub({}, n=2, base=rerank.BM25Reranker(), model="m")
    assert r.spec == "llm2@bm25:m"


def test_grade_reorders_only_the_head():
    base = rerank.BM25Reranker()
    base_order = [d["title"] for d in base.rank(Q, DOCS, top_k=4)]
    # Grade the base's #2 above its #1; the tail (positions 3-4) must not move.
    r = _Stub({base_order[0]: 1, base_order[1]: 2}, n=2, base=base, model="m")
    out = [d["title"] for d in r.rank(Q, DOCS, top_k=4)]
    assert out[:2] == [base_order[1], base_order[0]]
    assert out[2:] == base_order[2:]
    assert r.calls == 2


def test_ungradable_output_keeps_base_rank():
    base = rerank.BM25Reranker()
    r = _Stub({}, n=3, base=base, model="m")   # every call returns non-JSON
    assert [d["title"] for d in r.rank(Q, DOCS, top_k=4)] == \
        [d["title"] for d in base.rank(Q, DOCS, top_k=4)]
