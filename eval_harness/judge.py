"""
LLM-as-judge: relevance labels (qrels) and answer scoring.
==========================================================
Two responsibilities:

1. relevance_label(query, doc) -> 0|1|2
   Graded relevance for building a `qrels` file. Pooled across all systems and
   cached to disk, so the (slow, non-deterministic) judging happens once and
   downstream metrics are reproducible and auditable.

2. score_answer(query, answer, contexts, ground_truth) -> dict
   RAGAS-style answer metrics, each 0..1:
     - faithfulness     : is the answer grounded in the retrieved contexts?
     - answer_relevance : does it actually address the question?
     - correctness      : does it agree with the ground-truth answer (when available)?

To reduce self-evaluation bias (the conference's "independence of providers"
point), the judge should be a *different* model from the system under test.
The judge returns strict JSON; we parse defensively.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from .providers import LLMClient, make_client, LLMError


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text).rstrip("`").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _clamp01(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


class Judge:
    def __init__(self, spec: str = "ollama:llama3.1"):
        self.client: LLMClient = make_client(spec)
        self.spec = self.client.spec

    def available(self) -> bool:
        return self.client.available()

    # ---- relevance labelling (qrels) ------------------------------------
    def relevance_label(self, query: str, doc: dict) -> int:
        title = doc.get("title", "")
        text = (doc.get("text", "") or "")[:600]
        src = doc.get("source", "?")
        prompt = (
            "Rate how relevant this document is to the user's software-update "
            "question. Use this scale:\n"
            "  2 = highly relevant (directly answers or is about the exact topic)\n"
            "  1 = related (same product/area but not a direct answer)\n"
            "  0 = irrelevant\n\n"
            f'Question: "{query}"\n\n'
            f"Document (source={src}):\nTitle: {title}\nContent: {text}\n\n"
            'Respond with JSON only: {"relevance": <0|1|2>}'
        )
        try:
            raw = self.client.generate(prompt, temperature=0.0, max_tokens=60)
        except LLMError:
            return 0
        obj = _extract_json(raw) or {}
        try:
            g = int(round(float(obj.get("relevance", 0))))
        except (TypeError, ValueError):
            g = 0
        return max(0, min(2, g))

    # ---- answer scoring -------------------------------------------------
    def score_answer(self, query: str, answer: str, contexts: List[str],
                     ground_truth: Optional[str] = None) -> Dict[str, float]:
        ctx = "\n".join(f"- {c[:300]}" for c in contexts[:6]) or "(no retrieved context)"
        gt_block = (
            f'\nReference answer (ground truth): "{ground_truth[:400]}"\n'
            if ground_truth else
            "\n(No reference answer available; set correctness to null.)\n"
        )
        prompt = (
            "You are a strict evaluator of a software-update Q&A system. "
            "Score the ANSWER on three axes, each from 0.0 to 1.0:\n"
            "  faithfulness     - every claim is supported by the CONTEXT (no hallucination). "
            "If there is no context, judge whether claims are plausibly grounded vs invented.\n"
            "  answer_relevance - the answer directly addresses the QUESTION.\n"
            "  correctness      - the answer agrees with the REFERENCE answer. "
            "If no reference is given, return null.\n\n"
            f'QUESTION: "{query}"\n\n'
            f"CONTEXT:\n{ctx}\n"
            f"{gt_block}\n"
            f'ANSWER: "{answer[:1200]}"\n\n'
            'Respond with JSON only, e.g. '
            '{"faithfulness":0.8,"answer_relevance":0.9,"correctness":0.7}'
        )
        try:
            raw = self.client.generate(prompt, temperature=0.0, max_tokens=200)
        except LLMError:
            raw = ""
        obj = _extract_json(raw) or {}
        out = {
            "faithfulness": _clamp01(obj.get("faithfulness", 0.0)),
            "answer_relevance": _clamp01(obj.get("answer_relevance", 0.0)),
        }
        corr = obj.get("correctness", None)
        out["correctness"] = None if (corr is None or ground_truth is None) else _clamp01(corr)
        return out
