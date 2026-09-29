"""A strict replay has to stop on a corpus miss, not absorb it.

`strict:` was not the tripwire it was taken for, in this repo and in the paper.
CorpusMiss was a RuntimeError, every fetch in the retriever ends in a broad
`except ...: return []`, and three of them were bare `except:`. So a miss was
caught at the fetch, that source contributed nothing for that question, and the
run carried on and exited 0. One 500-question pass took 74 misses that way and
still called itself strict.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import corpus_snapshot
import multiagent_rag_v3 as marag


def test_corpus_miss_is_not_an_exception():
    """The one line that makes every `except Exception` pass it through."""
    assert issubclass(corpus_snapshot.CorpusMiss, BaseException)
    assert not issubclass(corpus_snapshot.CorpusMiss, Exception)


@pytest.mark.parametrize("fetch, args", [
    ("fetch_live_reddit", ("anything",)),
    ("fetch_live_releases", ("anything",)),
    ("fetch_google_news", ("anything",)),
    ("fetch_live_cve", ("anything",)),
    ("fetch_apple_rss", ("anything",)),
])
def test_a_miss_propagates_out_of_every_fetch(fetch, args, monkeypatch):
    def miss(*a, **k):
        raise corpus_snapshot.CorpusMiss("strict: no snapshot entry")
    monkeypatch.setattr(marag.requests, "get", miss)
    monkeypatch.setattr(marag.urllib.request, "urlopen", miss)

    with pytest.raises(corpus_snapshot.CorpusMiss):
        getattr(marag, fetch)(*args, limit=2)


def test_an_ordinary_endpoint_failure_is_still_absorbed(monkeypatch):
    """The broad handlers exist for a reason: one flaky feed must not take the
    run down. Only the miss is special."""
    def flaky(*a, **k):
        raise RuntimeError("HTTP 502")
    monkeypatch.setattr(marag.requests, "get", flaky)

    assert marag.fetch_live_reddit("anything", limit=2) == []
    assert marag.fetch_google_news("anything", limit=2) == []


def test_no_bare_except_remains_in_the_fetch_path():
    """A bare `except:` catches BaseException too, which is how the miss was
    being absorbed even after CorpusMiss stopped being an Exception."""
    import re
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "multiagent_rag_v3.py")).read()
    assert not re.search(r"(?m)^\s*except:\s*$", src)


# ---- the fire rate should be read, not reconstructed ------------------------

def test_the_round_count_is_carried_on_every_row():
    """The first measurement of the retry's fire rate had to infer it from
    per-role call counts, which works only while the roles stay
    distinguishable. One integer per row makes it a reading."""
    import types
    import eval_harness.generators as G

    gen = object.__new__(G.MultiAgentRAGGenerator)
    gen.marag = marag
    gen.rewriter = types.SimpleNamespace(
        run=lambda q, avoid=(): {"rewritten": q + " notes" * (len(avoid) + 1)})
    docs = [{"title": "t", "url": "u", "source": "releases", "subreddit": "",
             "sentiment": "Neutral", "detail": ""}]
    gen.retriever = types.SimpleNamespace(
        run=lambda *a, **k: docs, last_pool=list(docs),
        last_rerank_spec="bm25", last_rerank_degraded=False)
    # Negative once, then positive: one retry, so two rounds.
    seen = {"n": 0}

    def evaluate(d, q):
        seen["n"] += 1
        sig = "negative" if seen["n"] == 1 else "positive"
        return {"answer": "A", "quality": 0.1, "relevance": 0.0, "signal": sig}
    gen.evaluator = types.SimpleNamespace(run=evaluate)
    gen.top_k, gen.synth, gen.union, gen.retry = 2, None, True, True

    out = gen.generate("does printing work")
    assert out["rounds"] == 2
    assert out["retried"] is True
