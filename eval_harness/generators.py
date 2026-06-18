"""
Generator adapters — the systems under test.
============================================
Every generator implements:

    gen.generate(query) -> {
        "answer":   str,                 # final natural-language answer
        "docs":     [doc, ...],          # retrieved docs (ranked); [] if no retrieval
        "self_quality": float|None,      # the system's own heuristic score, if any
    }

doc is a dict with at least {"doc_id", "title", "text", "source", "url"}.

Systems:
  - MultiAgentRAGGenerator        : full 4-agent pipeline (Rewriter -> Retriever -> RLAIF Evaluator)
  - SingleAgentGenerator  : the paper's baseline (raw query -> keyword retrieval -> 1 LLM call)
  - RawLLMGenerator       : no retrieval, ask a model directly (GPT/Claude/Llama/...)
                            -> this is the "compare against other models" column

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


class Generator:
    name = "base"

    def available(self) -> bool:
        return True

    def generate(self, query: str) -> Dict:
        raise NotImplementedError


class MultiAgentRAGGenerator(Generator):
    """Full multi-agent pipeline from multiagent_rag_v3.py."""

    name = "marag"

    def __init__(self, top_k: int = 4):
        import multiagent_rag_v3 as marag
        self.marag = marag
        self.rewriter = marag.QueryRewriterAgent()
        self.retriever = marag.RetrieverAgent()
        self.evaluator = marag.EvaluatorAgent()
        self.top_k = top_k

    def generate(self, query: str) -> Dict:
        with _silenced(self.marag):
            rewrite = self.rewriter.run(query)
            docs = self.retriever.run(rewrite["rewritten"], top_k=self.top_k,
                                      original_query=query)
            result = self.evaluator.run(docs, query)
        return {
            "answer": result.get("answer", ""),
            "docs": [normalize_doc(d) for d in docs],
            "self_quality": result.get("quality"),
            "rewritten_query": rewrite.get("rewritten", ""),
        }


class SingleAgentGenerator(Generator):
    """
    Paper's baseline: raw query, keyword retrieval (no rewriting, no CVE agent,
    no RLAIF), and a single LLM synthesis call. Uses Multi-Agent RAG System's retriever but feeds
    it the *raw* query and a plain synthesis prompt — i.e. the multi-agent
    machinery stripped away.
    """

    name = "single_agent"

    def __init__(self, client: Optional[LLMClient] = None, top_k: int = 4):
        import multiagent_rag_v3 as marag
        self.marag = marag
        self.retriever = marag.RetrieverAgent()
        self.top_k = top_k
        self.client = client or make_client("ollama:mistral")

    def available(self) -> bool:
        return self.client.available()

    def generate(self, query: str) -> Dict:
        with _silenced(self.marag):
            docs = self.retriever.run(query, top_k=self.top_k, original_query=query)
        ctx = "\n".join(
            f"- [{d.get('source','?')}] {d.get('title','')}: {(d.get('detail') or '')[:200]}"
            for d in docs[: self.top_k]
        ) or "No documents retrieved."
        prompt = (
            "You are a software-update assistant. Answer the question using ONLY the "
            "sources below. Be concise (2-3 sentences). If the sources do not contain "
            "the answer, say so.\n\n"
            f"Question: {query}\n\nSources:\n{ctx}\n\nAnswer:"
        )
        try:
            answer = self.client.generate(prompt, temperature=0.0, max_tokens=400)
        except LLMError as e:
            answer = f"[generation error: {e}]"
        return {
            "answer": answer,
            "docs": [normalize_doc(d) for d in docs],
            "self_quality": None,
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
        return {"answer": answer, "docs": [], "self_quality": None}


def build_generators(specs: List[str], top_k: int = 4) -> List[Generator]:
    """
    Build generators from short specs:
      "marag"                      -> MultiAgentRAGGenerator
      "single_agent"               -> SingleAgentGenerator (mistral synthesis)
      "single_agent:ollama:llama3.1" -> SingleAgentGenerator with a given model
      "raw:ollama:llama3.1"        -> RawLLMGenerator over that model
      "raw:openai:gpt-4o"          -> RawLLMGenerator over GPT-4o (if key present)
    """
    gens: List[Generator] = []
    for spec in specs:
        if spec == "marag":
            gens.append(MultiAgentRAGGenerator(top_k=top_k))
        elif spec == "single_agent":
            gens.append(SingleAgentGenerator(top_k=top_k))
        elif spec.startswith("single_agent:"):
            gens.append(SingleAgentGenerator(make_client(spec.split(":", 1)[1]), top_k))
        elif spec.startswith("raw:"):
            gens.append(RawLLMGenerator(make_client(spec.split(":", 1)[1])))
        else:
            raise ValueError(f"unknown generator spec: {spec}")
    return gens
