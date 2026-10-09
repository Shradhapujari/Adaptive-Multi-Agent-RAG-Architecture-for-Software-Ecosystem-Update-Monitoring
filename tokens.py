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

This is also where those three sites get the request options they share, so
that a model-loading or context-window setting is one number, not three.
"""
from __future__ import annotations

import json
import os
from typing import Dict

# `keep_alive=-1` keeps the model resident between calls. Ollama's default
# unloads it after five idle minutes, and a judge pass that alternates models
# pays a multi-second reload per swap that then lands in the latency column as
# if the architecture had spent it. `num_ctx=4096` is Ollama 0.34's own default
# for these models (`ollama ps` shows CONTEXT 4096), stated explicitly so a
# future Ollama that changes the default cannot change a measurement. Both are
# overridable for a memory-constrained host: MARAG_OLLAMA_KEEP_ALIVE=5m,
# MARAG_OLLAMA_NUM_CTX=2048.
_ka = os.environ.get("MARAG_OLLAMA_KEEP_ALIVE", "-1")
KEEP_ALIVE = int(_ka) if _ka.lstrip("-").isdigit() else _ka
NUM_CTX = int(os.environ.get("MARAG_OLLAMA_NUM_CTX", "4096"))


def ollama_payload(model: str, prompt: str, **options) -> dict:
    """The `/api/generate` body every call site sends; `options` are merged
    over the shared ones (temperature, num_predict, ...)."""
    opts: Dict = {"num_ctx": NUM_CTX}
    opts.update(options)
    return {"model": model, "prompt": prompt, "stream": False,
            "keep_alive": KEEP_ALIVE, "options": opts}

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


def delta(before: dict, after: dict) -> dict:
    """Tokens spent between two snapshots -- one graph transition's bill."""
    return {k: after[k] - before[k] for k in
            ("calls", "prompt_tokens", "completion_tokens", "embed_calls")}


TRACE_ENV = "MARAG_TRACE"


def emit(step: dict) -> None:
    """Append one transition record to the JSONL file $MARAG_TRACE names.

    Off when the variable is unset, so the harness's numbers do not change
    and nothing is written under results/ by accident. One line per graph
    transition: node, edge_taken, reason, tokens, dur_ms, contract_ok,
    state_hash_in/out -- enough to bill a token or a retry to the node that
    caused it, and to prove two replays walked the same states.
    """
    path = os.environ.get(TRACE_ENV)
    if not path:
        return
    with open(path, "a") as f:
        f.write(json.dumps(step, sort_keys=True, default=str) + "\n")


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
    assert delta({"calls": 1, "prompt_tokens": 10, "completion_tokens": 2, "embed_calls": 0},
                 {"calls": 3, "prompt_tokens": 50, "completion_tokens": 9, "embed_calls": 1}) == \
        {"calls": 2, "prompt_tokens": 40, "completion_tokens": 7, "embed_calls": 1}
    print("ok")
