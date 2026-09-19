# Evaluation Findings

Results from the Tier-1 harness (`eval_harness/`) on the 10 ground-truth
validation questions (`validation_gt.json`), judge `ollama:llama3.1`, seed 42.
Reproduce: see `eval_harness/README.md`. Numbers are auditable in
`results/<run_id>/` (per_query.jsonl, qrels.json).

> ⚠️ Sample size is small (n=10) with wide, overlapping confidence intervals.
> These are directional findings. The 300-question multi-ecosystem set
> (`data/benchmark_300.json`) exists to test them at a size that can support a
> claim, and a stronger independent judge is still needed
> (`--judge openai:gpt-4o` with an API key set).

This file reads in order: a defect was measured, misdiagnosed once, then
correctly diagnosed and fixed. The superseded findings are kept because the
sequence is the evidence.

---

## Finding 1 — The published retrieval gain does not survive standard IR metrics

| System | nDCG@1 | nDCG@3 | MRR | faithfulness |
|---|---:|---:|---:|---:|
| single_agent (raw query) | **0.800** | **0.743** | **0.800** | **0.805** |
| marag (multi-agent)      | 0.167 | 0.193 | 0.433 | 0.660 |

This **inverts the paper's headline**. The paper's number was measured on a
bespoke keyword-overlap "quality" score, not a standard IR metric. Under
Recall@k / nDCG@k / MRR with judged relevance, the multi-agent pipeline lost.

**Status: confirmed, and the cause is now known — see Findings 3 and 4.**

---

## Finding 2 — First diagnosis: the Query Rewriter degrades retrieval

Isolating the rewriter (same retriever, raw vs rewritten query, same qrels —
`python -m eval_harness.diagnose_rewriter`):

| | raw query | rewritten query |
|---|---:|---:|
| Mean nDCG@3 | **0.743** | 0.193 |
| Rewrite helped / hurt / tie | — | **0 / 7 / 3** |

The rewriter helped **0 of 10** queries and hurt **7**.

| Raw query | Rewrite | nDCG@3 raw → rw |
|---|---|---|
| `G6 Bullet unstable?` | `"Unstable behavior in G6 Bullet software: …"` | 0.879 → 0.242 |
| `Queue limitations - hard limit of 200` | `"Queue capacity threshold - does setting a…"` | 1.000 → 0.000 |
| `I can't run Ace-Step 1.5 XL on Comfy!?` | `"Are there any known issues or updates for…"` | 1.000 → 0.000 |

**Status: the measurement holds; the explanation was incomplete.** The original
reading — that the retriever's lexical matching mismatches the rewrite's formal
vocabulary — pointed at *ranking*. Fixing ranking alone recovered only part of
the loss (Finding 3), which is what exposed the real cause (Finding 4).

---

## Finding 3 — Fixing the ranking stage is not sufficient

The retriever's final ordering was a substring boost over the first four tokens
of the *rewritten* query — tokens which, after a rewrite, are filler. Replacing
it with a reranker scored against the **original** question (`rerank.py`, arms
selected by `MARAG_RERANK`) gives:

| Ranking arm | marag nDCG@3 | marag MRR | single_agent nDCG@3 | single_agent MRR |
|---|---:|---:|---:|---:|
| `none` (published behaviour) | 0.145 | 0.250 | 0.765 | 0.800 |
| `bm25` | 0.212 | 0.500 | 0.891 | 1.000 |
| `embed` (nomic-embed-text) | 0.188 | 0.625 | 0.984 | 1.000 |

marag's MRR improves monotonically with a better reranker, confirming ranking
*was* broken. But the gap does not close: the baseline improves at least as
much, because both systems share the reranker.

**Reading it:** if better ranking cannot close the gap, the missing documents
are not being mis-ranked. They are not there.

---

## Finding 4 — The loss is at fetch time: the rewrite *replaced* the user's query

Counting, per question, how many of the relevant documents the baseline
retrieved were present anywhere in marag's candidate pool (arm `bm25`):

> **22 of 23** relevant documents that single_agent retrieved were never
> fetched by marag at all.

Every live endpoint was being queried with the rewritten string only. The
documents that match what the user actually asked never entered the pool, so no
reranker could promote them. marag *did* find relevant documents the baseline
missed — the rewrite has real recall value — they were simply a different,
smaller set.

**Fix:** the rewrite augments the search rather than substituting for it. Both
phrasings are searched and the pools unioned, deduped by URL
(`RetrieverAgent.run`, `dedupe_docs`).

| Configuration | marag nDCG@3 | marag MRR | marag recall@5 |
|---|---:|---:|---:|
| `embed`, rewrite replaces query | 0.188 | 0.625 | 0.327 |
| `embed`, rewrite augments query | **0.765** | **1.000** | **0.933** |

---

## Finding 5 — With both fixes, multi-agent *matches* the baseline; it does not beat it

| System | nDCG@3 | recall@5 | faithfulness | latency |
|---|---:|---:|---:|---:|
| marag (`embed` + union fetch) | 0.765 | 0.933 | 0.705 | 23.1s |
| single_agent | 0.988 | 1.000 | 0.865 | 12.0s |

The nDCG@3 cell read 0.973 in an earlier draft of this file. That figure came
from `run_1788129818_237950e265eb`, made before the qrels cache key fix;
re-measured post-fix the same configuration scores 0.765, reproduced by
`run_1788135008_237950e265eb`. Do not reintroduce 0.973.

The retrieval difference sits well inside the confidence intervals. On this
set, the multi-agent pipeline costs roughly 2× the latency to reach parity.

**The claim that multi-agent decomposition improves retrieval is not supported
at n=10.** What is supported: the architecture had two real defects, both now
fixed and both regression-tested.

Note that `single_agent` is unaffected by the union-fetch change — it passes the
same string as original and rewritten, so the union collapses to one search.
The comparison is therefore a clean before/after for the multi-agent arm only.

---

## Finding 6 — At n=300 the parity holds, and the faithfulness gap is entirely format

`run_1788302755_7cdc5685d75a`: the whole 300-question benchmark, three arms,
synthesis model held at `llama3.1`, judge `ollama:llama3.1`, `embed` reranker.
Paired Wilcoxon against `single_agent`, Holm-corrected:

| Metric | marag | marag_llm | p_holm | W/T/L (marag) |
|---|---:|---:|---:|---:|
| nDCG@3 | +0.009 | +0.006 | 0.302 | 16/269/15 |
| nDCG@5 | +0.001 | -0.002 | 1.000 | 20/250/30 |
| Recall@5 | -0.011 | -0.013 | 0.502 | 12/267/21 |
| MRR | +0.006 | +0.006 | 0.667 | 4/290/6 |
| Faithfulness | **-0.196** | +0.002 | **<0.001** / 0.787 | 33/50/217 |

Three readings, in order of how much they change the argument:

**1. The parity result is now well-powered.** Every retrieval metric is null
across 300 questions. Findings 1-5 were measured at n=10 and the scaled tables
at n=100, where a reviewer could fairly answer "underpowered". That answer is no
longer available.

**2. Parity is not the benchmark failing to discriminate.** The obvious
objection to a wall of ties is that both arms retrieve the same documents, so
the test cannot see a difference that exists. It does not hold here: only
**33.3%** of questions (100 of 300) produce identical top-k lists, **65.0%**
retrieve materially different documents, and marag's mean candidate pool is
**23.1** against the baseline's **15.5**. The multi-agent pipeline fetches half
again as many candidates, and different ones, and no retrieval metric moves.
That is a stronger statement than parity: the extra retrieval is real and it is
inert.

**3. The answer-format confound is confirmed, not merely suspected.** The
template arm loses 0.196 of faithfulness on 217 of 300 questions at p<0.001. The
*same retrieval* rendered as prose by the same model is indistinguishable from
the baseline (+0.002, p=0.787). Whatever the template costs, it is not
grounding. Any future comparison that lets answer format vary between arms is
measuring formatting.

**Latency, correctly.** Do not use the run's mean latencies: questions 164 and
165 recorded 1,000-5,200 s on every arm because the host stalled. Medians are
20.3 s (marag), 26.3 s (marag_llm), 8.8 s (single_agent) — **2.3x** and
**3.0x** the baseline.

**What this run cannot do.** It is not a frozen comparison. It spans two
calendar days, so early and late questions saw different live corpora — which
leaves the *paired* comparison intact (the three arms run back-to-back within
each question, median 129 s for all three) but makes the run incomparable to any
other run. For byte-identical documents across arms, the frozen ladder replay
`run_1788422938_67177cd53aab` is the citable artifact; this run is its
large-sample corroboration on the coordination question.

---

## Finding 7 — At n=500 the parity holds, and the retrieval scores were mostly the question's own post

`run_1789429742_8fda4edb2d21`: `benchmark_500.json` (superset of the 300),
same three arms, same judge, reranker and seed. Paired vs `single_agent`,
Holm-corrected: nDCG@3 -0.010 (35/416/49, p 0.50), nDCG@5 -0.016 (p 0.16),
Recall@5 -0.030 (30/416/54, p 0.022), MRR -0.013 (p 0.31). Template
faithfulness -0.110 on 298 of 500 (p<0.001); the same retrieval as prose
+0.014 (p 0.031). Latency medians 56.9 / 60.6 / 26.7 s. Finding 6 replicates
at n=500, with the retrieval deltas now nominally negative.

**The absolute numbers, though, dropped by 0.34 on every arm** — nDCG@3
0.83 -> 0.48 on the same 300 questions with nothing in the pipeline changed.
That is not a systems effect, and chasing it found the reason the numbers were
high in the first place.

Reddit-mined questions are post titles. The corpus is the live Reddit feed. The
feed returns the post the title came from, its `doc_id` is `sha1(url)`, and the
judge marks it relevant — correctly, since it is the question. In the 300 run
the own post was in the pool for 247 of 262 Reddit questions and the *only*
relevant document for 140. Two weeks later the feed had aged past most of them
(171 of 445 in pool), and the score fell with it. `scripts/leak_report.py`
strikes the own post from ranking and qrels:

| Run | Arm | nDCG@3 | leak-free | own post in top-k |
|---|---|---:|---:|---:|
| n=300 | single_agent | 0.818 | 0.324 | 82% |
| n=500 | single_agent | 0.494 | 0.309 | 34% |
| frozen ladder n=100 | single_agent | 0.731 | 0.269 | 72% |
| frozen ladder n=100 | rewrite_only | 0.210 | 0.263 | 4% |

Leak-free, the runs agree (0.27-0.32 everywhere) and parity survives: n=500
-0.015 nDCG@3 (37/410/53, p_holm 0.43), n=300 -0.005 (p_holm 1.0).

**What changes.** The parity argument (Findings 5-6) is untouched — every
`marag*` and `single_agent*` arm retrieves the own post at the same rate, so
their paired differences never included it. Two other things do not survive:

- **The expansion-drift mechanism.** `rewrite_only` scored 0.21 against 0.73
  because a rewritten query no longer matches the post title verbatim, so the
  own post drops out (4% vs 72%). With it struck, `rewrite_only` is level with
  `single_agent` (nDCG@3 -0.006, 8/83/9; Recall@5 +0.032). "Rewriting destroys
  retrieval and union fetch repairs it" was, on this benchmark, "rewriting
  stops the lookup of the answer key and union fetch restores it." Findings 2
  and 4 were measured at n=10 on a different dataset and were not re-examined;
  treat them as affected until they are.
- **The grounding gain** (A1 -> A1g, PROVENANCE ladder) shrinks to +0.052
  nDCG@3 (13/80/7) and is not significant in the 21-test family the script
  tests; it needs its own family before it is quoted.

**What is still true.** Retrieval quality on this benchmark, honestly measured,
is nDCG@3 ~0.3 for every arm, and no arm of the multi-agent pipeline moves it.
The format confound (template vs prose) is a pure answer-side effect and is
unaffected.

**Fix.** `RetrieverAgent.exclude_urls` strikes the question's own `url` from
both tiers before ranking; `run_eval` sets it per question and records
`exclude_own_post` in `config.json` (default on, `--no-exclude-own-post` to
disable). Verified on a replay of the 500 snapshot: own post absent from pool
and top-k on both arm types. Every run before 2026-09-17 predates it; the table
above is a post-hoc correction, and a fresh run is the clean measurement.

---

## Finding 8 — Leak-free, every arm retrieves at nDCG@3 0.30 and the parity is exact

`run_1789703506_8fda4edb2d21`: the 500 questions rerun with the own post
excluded at fetch time, nothing else changed. Own post in 0 of 445 pools.

| Arm | nDCG@3 | Recall@5 | MRR | Faithfulness |
|---|---:|---:|---:|---:|
| marag (template) | 0.304 | 0.351 | 0.344 | 0.844 |
| marag_llm (prose) | 0.306 | 0.353 | 0.345 | 0.915 |
| single_agent | 0.301 | 0.366 | 0.344 | 0.910 |

Paired vs `single_agent`: nDCG@3 +0.003 (40/418/42, p_holm 1.0), Recall@5
-0.015 (p_holm 0.65), MRR +0.000 (28/434/38). Template faithfulness -0.066 on
283 of 500 (p<0.001); prose +0.005 (p 0.38). The post-hoc leak-free estimate
from Finding 7 (0.29-0.32) was right to within 0.01.

Three things this settles:

1. **The honest retrieval number for this system, and for its baseline, is
   about 0.30.** Every number above that in earlier runs was the question's
   own post. 273 of 500 questions have no judged-relevant document in any
   arm's pool.
2. **Parity is exact and not a benchmark artifact.** Only 113 of 500 top-k lists
   are identical across marag and single_agent; the multi-agent pool is 19.3
   against 12.8; and no metric moves by more than 0.015.
3. **The format effect is real but smaller than the leaky runs showed** —
   -0.066 here against -0.110 (leaky n=500) and -0.196 (n=300). Part of the
   earlier gap was the template rendering the own post's title verbatim.

**One number not to quote.** Template correctness +0.129 on the 72 GT
questions (16/54/2, p 0.002) is the judge scoring a "✅ VERIFIED" banner and
version strings around an answer that says the sources do not cover the
question. The prose arms say the same thing without the banner and score 0.
See PROVENANCE for an example; it is the judge-independence confound, not a
result.

---

## Confounds, and what has been done about them

| Confound | Status |
|---|---|
| **Answer format.** marag's answer is a template assembled by `EvaluatorAgent`; single_agent's is model prose. An LLM judge scoring these against each other measures format as much as content, so the faithfulness gap above is not yet evidence of anything. | Addressed: the `marag:<backend>:<model>` spec runs the same multi-agent retrieval with the answer synthesised by a named model through the shared prompt, reported as `marag_llm`. |
| **Synthesis model.** A bare `single_agent` synthesises with Mistral while marag uses Llama 3.1, though the paper reports Llama 3.1 throughout. Retrieval metrics are model-independent and unaffected; answer metrics were confounded. | Addressed by holding the model constant: `--generators marag,marag:ollama:llama3.1,single_agent:ollama:llama3.1`. |
| **Judge independence.** The judge (`ollama:llama3.1`) shares a model family with the system under test. | Open. Needs a stronger independent judge before publication. |
| **Qrels cache collisions.** The relevance cache was keyed by a question's *row position*, so datasets with overlapping ids read each other's labels. Runs made before this fix shared a cache with `table_50` runs. | Fixed (keys are now a hash of the question text); old-format entries are dropped rather than trusted. Headline numbers are being re-measured against a regenerated cache. |
| **Own-post leak.** Reddit-mined questions are post titles and the live feed returns the post itself; the judge grades it relevant. 72-83% of top-k lists in the cited runs contain the question's own post; absolute retrieval numbers above ~0.3 are mostly this. | Fixed for new runs: excluded from the candidate tiers before ranking, default on. Existing runs corrected post hoc (`scripts/leak_report.py`, Finding 7). |
| **Live APIs.** The document pool drifts, so a *given run* is reproducible via its saved qrels and per-query docs, but two runs days apart are not strictly comparable. | Open by design. A frozen snapshot is the fix if strict comparability is needed. |

---

## What this means for the paper

1. The +17.2% retrieval claim cannot stand as written — it rests on a bespoke
   metric that standard IR metrics contradict.
2. There is a genuine, publishable finding underneath: **query rewriting that
   replaces the user's query destroys retrieval, and the damage is at fetch
   time, not ranking time.** It is measured, mechanistically explained, and
   fixed. Prior work motivates rewriting for recall; this is a concrete failure
   mode and a cheap remedy.
3. The multi-agent justification needs different evidence than retrieval
   parity. The 300-question set has now been run (Finding 6) and does not
   supply it: retrieval is null at n=300 despite the arms retrieving materially
   different documents. The justification, if there is one, is not a retrieval
   -quality claim.

## Reproducing

```bash
# ranking ablation
for arm in none bm25 embed; do
  MARAG_RERANK=$arm python -m eval_harness.run_eval \
    --dataset validation_gt.json --generators marag,single_agent
done

# model held constant, answer-format confound removed
MARAG_RERANK=embed python -m eval_harness.run_eval \
  --dataset validation_gt.json \
  --generators marag,marag:ollama:llama3.1,single_agent:ollama:llama3.1 \
  --judge ollama:llama3.1

# the fetch-time diagnosis of Finding 4
python -m eval_harness.diagnose_rewriter
```
