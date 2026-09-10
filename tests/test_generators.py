"""
Tests for eval_harness/generators.py — the systems under test.

The point of these tests is the *fairness* property the answer metrics depend
on: the multi-agent arm and the single-agent baseline must synthesise from the
identical prompt, so a difference in judged answer quality is attributable to
the retrieval pipeline rather than to prompt wording or model choice.

They are offline. The generators are built with `object.__new__` and stubbed
collaborators instead of real agents, so no Ollama call, no releasetrain.io
request, and no 4.9 GB model pull is involved.
"""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval_harness import generators as G  # noqa: E402
from eval_harness.providers import LLMError  # noqa: E402


DOCS = [
    {"title": "Firefox 149.0.1 released", "detail": "Security fixes for tabs.",
     "source": "releases", "url": "u1"},
    {"title": "Firefox crash on startup", "detail": "Reports after 149 update.",
     "source": "reddit_live", "url": "u2"},
    {"title": "Unrelated kernel advisory", "detail": "erofs fix.",
     "source": "cve", "url": "u3"},
]
QUERY = "What is the latest Firefox release?"


class CapturingClient:
    """LLMClient stand-in that records the prompt it was asked to complete."""

    spec = "ollama:stub"

    def __init__(self, reply="stub answer", raises=False, avail=True):
        self.prompts = []
        self.reply = reply
        self.raises = raises
        self.avail = avail

    def available(self):
        return self.avail

    def generate(self, prompt, system=None, temperature=0.0, max_tokens=1024):
        self.prompts.append(prompt)
        if self.raises:
            raise LLMError("stub backend down")
        return self.reply


def _fake_marag_module():
    """`_silenced` only needs an object whose pause/bar it can swap."""
    return types.SimpleNamespace(pause=lambda *a, **k: None,
                                 bar=lambda *a, **k: None)


def _single_agent(client, top_k=2):
    gen = object.__new__(G.SingleAgentGenerator)
    gen.marag = _fake_marag_module()
    gen.retriever = types.SimpleNamespace(run=lambda q, top_k=4, original_query=None, union=True: DOCS)
    gen.top_k = top_k
    gen.client = client
    return gen


def _marag(synth, top_k=2, template="TEMPLATE ANSWER", quality=0.7):
    gen = object.__new__(G.MultiAgentRAGGenerator)
    gen.marag = _fake_marag_module()
    gen.rewriter = types.SimpleNamespace(
        run=lambda q: {"rewritten": q + " latest version release notes"})
    gen.retriever = types.SimpleNamespace(run=lambda q, top_k=4, original_query=None, union=True: DOCS)
    gen.evaluator = types.SimpleNamespace(
        run=lambda docs, q: {"answer": template, "quality": quality})
    gen.top_k = top_k
    gen.synth = synth
    gen.name = "marag" if synth is None else "marag_llm"
    return gen


# ── the shared prompt ────────────────────────────────────────────────────

def test_prompt_contains_question_and_only_top_k_sources():
    prompt = G.build_synthesis_prompt(QUERY, DOCS, top_k=2)
    assert QUERY in prompt
    assert G.SYNTHESIS_INSTRUCTION in prompt
    assert "Firefox 149.0.1 released" in prompt
    assert "Firefox crash on startup" in prompt
    # top_k=2 must not leak the third doc into the context.
    assert "Unrelated kernel advisory" not in prompt


def test_prompt_reports_empty_retrieval_rather_than_an_empty_context():
    assert "No documents retrieved." in G.build_synthesis_prompt(QUERY, [], top_k=4)


def test_prompt_accepts_both_raw_and_normalized_docs():
    """Raw pipeline docs carry `detail`; harness-normalized docs carry `text`."""
    raw = G.build_synthesis_prompt(QUERY, [DOCS[0]], top_k=1)
    norm = G.build_synthesis_prompt(QUERY, [G.normalize_doc(DOCS[0])], top_k=1)
    assert "Security fixes for tabs." in raw
    assert "Security fixes for tabs." in norm


# ── the fairness property ────────────────────────────────────────────────

def test_both_arms_synthesise_from_the_identical_prompt():
    """
    The regression test for the answer-metric confound: if these prompts ever
    diverge, a marag_llm vs single_agent answer-quality difference stops being
    evidence about retrieval.
    """
    base_client, marag_client = CapturingClient(), CapturingClient()
    _single_agent(base_client).generate(QUERY)
    _marag(marag_client).generate(QUERY)
    assert base_client.prompts == marag_client.prompts != []


def test_marag_llm_answer_comes_from_the_synthesiser_and_keeps_the_template():
    client = CapturingClient(reply="Firefox 149.0.1 is the latest release.")
    out = _marag(client).generate(QUERY)
    assert out["answer"] == "Firefox 149.0.1 is the latest release."
    # The published template answer is retained for audit, not discarded.
    assert out["template_answer"] == "TEMPLATE ANSWER"
    assert out["synth_model"] == "ollama:stub"


def test_template_arm_is_the_published_system_unchanged():
    out = _marag(None).generate(QUERY)
    assert out["answer"] == "TEMPLATE ANSWER"
    assert "template_answer" not in out and "synth_model" not in out
    assert out["self_quality"] == 0.7
    assert out["rewritten_query"].startswith(QUERY)


def test_retrieval_is_identical_across_the_two_arms():
    """Switching the answer path must not move the IR metrics."""
    a = _marag(None).generate(QUERY)
    b = _marag(CapturingClient()).generate(QUERY)
    assert [d["doc_id"] for d in a["docs"]] == [d["doc_id"] for d in b["docs"]]


def test_synthesiser_failure_is_reported_not_silently_templated():
    out = _marag(CapturingClient(raises=True)).generate(QUERY)
    assert out["answer"].startswith("[generation error:")
    assert out["template_answer"] == "TEMPLATE ANSWER"


def test_availability_follows_the_synthesiser():
    assert _marag(None).available() is True
    assert _marag(CapturingClient(avail=False)).available() is False


# ── spec grammar ─────────────────────────────────────────────────────────

def test_spec_grammar_attaches_a_synthesiser_only_when_asked(monkeypatch):
    built = []

    class Recorder:
        def __init__(self, top_k=4, synth=None):
            built.append((top_k, synth))
            self.name = "marag" if synth is None else "marag_llm"

    monkeypatch.setattr(G, "MultiAgentRAGGenerator", Recorder)
    gens = G.build_generators(["marag", "marag:ollama:mistral"], top_k=3)

    assert [g.name for g in gens] == ["marag", "marag_llm"]
    assert built[0] == (3, None)
    assert built[1][0] == 3 and built[1][1].spec == "ollama:mistral"


def test_unknown_spec_is_rejected():
    with pytest.raises(ValueError):
        G.build_generators(["marag_llm"])


# ─────────────────────────────────────────────────────────────────────────
# The ablation ladder and the rendering x retrieval factorial
# ─────────────────────────────────────────────────────────────────────────
# A reviewer's objection to the capability table is that the arms are not doing
# the same task. The answer is that each adjacent rung differs by exactly one
# capability, and that rendering is a factor crossing retrieval rather than a
# property welded to the multi-agent arm. These tests hold that structure in
# place: if a rung ever starts differing by two things at once, they fail.


def _recording_retriever(docs=DOCS):
    """Retriever stub that records the kwargs each call was made with."""
    calls = []

    def run(q, top_k=4, original_query=None, union=True):
        calls.append({"query": q, "original_query": original_query,
                      "union": union, "top_k": top_k})
        return docs

    return types.SimpleNamespace(run=run, calls=calls, last_pool=list(docs),
                                 last_rerank_spec="bm25",
                                 last_rerank_degraded=False)


def _ladder_marag(synth=None, union=True, retry=False, signal="✅ positive",
                  retriever=None):
    gen = object.__new__(G.MultiAgentRAGGenerator)
    gen.marag = _fake_marag_module()
    gen.rewriter = types.SimpleNamespace(
        run=lambda q: {"rewritten": q + " release notes"})
    gen.retriever = retriever or _recording_retriever()
    gen.evaluator = types.SimpleNamespace(
        run=lambda docs, q: {"answer": "TEMPLATE", "quality": 0.1,
                             "signal": signal})
    gen.top_k = 2
    gen.synth = synth
    gen.union = union
    gen.retry = retry
    return gen


def _single_agent_template(top_k=2):
    gen = object.__new__(G.SingleAgentGenerator)
    gen.marag = types.SimpleNamespace(
        pause=lambda *a, **k: None, bar=lambda *a, **k: None,
        EvaluatorAgent=lambda: types.SimpleNamespace(
            run=lambda docs, q: {"answer": "TEMPLATE", "quality": 0.42,
                                 "signal": "✅ positive"}))
    gen.retriever = _recording_retriever()
    gen.top_k = top_k
    gen.render = "template"
    gen.client = None
    return gen


def test_rewrite_only_fetches_one_phrasing_and_marag_fetches_both():
    """A2 -> A3 is the union-fetch effect and nothing else."""
    a2 = _ladder_marag(synth=CapturingClient(), union=False)
    a3 = _ladder_marag(synth=CapturingClient(), union=True)
    a2.generate(QUERY)
    a3.generate(QUERY)

    assert a2.retriever.calls[0]["union"] is False
    assert a3.retriever.calls[0]["union"] is True
    # Everything else about the call is identical, which is what makes the
    # difference attributable to the union fetch.
    for key in ("query", "original_query", "top_k"):
        assert a2.retriever.calls[0][key] == a3.retriever.calls[0][key]


def test_the_retry_arm_refetches_only_on_a_negative_signal():
    """A3 -> A4 is ManagerAgent's adaptive retry and nothing else."""
    negative = _ladder_marag(synth=CapturingClient(), retry=True,
                             signal="⚠️  negative — manager will retry")
    positive = _ladder_marag(synth=CapturingClient(), retry=True,
                             signal="✅ positive")
    off = _ladder_marag(synth=CapturingClient(), retry=False,
                        signal="⚠️  negative — manager will retry")

    assert negative.generate(QUERY)["retried"] is True
    assert len(negative.retriever.calls) == 2
    # The widened fetch still ranks against the user's own words.
    assert negative.retriever.calls[1]["original_query"] == QUERY
    assert negative.retriever.calls[1]["query"].startswith(QUERY)

    assert positive.generate(QUERY)["retried"] is False
    assert len(positive.retriever.calls) == 1
    # Same negative signal, retry disabled: the rung below must not retry.
    assert off.generate(QUERY)["retried"] is False
    assert len(off.retriever.calls) == 1


def test_the_retry_pool_is_the_union_of_both_fetches():
    """Pool recall is the fetch ceiling; the retry must not hide the first pool."""
    first = [DOCS[0]]
    second = [DOCS[1], DOCS[2]]
    state = {"n": 0}

    def run(q, top_k=4, original_query=None, union=True):
        state["n"] += 1
        # RetrieverAgent overwrites last_pool on every call, as the real one does.
        retriever.last_pool = first if state["n"] == 1 else second
        return DOCS[:2]

    retriever = types.SimpleNamespace(run=run, last_pool=first,
                                      last_rerank_spec="bm25",
                                      last_rerank_degraded=False)
    gen = _ladder_marag(synth=CapturingClient(), retry=True,
                        signal="⚠️  negative — manager will retry",
                        retriever=retriever)
    out = gen.generate(QUERY)

    assert out["retried"] is True
    titles = [d["title"] for d in out["pool"]]
    assert titles == [d["title"] for d in first + second]


def test_the_rewrite_only_rung_refuses_to_be_a_template_arm():
    with pytest.raises(ValueError):
        G.MultiAgentRAGGenerator(union=False)


def test_the_template_cell_of_the_factorial_calls_no_model():
    """single_agent_template completes the 2x2 without an LLM call."""
    gen = _single_agent_template()
    out = gen.generate(QUERY)

    assert out["answer"] == "TEMPLATE"
    assert out["self_quality"] == 0.42
    assert gen.client is None          # deterministic, and free to carry
    # Baseline retrieval, unchanged: the raw question, single phrasing.
    assert gen.retriever.calls[0]["original_query"] == QUERY
    assert gen.retriever.calls[0]["query"] == QUERY


def test_rendering_crosses_retrieval_rather_than_being_welded_to_an_arm():
    """The prose and template cells of one row retrieve identically."""
    prose = _single_agent(CapturingClient())
    template = _single_agent_template()

    assert ([d["doc_id"] for d in prose.generate(QUERY)["docs"]]
            == [d["doc_id"] for d in template.generate(QUERY)["docs"]])


def test_the_ladder_specs_build_distinctly_named_arms():
    specs = ["single_agent", "single_agent_template",
             "rewrite_only:ollama:mistral", "marag:ollama:mistral",
             "marag_retry:ollama:mistral", "marag_retry", "marag"]
    assert [g.name for g in G.build_generators(specs)] == [
        "single_agent", "single_agent_template", "rewrite_only",
        "marag_llm", "marag_llm_retry", "marag_retry", "marag"]


def test_an_unknown_render_mode_is_rejected():
    with pytest.raises(ValueError):
        G.SingleAgentGenerator(CapturingClient(), render="bullets")


# ---------------------------------------------------------------- rules arm
# AGENT_RULES.md is prepended by the app on every prompt and by the harness on
# none, so its effect was never measured. MARAG_RULES makes it a factor. Off is
# the default because the published answer numbers were produced without it.

def test_rules_are_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv(G.RULES_ENV, raising=False)
    assert G.rules_prefix() == ""
    assert G.build_synthesis_prompt(QUERY, DOCS, 2).startswith(G.SYNTHESIS_INSTRUCTION)


def test_rules_arm_prepends_the_block_and_nothing_else(monkeypatch):
    monkeypatch.delenv(G.RULES_ENV, raising=False)
    off = G.build_synthesis_prompt(QUERY, DOCS, 2)
    monkeypatch.setenv(G.RULES_ENV, "on")
    on = G.build_synthesis_prompt(QUERY, DOCS, 2)
    # The whole difference between the two arms, and it is a prefix.
    assert on.endswith(off) and on != off
    assert on.startswith("# Agent Rules")


def test_the_run_records_which_arm_it_actually_was(monkeypatch):
    monkeypatch.delenv(G.RULES_ENV, raising=False)
    arm = G.rules_arm()
    assert arm["rules_active"] is False and arm["rules_sha"] == ""
    monkeypatch.setenv(G.RULES_ENV, "on")
    arm = G.rules_arm()
    # The digest is what makes two arms comparable: an edit between them shows.
    assert arm["rules_active"] is True and len(arm["rules_sha"]) == 12
    assert arm["rules_chars"] > 0


def test_an_arm_that_cannot_be_on_fails_instead_of_running_off(monkeypatch):
    # Silently handing back the bare prompt would report a rules run that never
    # had any rules in it -- the arm would be mislabelled, not merely empty.
    monkeypatch.setenv(G.RULES_ENV, "on")
    monkeypatch.setattr("agent_rules.rules_block", lambda: "")
    with pytest.raises(RuntimeError, match="AGENT_RULES.md"):
        G.rules_prefix()
