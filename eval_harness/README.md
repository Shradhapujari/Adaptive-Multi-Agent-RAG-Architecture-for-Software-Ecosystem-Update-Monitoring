# Multi-Agent RAG System Evaluation Harness (Tier 1)

A reproducible, **benchmark-grounded, model-comparative** evaluation for the
Multi-Agent RAG System multi-agent RAG system. It replaces the paper's bespoke "retrieval
quality" heuristic with the metrics reviewers actually expect, and runs the
same questions through multiple systems and models head-to-head.

## Why this exists

Conference / poster feedback that this directly answers:

| Feedback | What the harness does |
|---|---|
| "Evaluate answers with **benchmarks**" | Standard IR metrics: **Recall@k, nDCG@k, MRR** over LLM-judged relevance, plus RAGAS-style **faithfulness / answer-relevance / correctness** |
| "Compare with **other models** (GPT, Gemini, Grok)" | Provider-agnostic generators — run Multi-Agent RAG System vs single-agent vs raw GPT/Claude/Llama/Mistral in one table |
| "Why **multi-agent** / does it help?" | Run `marag` vs `single_agent` side by side (the ablation) |
| "**Result tables and graphs**" | Auto-generated markdown + CSV tables and matplotlib bar charts with 95% CIs |
| "**Reproducibility / transparency of data**" | Frozen dataset hash, seed, cached & saved qrels, full per-query JSONL, config manifest |

## Install / run

Use the project's Python 3.11 environment (the Multi-Agent RAG System module needs 3.10+):

```bash
venv311/bin/python -m eval_harness.run_eval \
  --dataset validation_gt.json \
  --generators marag,single_agent,raw:ollama:llama3.1,raw:ollama:mistral \
  --judge ollama:llama3.1
```

Requires **Ollama running** locally (`llama3.1`, `mistral` pulled). Add an
`OPENAI_API_KEY` or `ANTHROPIC_API_KEY` to your environment and the GPT/Claude
generators light up automatically — **no code change**:

```bash
export OPENAI_API_KEY=sk-...
venv311/bin/python -m eval_harness.run_eval --generators marag,raw:openai:gpt-4o
```

## Generator specs

| Spec | System |
|---|---|
| `marag` | Full 4-agent pipeline (Rewriter → Retriever → RLAIF Evaluator) |
| `single_agent` | Paper's baseline: raw query → keyword retrieval → 1 LLM call |
| `single_agent:openai:gpt-4o` | Baseline with a chosen synthesis model |
| `raw:ollama:llama3.1` | No retrieval — model answers directly (model-comparison column) |
| `raw:openai:gpt-4o` | Same, GPT-4o (needs key) |
| `raw:anthropic:claude-sonnet-4-6` | Same, Claude (needs key) |

## Output

Each run writes `results/<run_id>/`:

- `report.md` — head-to-head + per-category tables
- `aggregate.csv` — same numbers, machine-readable
- `plot_retrieval.png`, `plot_answer.png` — bar charts with error bars
- `per_query.jsonl` — every system's answer + scores per question (audit trail)
- `qrels.json` — the relevance judgments used (auditable, cached & reused)
- `config.json` — full run manifest (dataset hash, seed, models, judge)

## Known limitations (honest notes)

- **Judge independence.** With only local models, the judge can overlap with a
  system under test (e.g. `raw:ollama:llama3.1` judged by `ollama:llama3.1`).
  For publication, use a stronger independent judge (set an API key and
  `--judge openai:gpt-4o`). This is flagged because the conference panels
  stressed provider independence in evaluation.
- **Ground-truth coverage.** `correctness` is only computed where the dataset
  provides a reference answer (e.g. `validation_gt.json`). IR metrics depend on
  judged relevance, not gold qrels — pooled & cached, but judge-derived.
- **Live APIs.** Multi-Agent RAG System retrieves from releasetrain.io live APIs, so the
  document pool can drift over time. The qrels cache + saved per-query docs
  make a *given run* reproducible; for a fully frozen corpus, snapshot the pool.
```
