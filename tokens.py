"""
Per-question model-call and token tally.
========================================

Every local model call the system makes goes through one of three
`urllib` sites -- `call_llama` (rewrite), `LLMCascadeReranker` (candidate
grading) and `eval_harness.providers.OllamaClient` (synthesis, and the
judge). Ollama's `/api/generate` response carries `prompt_eval_count` and
`eval_count`; each site hands its parsed response here with a role label.

The harness resets the tally before a generator runs and snapshots it after,
so a per_query row's `tokens` is that arm's own spend on that question: the
judge's calls land after the snapshot and are not counted. Embeddings are
counted as calls only -- `/api/embeddings` reports no token counts.

Process-wide and single-threaded on purpose: the harness runs arms one after
another, and a lock here would be protecting nothing.
"""
from __future__ import annotations

from typing import Dict

_T: Dict = {}


def reset() -> None:
    _T.clear()
    _T.update({"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
               "embed_calls": 0, "by_role": {}})


def record(resp: dict, role: str) -> None:
    """Tally one `/api/generate` response. Missing counts tally as 0 tokens."""
    if not _T:
        reset()
    p = int(resp.get("prompt_eval_count") or 0)
    c = int(resp.get("eval_count") or 0)
    _T["calls"] += 1
    _T["prompt_tokens"] += p
    _T["completion_tokens"] += c
    r = _T["by_role"].setdefault(role, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
    r["calls"] += 1
    r["prompt_tokens"] += p
    r["completion_tokens"] += c


def record_embed() -> None:
    if not _T:
        reset()
    _T["embed_calls"] += 1


def snapshot() -> dict:
    if not _T:
        reset()
    out = dict(_T)
    out["by_role"] = {k: dict(v) for k, v in _T["by_role"].items()}
    out["total_tokens"] = out["prompt_tokens"] + out["completion_tokens"]
    return out


if __name__ == "__main__":
    reset()
    record({"prompt_eval_count": 100, "eval_count": 20}, "rewrite")
    record({"prompt_eval_count": 50}, "rerank")
    record_embed()
    s = snapshot()
    assert (s["calls"], s["prompt_tokens"], s["completion_tokens"], s["embed_calls"]) == (2, 150, 20, 1)
    assert s["by_role"]["rerank"] == {"calls": 1, "prompt_tokens": 50, "completion_tokens": 0}
    reset()
    assert snapshot()["total_tokens"] == 0
    print("ok")
