"""
Tests for the Manager's retrieve-then-evaluate loop.

Two behaviours, both regressions of the same line. The loop used to be capped
by `"retry" not in query`, which read the *user's wording* as a recursion
guard: a question about retry logic could never widen its fetch, and the cap
was one round whatever the deployment wanted. And the one retry it did run
reissued a fixed filler string, so a thin pool was re-fetched with vocabulary
the Evaluator had already scored negative.

Offline: every agent is a stub, so nothing here calls Ollama or an endpoint.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import multiagent_rag_v3 as marag  # noqa: E402


class FakeRewriter:
    def __init__(self):
        self.calls = []

    def run(self, query, avoid=()):
        self.calls.append(tuple(avoid))
        return {"original": query, "rewritten": f"{query} v{len(self.calls)}"}


class FakeRetriever:
    def __init__(self):
        self.queries = []

    def run(self, q, top_k=4, original_query=None):
        self.queries.append((q, original_query))
        return [{"title": q}]


class FakeEvaluator:
    """Negative for `negative_rounds` rounds, then positive."""

    def __init__(self, negative_rounds):
        self.negative_rounds = negative_rounds
        self.calls = 0

    def run(self, docs, query):
        self.calls += 1
        sig = "negative" if self.calls <= self.negative_rounds else "positive"
        return {"quality": 0.0, "signal": sig, "answer": f"answer-{self.calls}"}


def manager(negative_rounds, cap=None):
    m = marag.ManagerAgent()
    m.rewriter, m.retriever = FakeRewriter(), FakeRetriever()
    m.evaluator = FakeEvaluator(negative_rounds)
    if cap is not None:
        m.MAX_ROUNDS = cap
    return m


def test_positive_first_round_does_not_retry():
    m = manager(negative_rounds=0)
    m.run("chrome update")
    assert m.evaluator.calls == 1
    assert len(m.retriever.queries) == 1


def test_negative_signal_runs_a_second_round():
    m = manager(negative_rounds=1)
    m.run("chrome update")
    assert m.evaluator.calls == 2


def test_the_word_retry_in_the_question_no_longer_blocks_the_loop():
    """The regression. `"retry" not in query` made this question uncapped-proof
    in the wrong direction: it got one round and no widening, because of a
    substring of the user's own sentence."""
    m = manager(negative_rounds=1)
    m.run("does urllib3 retry on 503?")
    assert m.evaluator.calls == 2


def test_cap_bounds_a_persistently_negative_loop():
    m = manager(negative_rounds=99, cap=4)
    m.run("chrome update")
    assert m.evaluator.calls == 4
    assert len(m.retriever.queries) == 4


def test_cap_of_one_disables_the_loop():
    m = manager(negative_rounds=99, cap=1)
    m.run("chrome update")
    assert m.evaluator.calls == 1


def test_cap_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("MARAG_MAX_ROUNDS", "5")
    import importlib
    importlib.reload(marag)
    try:
        assert marag.ManagerAgent.MAX_ROUNDS == 5
        monkeypatch.setenv("MARAG_MAX_ROUNDS", "0")
        importlib.reload(marag)
        assert marag.ManagerAgent.MAX_ROUNDS == 1      # floored, never zero
    finally:
        monkeypatch.delenv("MARAG_MAX_ROUNDS", raising=False)
        importlib.reload(marag)


def test_each_round_asks_for_terms_the_last_one_did_not_use():
    m = manager(negative_rounds=99, cap=3)
    m.run("chrome update")
    # Round 1 has nothing to avoid; each later round is handed every phrasing
    # already searched, and the retriever is issued the new one.
    assert m.rewriter.calls == [(), ("chrome update v1",),
                                ("chrome update v1", "chrome update v2")]
    assert [q for q, _ in m.retriever.queries] == [
        "chrome update v1", "chrome update v2", "chrome update v3"]


def test_every_round_ranks_against_the_users_own_words():
    m = manager(negative_rounds=99, cap=3)
    m.run("chrome update")
    assert {orig for _, orig in m.retriever.queries} == {"chrome update"}


@pytest.mark.parametrize("avoid,expect_different", [((), False), (("x",), True)])
def test_rule_based_fallback_widens_differently_per_round(monkeypatch, avoid,
                                                          expect_different):
    """With no model reachable, the retry must still change the phrasing --
    otherwise the fallback path re-fetches the pool that just scored negative.
    """
    monkeypatch.setattr(marag, "call_llama", lambda p: "[Ollama error: offline]")
    rw = marag.QueryRewriterAgent()
    first = rw.run("chrome update")["rewritten"]
    later = rw.run("chrome update", avoid=avoid)["rewritten"]
    assert (first != later) is expect_different


def test_a_rewriter_that_repeats_itself_is_widened_by_rule(monkeypatch):
    """The model can ignore the do-not-reuse instruction. A round that reissues
    a tried phrasing is a round of latency for the same pool."""
    monkeypatch.setattr(marag, "call_llama", lambda p: "chrome update")
    rw = marag.QueryRewriterAgent()
    out = rw.run("chrome update", avoid=("chrome update",))["rewritten"]
    assert out != "chrome update"


def test_the_avoided_phrasings_reach_the_prompt(monkeypatch):
    seen = {}
    monkeypatch.setattr(marag, "call_llama",
                        lambda p: seen.setdefault("prompt", p) and "rewritten q")
    marag.QueryRewriterAgent().run("chrome update", avoid=("chrome update v1",))
    assert "chrome update v1" in seen["prompt"]
    assert "Do not reuse" in seen["prompt"]
