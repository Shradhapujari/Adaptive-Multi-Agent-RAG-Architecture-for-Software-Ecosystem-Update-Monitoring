"""
Generator adapters — the systems under test.
============================================
Every generator implements:

    gen.generate(query) -> {
        "answer":   str,                 # final natural-language answer
        "docs":     [doc, ...],          # retrieved docs (ranked); [] if no retrieval
        "self_quality": float|None,      # the system's own heuristic score, if any
        "pool":     [doc, ...],          # pre-rerank candidates; [] if not applicable
    }

`pool` is what the reranker was given, before it cut to top_k. It separates a
ranking failure (the document was fetched and buried) from a fetch failure (the
document was never retrieved at all) -- two defects with different fixes that
the final ranked list cannot tell apart.

doc is a dict with at least {"doc_id", "title", "text", "source", "url"}.

Systems:
  - MultiAgentRAGGenerator        : full 4-agent pipeline (Rewriter -> Retriever -> RLAIF Evaluator),
                            with `union` and `retry` switches that ablate the
                            two-phrasing fetch and ManagerAgent's retry loop
  - SingleAgentGenerator  : the paper's baseline (raw query -> keyword retrieval -> 1 LLM call),
                            with `render="template"` for the fourth factorial cell
  - RawLLMGenerator       : no retrieval, ask a model directly (GPT/Claude/Llama/...)
                            -> this is the "compare against other models" column

Answer-metric fairness
----------------------
The multi-agent pipeline's own answer is a *template* assembled by
`EvaluatorAgent` (headers, bullet lists, source tags); the single-agent
baseline's answer is LLM prose. Scoring those two against each other with an
LLM judge measures answer *format* as much as answer *content*, so a
head-to-head on faithfulness/correctness between `marag` and `single_agent`
is confounded by construction.

The `marag_llm` arm removes that confound: same multi-agent retrieval, but the
answer is synthesised from the retrieved docs through `build_synthesis_prompt`
with the same model as the baseline. Then the only difference left between the
two arms is the retrieval pipeline, which is the claim under test. `marag`
stays available because it is the system the paper describes; `marag_llm`
keeps its template answer under `template_answer` so nothing is lost.

Better still, `single_agent_template` (SingleAgentGenerator with
render="template") completes the 2x2:

                      prose            template
  baseline retr.      single_agent     single_agent_template
  multi-agent retr.   marag_llm        marag

so rendering and retrieval are main effects with an interaction term, instead
of a format effect inferred by differencing two arms. The template cell calls
no LLM -- EvaluatorAgent.run is deterministic and document-agnostic -- so it
costs nothing to carry in every run.

The ablation ladder (see eval_harness/README.md) makes each remaining
capability a single-factor step: single_agent -> rewrite_only (adds rewriting)
-> marag_llm (adds union fetch) -> marag_llm_retry (adds adaptive retry) ->
marag (adds template rendering).

The Multi-Agent RAG System pipeline (`multiagent_rag_v3.py`) is a noisy CLI script; we import it
and silence stdout + the artificial `pause()`/`bar()` sleeps so it runs fast and
clean in batch.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import sys
from typing import List, Dict, Optional

from .providers import LLMClient, make_client, LLMError

# Make the project root importable regardless of where the harness is run from.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def doc_id(d: dict) -> str:
    """Stable id for a retrieved doc, used for relevance judgments / qrels."""
    key = (d.get("url") or "").strip() or (d.get("title", "") + "|" + d.get("source", ""))
    return hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()[:12]


def normalize_doc(d: dict) -> dict:
    """Project an Multi-Agent RAG System doc dict into the harness's canonical shape."""
    text = d.get("detail") or d.get("top_comment") or ""
    return {
        "doc_id": doc_id(d),
        "title": d.get("title", ""),
        "text": text,
        "source": d.get("source", "?"),
        "url": d.get("url", ""),
        "subreddit": d.get("subreddit", ""),
        "date": d.get("date", ""),
    }


@contextlib.contextmanager
def _silenced(mod):
    """Suppress stdout and the Multi-Agent RAG System module's pause()/bar() side effects."""
    saved_pause = getattr(mod, "pause", None)
    saved_bar = getattr(mod, "bar", None)
    mod.pause = lambda *a, **k: None
    mod.bar = lambda *a, **k: None
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            yield
    finally:
        if saved_pause is not None:
            mod.pause = saved_pause
        if saved_bar is not None:
            mod.bar = saved_bar


# ─────────────────────────────────────────────────────────────────────────
# Symmetric answer synthesis
# ─────────────────────────────────────────────────────────────────────────
# Every arm that turns retrieved docs into prose goes through the function
# below, so a difference in answer scores between two arms cannot be an
# artefact of a different prompt. The model is the caller's choice; pass the
# same one to both arms to keep that comparison clean too.

SYNTHESIS_INSTRUCTION = (
    "You are a software-update assistant. Answer the question using ONLY the "
    "sources below. Be concise (2-3 sentences). If the sources do not contain "
    "the answer, say so."
)


from agent_rules import RULES_ENV


def _rules_on() -> bool:
    return os.environ.get(RULES_ENV, "off").strip().lower() in ("on", "1", "true", "yes")


def rules_prefix() -> str:
    """AGENT_RULES.md as a prompt prefix, and only when asked for by name.

    Off unless MARAG_RULES says otherwise. The published answer numbers were
    produced without the file, so a rule someone adds to it must not move them
    without an arm that says it did. On, this is the same block the app
    prepends -- the ablation measures the deployed rules, not a copy of them.

    An arm that asked to be on and could not be is not an off arm, it is a
    broken one, so a missing or empty file raises here rather than quietly
    handing back the bare prompt and reporting a rules run.
    """
    if not _rules_on():
        return ""
    from agent_rules import rules_block
    block = rules_block()
    if not block:
        raise RuntimeError(
            f"{RULES_ENV} asked for the agent rules, but AGENT_RULES.md is "
            "missing or has no '## ' section to read.")
    return block


def rules_arm() -> Dict:
    """What the rules factor actually was, asked rather than assumed.

    Same reason `rerank_spec` is read back off the reranker instead of the
    environment: the run artifact has to record the arm that ran. The digest
    is what makes two runs comparable -- an edit to AGENT_RULES.md between
    arms changes it, and the pair is no longer an ablation of one factor.
    """
    block = rules_prefix()
    return {
        "rules_requested": os.environ.get(RULES_ENV, "off"),
        "rules_active": bool(block),
        "rules_sha": hashlib.sha256(block.encode()).hexdigest()[:12] if block else "",
        "rules_chars": len(block),
    }


def build_synthesis_prompt(query: str, docs: List[dict], top_k: int) -> str:
    """The one synthesis prompt, shared by every doc-grounded arm.

    `rules_prefix()` is empty unless MARAG_RULES asks for it, so the two arms
    of the rules ablation differ by that block and nothing else -- the same
    guarantee the comment above makes about the rest of this prompt.
    """
    ctx = "\n".join(
        f"- [{d.get('source','?')}] {d.get('title','')}: "
        f"{(d.get('detail') or d.get('text') or '')[:200]}"
        for d in docs[:top_k]
    ) or "No documents retrieved."
    return (
        f"{rules_prefix()}{SYNTHESIS_INSTRUCTION}\n\n"
        f"Question: {query}\n\nSources:\n{ctx}\n\nAnswer:"
    )


def render_template(marag_mod, docs: List[dict], query: str) -> Dict:
    """The other rendering: EvaluatorAgent's assembled template.

    Symmetric counterpart to `build_synthesis_prompt`. EvaluatorAgent.run is
    document-agnostic, so any arm's retrieved docs can be rendered this way --
    which is what makes rendering a *factor* that crosses retrieval rather than
    a property welded to the multi-agent arm. Returns the evaluator's whole
    result so callers can also read its `quality` and `signal`.
    """
    with _silenced(marag_mod):
        return marag_mod.EvaluatorAgent().run(docs, query)


class Generator:
    name = "base"

    def available(self) -> bool:
        return True

    def generate(self, query: str) -> Dict:
        raise NotImplementedError


class MultiAgentRAGGenerator(Generator):
    """
    Full multi-agent pipeline from multiagent_rag_v3.py.

    `synth=None` is the published system: the answer is EvaluatorAgent's
    template. Passing a client switches the answer to LLM prose synthesised
    from the same retrieved docs with `build_synthesis_prompt` — the arm that
    is answer-comparable to SingleAgentGenerator. Retrieval is identical
    either way, so IR metrics do not move between the two arms.
    """

    name = "marag"
    # Defaults live on the class, not only in __init__: generate() reads them,
    # and instances built with object.__new__ (the test stubs, which swap in
    # fake agents) never run __init__.
    union = True
    retry = False

    def __init__(self, top_k: int = 4, synth: Optional[LLMClient] = None,
                 union: bool = True, retry: bool = False):
        import multiagent_rag_v3 as marag
        self.marag = marag
        self.rewriter = marag.QueryRewriterAgent()
        self.retriever = marag.RetrieverAgent()
        self.evaluator = marag.EvaluatorAgent()
        self.top_k = top_k
        self.synth = synth
        self.union = union
        self.retry = retry
        base = "marag" if synth is None else "marag_llm"
        if not union:
            # Rewriting without the two-phrasing fetch: one rung below
            # marag_llm on the ladder, so marag_llm minus this arm is the
            # union-fetch effect and nothing else. The ladder compares it
            # against a prose arm, so a template answer here would reintroduce
            # the rendering confound the ladder exists to separate.
            if synth is None:
                raise ValueError(
                    "union=False is the 'rewrite_only' ablation rung, which is "
                    "compared against prose arms; pass synth= so its answer is "
                    "prose too")
            base = "rewrite_only"
        if retry:
            base += "_retry"
        self.name = base

    def available(self) -> bool:
        return True if self.synth is None else self.synth.available()

    def generate(self, query: str) -> Dict:
        retried = False
        with _silenced(self.marag):
            rewrite = self.rewriter.run(query)
            docs = self.retriever.run(rewrite["rewritten"], top_k=self.top_k,
                                      original_query=query, union=self.union)
            pool = list(getattr(self.retriever, "last_pool", []) or [])
            result = self.evaluator.run(docs, query)
            # `"retry" not in query` is ManagerAgent's own recursion guard,
            # reproduced verbatim: it also means a question that happens to
            # contain the word "retry" never triggers one. Faithful to the
            # system under test, and a reason not to read this arm's retry rate
            # as a property of the questions alone.
            if self.retry and "negative" in result.get("signal", "") \
                    and "retry" not in query:
                # ManagerAgent's adaptive loop (multiagent_rag_v3.py, class
                # ManagerAgent): on a negative RLAIF signal, widen the FETCH
                # with filler terms while still ranking against the user's own
                # words. Reproduced here rather than called because
                # ManagerAgent.run returns only the answer string and the
                # harness needs the retrieved documents too.
                #
                # NOTE the real threshold: EvaluatorAgent emits the negative
                # signal at quality < 0.15, not the 0.30 the write-up claims.
                # 0.30 is a different constant in that method (a quality floor
                # for tier-1 and Apple sources).
                retried = True
                docs = self.retriever.run(query + " software update release",
                                          top_k=self.top_k, original_query=query,
                                          union=self.union)
                # The retry OVERWRITES RetrieverAgent.last_pool, so reporting it
                # alone would understate the fetch: the system saw both pools,
                # and pool recall is meant to be the ceiling of everything
                # fetched. Union them, first attempt first, deduped by doc_id.
                seen = {doc_id(d) for d in pool}
                for d in (getattr(self.retriever, "last_pool", []) or []):
                    if doc_id(d) not in seen:
                        seen.add(doc_id(d))
                        pool.append(d)
                result = self.evaluator.run(docs, query)
        template_answer = result.get("answer", "")
        answer = template_answer
        if self.synth is not None:
            try:
                answer = self.synth.generate(
                    build_synthesis_prompt(query, docs, self.top_k),
                    temperature=0.0, max_tokens=400)
            except LLMError as e:
                answer = f"[generation error: {e}]"
        out = {
            "answer": answer,
            "docs": [normalize_doc(d) for d in docs],
            "self_quality": result.get("quality"),
            "rewritten_query": rewrite.get("rewritten", ""),
            "pool": [normalize_doc(d) for d in pool],
            "rerank_spec": getattr(self.retriever, "last_rerank_spec", ""),
            "rerank_degraded": getattr(self.retriever, "last_rerank_degraded", False),
            "retried": retried,
        }
        if self.synth is not None:
            # The published template answer, kept for audit: the synthesised
            # arm replaces what is scored, not what the system produced.
            out["template_answer"] = template_answer
            out["synth_model"] = self.synth.spec
        return out


class SingleAgentGenerator(Generator):
    """
    Paper's baseline: raw query, keyword retrieval (no rewriting, no CVE agent,
    no RLAIF), and a single LLM synthesis call. Uses Multi-Agent RAG System's retriever but feeds
    it the *raw* query and a plain synthesis prompt — i.e. the multi-agent
    machinery stripped away.
    """

    name = "single_agent"
    render = "prose"   # class default, for the same reason as above

    def __init__(self, client: Optional[LLMClient] = None, top_k: int = 4,
                 render: str = "prose"):
        import multiagent_rag_v3 as marag
        self.marag = marag
        self.retriever = marag.RetrieverAgent()
        self.top_k = top_k
        if render not in ("prose", "template"):
            raise ValueError(f"render must be 'prose' or 'template', got {render!r}")
        self.render = render
        # `render="template"` is the fourth cell of the rendering x retrieval
        # design: baseline retrieval, but the answer assembled by
        # EvaluatorAgent's template instead of synthesised as prose. It closes
        # the factorial that marag / marag_llm / single_agent leave open, so
        # the format effect can be estimated as a main effect with an
        # interaction term rather than inferred by differencing two arms.
        # It calls no LLM, so it is deterministic and effectively free.
        self.client = None if render == "template" else (client or make_client("ollama:mistral"))
        if render == "template":
            self.name = "single_agent_template"

    def available(self) -> bool:
        return True if self.client is None else self.client.available()

    def generate(self, query: str) -> Dict:
        with _silenced(self.marag):
            docs = self.retriever.run(query, top_k=self.top_k, original_query=query)
        self_quality = None
        if self.render == "template":
            result = render_template(self.marag, docs, query)
            answer = result.get("answer", "")
            self_quality = result.get("quality")
        else:
            prompt = build_synthesis_prompt(query, docs, self.top_k)
            try:
                answer = self.client.generate(prompt, temperature=0.0, max_tokens=400)
            except LLMError as e:
                answer = f"[generation error: {e}]"
        return {
            "answer": answer,
            "docs": [normalize_doc(d) for d in docs],
            "self_quality": self_quality,
            # The baseline shares RetrieverAgent with the multi-agent arm, so it
            # is reranked by the same backend. That is precisely why it is not a
            # rerank-independent control, and why the pool is logged for it too.
            "pool": [normalize_doc(d) for d in getattr(self.retriever, "last_pool", [])],
            "rerank_spec": getattr(self.retriever, "last_rerank_spec", ""),
            "rerank_degraded": getattr(self.retriever, "last_rerank_degraded", False),
        }


class RawLLMGenerator(Generator):
    """No retrieval — ask a model directly. The 'other models' comparison column."""

    def __init__(self, client: LLMClient):
        self.client = client
        self.name = f"raw:{client.spec}"

    def available(self) -> bool:
        return self.client.available()

    def generate(self, query: str) -> Dict:
        prompt = (
            "You are a software-update assistant. Answer the user's question about "
            "software releases, bugs, or security as accurately as you can in 2-3 "
            "sentences. If you are unsure, say so rather than inventing details.\n\n"
            f"Question: {query}\n\nAnswer:"
        )
        try:
            answer = self.client.generate(prompt, temperature=0.0, max_tokens=400)
        except LLMError as e:
            answer = f"[generation error: {e}]"
        return {"answer": answer, "docs": [], "self_quality": None, "pool": []}



class SelfReflectiveGenerator(Generator):
    """Self-RAG / CRAG-style critique loop over this project's retrieval.

    A reimplementation of the published *mechanisms*, not the published systems:
    neither Self-RAG's reflection-token checkpoint nor CRAG's fine-tuned
    retrieval evaluator is used. See eval_harness/selfreflective.py for what is
    reimplemented and where it deviates.

    Retrieval is the same RetrieverAgent every other doc-grounded arm uses, fed
    the raw question, and the drafting prompt is the shared one -- so a
    difference against `single_agent` is the critique loop and nothing else.
    """

    def __init__(self, client: Optional[LLMClient] = None, top_k: int = 4,
                 keep_partial: bool = True):
        import multiagent_rag_v3 as marag
        from .selfreflective import SelfReflectiveRAG
        self.marag = marag
        self.retriever = marag.RetrieverAgent()
        self.top_k = top_k
        self.client = client or make_client("ollama:llama3.1")
        self.engine = SelfReflectiveRAG(self.client, top_k=top_k,
                                        keep_partial=keep_partial)
        self.name = "selfreflective"

    def available(self) -> bool:
        return self.client.available()

    def generate(self, query: str) -> Dict:
        with _silenced(self.marag):
            docs = self.retriever.run(query, top_k=self.top_k,
                                      original_query=query)
            pool = list(getattr(self.retriever, "last_pool", []) or [])
        out = self.engine.run(query, docs, build_synthesis_prompt)
        # `docs` stays the full retrieved list rather than the critique-filtered
        # one: IR metrics score what the system retrieved, and reporting only the
        # kept documents would flatter precision by hiding the discards.
        return {
            "answer": out["answer"],
            "docs": [normalize_doc(d) for d in docs],
            "self_quality": None,
            "pool": [normalize_doc(d) for d in pool],
            "trace": out["trace"],
        }


class GroundedSingleAgentGenerator(SingleAgentGenerator):
    """Baseline retrieval, but over a *grounded* question.

    The rung the capability table asks for. Query understanding -- resolving
    "today" to a date, recognising "Linux" as a catalog product, deciding
    whether the question is about security or about a release -- is not
    coordination, so a single-agent arm can have all of it without becoming
    multi-agent. Giving it only to the multi-agent pipeline would make every
    measured gap the sum of "coordination helps" and "understanding the
    question helps", and the paper claims only the first.

    Retrieval is `RetrieverAgent` exactly as `single_agent` uses it, on the
    same `top_k`, with the same synthesis prompt and model. The single
    difference is that the question handed to it has been through
    `grounding.ground`, and that documents the question's intent forbids are
    dropped -- for a "latest version" question a CVE row is not weak evidence,
    it is wrong evidence.

    Deliberately paired with `single_agent`, not with `marag`: A1 -> A1g
    measures grounding with no coordination present at all.
    """

    name = "single_agent_grounded"

    def __init__(self, client: Optional[LLMClient] = None, top_k: int = 4,
                 now=None):
        super().__init__(client=client, top_k=top_k, render="prose")
        self.name = "single_agent_grounded"
        # Injected for the same reason `temporal` injects it: a run replayed
        # next month must ground its questions the way the original run did.
        self._now = now
        import grounding as _grounding
        import vendor as _vendor
        self._ground = _grounding.ground
        self._vendor = _vendor
        self._catalog = _vendor.load_catalog()

    # How many candidates to ask for before the record-type filter cuts to
    # top_k. Filtering the top 4 is useless when all 4 are advisories, which is
    # the normal case for a product with an active CVE feed: /api/v/?q=linux
    # returns 449 advisory rows to 157 release rows, and the advisories are
    # newer because they are filed daily and kernels are not released daily.
    # Over-fetching is what gives the filter something to keep.
    POOL_FACTOR = 6

    def generate(self, query: str) -> Dict:
        g = self._ground(query, now=self._now, catalog=self._catalog)
        # The retriever is given the grounded phrasing; `original_query` stays
        # the user's wording, which is what the reranker scores against.
        # `retrieval_query`, not `retrieval_phrasings[0]`: the latter leads with
        # the bare product name for /api/v/, which matches on product names
        # only. RetrieverAgent scores over mixed text, where the version string
        # is what identifies the answer -- retrieving benchmark question 29 on
        # "firefox" instead of "firefox v148.0.0" scored recall@5 0.00 against
        # the baseline's 1.00.
        retrieval_query = g.retrieval_query or query
        pool_k = max(self.top_k * self.POOL_FACTOR, 24)
        with _silenced(self.marag):
            pool = self.retriever.run(retrieval_query, top_k=pool_k,
                                      original_query=query)

        docs = list(pool)
        if "cve" not in g.citable_kinds:
            kept = [d for d in pool
                    if self._vendor.doc_kind(d) in g.citable_kinds]
            # Never empty the pool on a filter: an answer with no documents is
            # worse than an answer over imperfect ones, and the ladder needs
            # this rung to differ from A1 by grounding, not by starvation. When
            # the filter does empty it, that is itself the finding -- the pool
            # genuinely held no shipped release -- and the synthesis prompt
            # will say so rather than name an advisory as a version.
            docs = kept or pool
        docs = docs[:self.top_k]

        prompt = build_synthesis_prompt(query, docs, self.top_k)
        try:
            answer = self.client.generate(prompt, temperature=0.0, max_tokens=400)
        except LLMError as e:
            answer = f"[generation error: {e}]"
        return {
            "answer": answer,
            "docs": [normalize_doc(d) for d in docs],
            "pool": [normalize_doc(d) for d in pool],
            "self_quality": None,
            "rewritten_query": g.rewritten,
            "intent": g.intent.label if g.intent else "",
            "vendors": g.vendor_names,
        }


def build_generators(specs: List[str], top_k: int = 4) -> List[Generator]:
    """
    Build generators from short specs:
      "marag"                      -> MultiAgentRAGGenerator (template answer)
      "marag:ollama:mistral"       -> same pipeline, answer synthesised by that
                                      model through the shared prompt, so its
                                      answer scores are comparable to
                                      single_agent's (reported as "marag_llm")
      "rewrite_only:ollama:mistral"-> rewriting WITHOUT the two-phrasing union
                                      fetch, prose answer. One ablation rung
                                      below marag_llm.
      "marag_retry:ollama:mistral" -> marag_llm plus ManagerAgent's adaptive
                                      retry on a negative RLAIF signal
                                      (reported as "marag_llm_retry");
                                      "marag_retry" alone keeps the template
                                      answer (reported as "marag_retry")
      "single_agent_template"      -> baseline retrieval rendered as the
                                      EvaluatorAgent template: the fourth cell
                                      of the rendering x retrieval factorial
      "selfreflective"             -> Self-RAG/CRAG-style critique loop over the
                                      same retrieval (reimplementation, not the
                                      published checkpoints)
      "selfreflective:ollama:llama3.1" -> same, with a chosen critic/synthesis model
      "single_agent"               -> SingleAgentGenerator (mistral synthesis)
      "single_agent:ollama:llama3.1" -> SingleAgentGenerator with a given model
      "raw:ollama:llama3.1"        -> RawLLMGenerator over that model
      "raw:openai:gpt-4o"          -> RawLLMGenerator over GPT-4o (if key present)
    """
    gens: List[Generator] = []
    for spec in specs:
        if spec == "marag":
            gens.append(MultiAgentRAGGenerator(top_k=top_k))
        elif spec.startswith("marag:"):
            gens.append(MultiAgentRAGGenerator(
                top_k=top_k, synth=make_client(spec.split(":", 1)[1])))
        elif spec == "rewrite_only":
            gens.append(MultiAgentRAGGenerator(
                top_k=top_k, synth=make_client("ollama:mistral"), union=False))
        elif spec.startswith("rewrite_only:"):
            gens.append(MultiAgentRAGGenerator(
                top_k=top_k, synth=make_client(spec.split(":", 1)[1]), union=False))
        elif spec == "marag_retry":
            gens.append(MultiAgentRAGGenerator(top_k=top_k, retry=True))
        elif spec.startswith("marag_retry:"):
            gens.append(MultiAgentRAGGenerator(
                top_k=top_k, synth=make_client(spec.split(":", 1)[1]), retry=True))
        elif spec == "single_agent_grounded":
            gens.append(GroundedSingleAgentGenerator(top_k=top_k))
        elif spec.startswith("single_agent_grounded:"):
            gens.append(GroundedSingleAgentGenerator(
                make_client(spec.split(":", 1)[1]), top_k))
        elif spec == "single_agent_template":
            gens.append(SingleAgentGenerator(top_k=top_k, render="template"))
        elif spec == "single_agent":
            gens.append(SingleAgentGenerator(top_k=top_k))
        elif spec.startswith("single_agent:"):
            gens.append(SingleAgentGenerator(make_client(spec.split(":", 1)[1]), top_k))
        elif spec == "selfreflective":
            gens.append(SelfReflectiveGenerator(top_k=top_k))
        elif spec.startswith("selfreflective:"):
            gens.append(SelfReflectiveGenerator(
                make_client(spec.split(":", 1)[1]), top_k))
        elif spec.startswith("raw:"):
            gens.append(RawLLMGenerator(make_client(spec.split(":", 1)[1])))
        else:
            raise ValueError(f"unknown generator spec: {spec}")
    return gens
