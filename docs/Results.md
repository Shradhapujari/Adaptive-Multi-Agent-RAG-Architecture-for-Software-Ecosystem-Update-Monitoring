# Results and Data Sources

Lifted verbatim from the README so the landing page stays short. The numbers
here are historical readings; the authoritative chain is
[Evaluation and Findings](Evaluation-and-Findings.md) and
[`eval_harness/FINDINGS.md`](../eval_harness/FINDINGS.md), with run ids in
[`results/PROVENANCE.md`](../results/PROVENANCE.md).

---

## Data sources

**Verified (Tier 1):**
- Vendor registry — 6,578 entries
- Software release notes — 31,958 entries
- CVE / vulnerability advisories — 24,139 entries
- LLM / AI model releases — served from the same `/api/v/` collection, filtered by product type/name (OpenAI, Anthropic, Google, Meta, Mistral, DeepSeek, Qwen, xAI, Ollama). Browsable at <https://releasetrain.io/?type=llm>
- Apple Developer RSS, CISA KEV, CIRCL CVE Atom feed (dedicated Apple-side coverage)

**Community (Tier 2):**
- Reddit discussions — 208,466 posts
- Software update risk discussions — 2,637 posts
- Vendor-specific subreddit queries
- Google News

Verified and community sources are kept separate and weighted differently in the Evaluator's score.

> **On these counts.** They are the figures measured for the conference paper and
> are not re-measurable: the endpoints return query results without a collection
> total. The one that can be checked has moved a long way — `/api/c/names`, the
> product vocabulary vendor matching is built from, returned 14,223 names then and
> returns **1,348** today (checked 2026-09-23, full response, not paginated), with
> 364 subreddits. Treat every absolute size here as a reading of the service at a
> point in time. Evaluation runs are unaffected: each one records or replays its
> own corpus snapshot.

The lake behind these endpoints is a MongoDB store covering Reddit posts, Stack
Overflow posts, software release notes, CVE advisories, and LLM/AI model
releases. The retrieval layer currently consumes release notes, CVE, LLM
releases, and Reddit; **Stack Overflow is present in the lake but not yet wired
into the Retriever** — see `TODO` in the roadmap below.


## Evaluation

Two independent layers, so a result never rests on our own scoring alone.

**1. IR + judge metrics** (`eval_harness/`) — recall@k, nDCG@k, precision@k, MRR
against pooled, judge-labelled qrels, plus LLM-judged answer scores.

```bash
python -m eval_harness.run_eval --dataset table_50_questions.json --limit 50
```

**2. Established-benchmark scoring** (`eval_harness/benchmarks.py`) — deterministic
CRAG-style labelling of every answer as `correct` / `incorrect` / `missing`, with

```
accuracy = correct/n     hallucination = incorrect/n
missing  = missing/n     crag_score    = accuracy - hallucination
```

No LLM in the loop, so it is reproducible and independent of the model under
test. `crag_score` penalizes a confident wrong answer and merely declines to
reward an abstention — which is exactly the property our own Evaluator score
cannot express, and the reason a system that says *"the sources do not answer
this"* is scored strictly above one that guesses.

```bash
python -m eval_harness.run_eval --dataset crag_questions.jsonl --benchmark crag
```

Answer matching is version-aware: a prediction naming the right product but the
wrong version scores `incorrect`, not `correct`.

**3. Head-to-head comparison** (`eval_harness/compare.py`) — paired statistics
over a completed run, since every system answers the same questions:

```bash
python -m eval_harness.compare results/<run_id> --baseline single_agent \
    --metrics ndcg@5,recall@5,mrr,answer_score
```

Reports the mean paired difference with a bootstrap 95% CI, a paired t-test, a
non-parametric bootstrap p-value, Holm correction across the comparison family,
and win/tie/loss counts. Pure Python — no scipy or numpy needed. The t-test
agrees with `scipy.stats.ttest_rel` to 1e-8 (see `tests/test_compare.py`).

Treat a difference as real only when the CI excludes zero, the Holm-corrected
p-value holds, **and** the win/loss split points the same way. A large mean
difference with a near-even win/loss split means outliers are carrying it.

**4. Ranking ablation** — the reranking stage is selected by environment
variable, so which ranking signal the retriever uses is an experiment rather
than an assumption:

```bash
for arm in none bm25 embed; do
  MARAG_RERANK=$arm python -m eval_harness.run_eval \
      --dataset validation_gt.json --generators marag,single_agent
done
```

`none` reproduces the published behaviour and is kept deliberately as the
ablation arm. `bm25` is dependency-free and deterministic. `embed` uses Ollama
embeddings and degrades to `bm25` — reporting that it did so — rather than
silently measuring something other than what it claims.

### Larger benchmark

`data/benchmark_300.json` — 300 questions mined from the live releasetrain.io
endpoints, **60 per category** (releases / bugs / security / community /
general) across **24 ecosystems** (Apple, Android, Windows, four Linux
distros, browsers, containers, package managers, self-hosted apps, databases,
LLM releases). Rebuild or refresh with:

```bash
python build_multiecosystem_benchmark.py            # replays the cache
python build_multiecosystem_benchmark.py --refresh  # re-mines live
```

Two upstream data defects are handled rather than inherited: CVE rows label the
*index token* instead of the affected product (templating them naively
fabricates claims like *"Is iOS v4.2.0 vulnerable?"*), and some feed dates are
corrupt. Rows that cannot be attributed confidently are dropped, and every
question carries a `source` field so mined and templated items stay
distinguishable.

`data/benchmark_1000.json` (**1,000 questions, 200 per category, 24
ecosystems**) is built the same way, at larger scale. It has not been run
yet — it overlaps `benchmark_500` on 486/500 questions, so it isn't a fresh
sample, just more of the same distribution.

### Evaluation at scale

The 10-question ground-truth set is directional only. The 100-question
benchmark (`data/benchmark_100.json`, 21 ecosystems) is where the repaired
system was measured:

| Measure | Value |
|---|---|
| Baseline-relevant documents missing from the candidate pool | 96% → **12%** after the union fetch |
| nDCG@3, multi-agent vs single-agent (synthesis model held constant) | 0.859 vs 0.863 — parity |
| Faithfulness: template answer / prose answer / baseline prose | 0.700 / 0.926 / **0.931** |
| Mean latency per question, multi-agent vs baseline | ≈ 23 s vs ≈ 12 s |

### Frozen corpora

The live endpoints drift while a run is in progress, so any comparison that has
to be exact is replayed rather than re-fetched:

```bash
MARAG_CORPUS=record:data/corpus_snapshot_myrun python -m eval_harness.run_eval ...
MARAG_CORPUS=replay:data/corpus_snapshot_myrun python -m eval_harness.run_eval ...
```

Record once, replay for every arm. A warm replay against a shared snapshot can
backfill it, so give each ablation its own directory rather than reusing one.

### Arms and the ablation ladder

Arms are built to differ by **one** capability at a time — query rewriting,
union fetch, reranker, answer rendering — so a difference between two of them
has a single candidate cause. In particular `marag_llm` exists to remove the
answer-format confound: same multi-agent retrieval, but the answer is
synthesized through the baseline's own prompt with the same model.

A reimplementation of Self-RAG-style per-passage critiques and CRAG-style
correction over this retrieval ships in `eval_harness/selfreflective.py`
(`--generators selfreflective`), with the model held constant. **Its evaluation
run is incomplete and no results are reported from it.**

### Tests

```bash
python -m pytest tests/ -q      # 643 offline tests, no network required
```

Offline in the strict sense: clocks, fetch functions and model clients are all
injected, so the suite needs neither a network nor a particular date to pass.


---

## Results

### Standard IR metrics (n = 10 ground-truth set, judge `ollama:llama3.1`)

| System | nDCG@1 | nDCG@3 | MRR | Faithfulness |
|---|---:|---:|---:|---:|
| Single-agent baseline | **0.800** | **0.743** | **0.800** | **0.805** |
| Multi-agent, as published | 0.167 | 0.193 | 0.433 | 0.660 |

Localizing the loss — the same retrieval under three ranking arms, single
phrasing, then with the union fetch added:

| Configuration | nDCG@3 | MRR |
|---|---:|---:|
| substring boost (published behaviour), single phrasing | 0.145 | 0.250 |
| `bm25`, single phrasing | 0.212 | 0.500 |
| `embed`, single phrasing | 0.188 | 0.625 |
| `embed` + union fetch | **0.765** | **1.000** |

Rising MRR under stronger rerankers with a flat nDCG is the signature of a
*fetch* fault rather than a ranking one. Reranking came first in this project
and mattered least: adopt the union first.

### Retrieval quality by category (50 questions, the paper's own score)

> Kept for the record. This is the bespoke keyword-overlap score whose ordering
> the table above inverts.

| Category | Single-Agent | 4-Agent | Improvement |
|---|---:|---:|---:|
| Security | 0.630 | 0.750 | **+19.0%** |
| Bugs | 0.756 | 0.833 | +10.3% |
| Releases | 0.667 | 0.723 | +8.5% |
| Community | 0.730 | 0.850 | +16.4% |
| General | 0.600 | 0.750 | **+25.0%** |
| **Overall** | **0.680** | **0.798** | **+17.2%** |

*Paired t-test: t(49) = 2.32, p = 0.020.*

### Self-improvement over the evaluation run

| Tertile | Mean retrieval quality |
|---|---:|
| Q1–Q17 (early) | 0.756 |
| Q34–Q50 (late) | 0.826 |

*+9.3% improvement, t(16) = 2.18, p = 0.043, Cohen's d = 0.83.*

> ⚠️ This compares time-ordered tertiles against a **live corpus that drifts
> during the run**, so adaptation is not separable from drift. Mechanism sound,
> magnitude unestablished — it needs a frozen snapshot (record/replay above) or
> an interleaved design.

### Answer accuracy

On version-specific questions, the system correctly identified Linux v7.0.0 (April 13, 2026) and Firefox v149.0.1 (April 7, 2026) from the corresponding release sources. On a supplementary 10-question live evaluation: **4 fully correct, 6 partially correct, 0 unsupported version numbers or CVE identifiers generated.**

Raw per-question results are in `results/legacy/eval_50_results_v2.json` and the per-question results table. Ablation results are in `results/legacy/ablation_results.json`.

---

