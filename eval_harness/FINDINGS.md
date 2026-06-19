# Evaluation Findings

Results from the Tier-1 harness (`eval_harness/`) on the 10 ground-truth
validation questions (`validation_gt.json`), judge `ollama:llama3.1`, seed 42.
Reproduce: see `eval_harness/README.md`. Numbers are auditable in
`results/<run_id>/` (per_query.jsonl, qrels.json).

> ⚠️ Sample size is small (n=10) with wide, overlapping confidence intervals —
> these are directional findings to be confirmed on the 50-question set with a
> stronger independent judge (set an API key and `--judge openai:gpt-4o`).

## Finding 1 — On standard IR metrics, the single-agent baseline outperforms the multi-agent system

| System | nDCG@1 | nDCG@3 | MRR | faithfulness |
|---|---|---|---|---|
| single_agent (raw query) | **0.800** | **0.743** | **0.800** | **0.805** |
| marag (multi-agent)      | 0.167 | 0.193 | 0.433 | 0.660 |

This **inverts the paper's headline** (+37.4% for the multi-agent system). The
paper's number was measured on a bespoke keyword-overlap "quality" score, not a
standard IR metric. Under Recall@k / nDCG@k / MRR with judged relevance, the
multi-agent pipeline currently loses.

## Finding 2 — The Query Rewriter is the cause: it degrades retrieval

Isolating the rewriter (same retriever, raw vs rewritten query, same qrels —
`python -m eval_harness.diagnose_rewriter`):

| | raw query | rewritten query |
|---|---|---|
| Mean nDCG@3 | **0.743** | 0.193 |
| Rewrite helped / hurt / tie | — | **0 / 7 / 3** |

The rewriter helped **0 of 10** queries and hurt **7**. Examples:

| Raw query | Rewrite | nDCG@3 raw → rw |
|---|---|---|
| `G6 Bullet unstable?` | `"Unstable behavior in G6 Bullet software: …"` | 0.879 → 0.242 |
| `Queue limitations - hard limit of 200` | `"Queue capacity threshold - does setting a…"` | 1.000 → 0.000 |
| `I can't run Ace-Step 1.5 XL on Comfy!?` | `"Are there any known issues or updates for…"` | 1.000 → 0.000 |

**Root cause.** The retriever uses keyword/synonym overlap, and the Reddit
corpus is written in the *same informal language as the user's raw query*. The
rewriter expands queries into verbose "technical document vocabulary," which
**introduces** lexical mismatch with the corpus rather than removing it. The
paper's premise — that rewriting bridges a vocabulary gap — does not hold when
the retrieval signal is lexical and the corpus is user-generated text.

## Implication — motivates the semantic-retrieval upgrade (Tier 2)

This is direct, quantified evidence for the paper's own future-work item:
**replace keyword matching with embedding retrieval (FAISS + BGE)**. With
semantic matching, query rewriting should become neutral-to-helpful (matching is
by meaning, not surface tokens). The recommended next experiment:

1. Add an embedding retriever behind the same `RetrieverAgent` interface.
2. Re-run this harness: `raw vs rewritten` nDCG under semantic retrieval.
3. Expect the gap to close or reverse — turning Finding 2 from a weakness into
   the justification for the multi-agent design.
