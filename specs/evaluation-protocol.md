# Evaluation Protocol

The measurement contract. Written before the headline runs so the analysis is not
chosen after seeing the numbers. If a decision here is changed after a run, say so in
the paper.

---

## 1. Datasets

| File | n | Composition | Use |
|---|---:|---|---|
| `validation_gt.json` | 10 | Hand-checked questions with ground truth | Diagnostic work only. Too small for a claim. |
| `table_50_questions.json` | 50 | Reddit-only, skewed (general 26 / releases 11 / bugs 9 / community 4) | Superseded. Do not carry a headline. |
| `data/benchmark_100.json` | 100 | Stratified subset of the 300: 20 per category × 5, round-robin over ecosystems, max 5 per ecosystem, deterministic (no RNG) | **Current working set.** |
| `data/benchmark_300.json` | 300 | Mined from live APIs, stratified over 24 ecosystems × 5 categories | The set that carries the final claims. |

`--limit N` is **not** a valid way to subsample either file: rows are ordered by
category, so `--limit 100` yields 60 `releases` + 40 `bugs` and zero `security`,
`community`, or `general`. `benchmark_100.json` exists because of that.

`benchmark_300` records provenance per question, and the paper must report the mix:

| `source` | Meaning |
|---|---|
| `mined_reddit_title` | Query is a real Reddit post title |
| `mined_release_record` | Query is phrased over a real live version record (real vendor, version, date) |
| `backfill_template` | **No live record existed for that (ecosystem, category) cell** |

Backfilled rows are templated, not observed. Report their share, and report headline
metrics both including and excluding them. A result that only holds on templated
questions is not a result.

**Measured mix.** `benchmark_300`: 249 `mined_reddit_title`, 51
`mined_release_record`, **0 `backfill_template`**. `benchmark_100`: 98 / 2 / 0. No
row in either file is templated, so T8 is closed by the data rather than merely
declared — but the 100-set's release-record share is small (2 of 100), which is
itself worth stating.

## 2. Relevance judgments (qrels)

Graded 0 / 1 / 2 by an LLM judge over `(question, document)` pairs.

- **Key**: `sha1(normalized question text)[:12] + ":" + doc_id`. Keying by dataset row
  position let `benchmark_300` question 3 read `validation_gt` question 3's label.
  Old-format entries are dropped at load with a printed count, never trusted.
- **Cache**: `results/qrels_cache.json`, shared across runs. Judgments are stable —
  0 of 60 shared labels changed across three consecutive runs — so reuse is a saving,
  not a confound.
- **Per-run record**: `results/<run_id>/qrels.json` holds the judgments that scored
  *that* run, as `{query_id: {doc_id: grade}}`. Distinct from the accumulating cache.

### Pooling bias — state this in the paper

Only documents some system retrieved are ever judged. Consequences:

- `recall@k`'s denominator is "relevant documents inside this run's pool", not
  "relevant documents in the corpus". On `validation_gt` that denominator is 1–3
  documents while the accumulated cache holds 2–10 for the same questions.
- `nDCG@k`'s IDCG comes from the same pool, so a system cannot be penalised for
  documents no arm retrieved.
- Both are valid for a **paired within-run** comparison, where every arm shares one
  pool. They are **not** comparable across runs, and not comparable to published
  numbers computed against a fixed judged corpus.

With `--judge-pool` the judged set widens from what systems *returned* to what they
*considered*, which makes pool recall real. Without it, `pool_recall` is a
tautological 1.0 and the harness reports `None` instead.

## 3. Metrics

**Retrieval** (`eval_harness/metrics.py`), over deduplicated ranked `doc_id` lists:
`recall@k`, `precision@k`, `nDCG@k` (graded gains, log2 discount), `MRR`, for
k ∈ {1, 3, 5}. Plus **pool recall** = |gold ∩ pool| / |gold|, the ceiling any reranker
could reach on that fetch.

**Answer** (LLM-judged): faithfulness, answer relevance, correctness. Plus the
system's own `self_quality` (RLAIF), reported as a system output, never as a metric.

**Benchmark mode**: deterministic CRAG-style correct / incorrect / missing labelling,
independent of our Evaluator and of the LLM judge.

**Cost**: wall-clock latency per question, and call counts by stage.

### The unit of observation is the question, not the document

Documents cluster within questions (top_k = 4 from one pool). A proportion test over
documents treats 4 correlated observations as 4 independent ones and reports a
p-value smaller than the truth. Aggregate to a per-question score first, then test
across questions. Where a document-level test is reported, report the design effect
alongside it.

## 4. Arms

| Arm | Varies | Held fixed |
|---|---|---|
| **Ranking** | `MARAG_RERANK` ∈ {`none`, `bm25`, `embed`} | corpus, dataset, judge, models, fetch mode |
| **Fetch** | rewrite replaces vs augments the search | corpus, dataset, judge, models, ranking backend |
| **System** | `marag` vs `marag_llm` vs `single_agent` | corpus, dataset, judge, synthesis model |
| **Judge** | `ollama:llama3.1` vs an independent judge | everything else |
| **Rules** | `MARAG_RULES` ∈ {`off`, `on`} — whether `AGENT_RULES.md` is prepended to every prompt | corpus (recorded once per arm), dataset, judge, models, `MARAG_RERANK=embed` |

`marag_llm` exists to remove the answer-format confound: the multi-agent arm's own
answer is a template assembled by `EvaluatorAgent`, the baseline's is model prose, and
an LLM judge scoring those against each other measures format as much as content.
`marag_llm` runs the same retrieval with the answer synthesised through the shared
prompt by the same model as the baseline. When answer metrics are compared, hold the
model constant:

```
--generators marag,marag:ollama:llama3.1,single_agent:ollama:llama3.1
```

The **Rules** arm is exploratory: it was added on 2026-09-10, after the other arms
were pre-registered, so §6's reporting rule for post-hoc comparisons applies to it.
It differs from the ranking arms in one way that matters for the corpus: the rules
reach `multiagent_rag_v3.call_llama`, hence the query rewriter, so the two arms ask
the corpus different questions. `scripts/phase_rules_ablation.sh` records once per
arm before replaying, and both replays must report `frozen=true`. For `marag` the
rules therefore move retrieval as well as the answer — its answer comparison is
sound, its IR metrics are not a controlled contrast. `single_agent` does not use
the rewriter and is the clean cell. Default is `off`: `run_eval` forces it before
any generator is built, because the rules reached the harness's rewriter silently
from `756b889` until `8a51eb8`, and no published number was produced with them.

## 5. What makes a run admissible

A run may carry a claim only if all of the following hold. Check them from
`config.json`, not from memory.

- [ ] `corpus.mode == "replay"` and `corpus.frozen == true` (zero corpus-host misses).
- [ ] `rerank_spec` matches the intended arm, and `rerank_degraded == false` unless
      degradation is the thing being reported.
- [ ] `judge_active == true`.
- [ ] `dataset_hash` matches the dataset the claim is about.
- [ ] `n_questions` matches the power analysis in §6.
- [ ] Every arm in a comparison replayed the **same** snapshot directory.
- [ ] The run postdates the fetch fix (`a1c717c`) and the qrels-key fix (`46ad7d0`).

Runs failing any line are diagnostic material, not evidence. The three-arm sweep of
2026-08-30 15:17–15:36 fails the last two and must not be quoted.

## 6. Statistical plan

Fixed in advance: α = 0.05, power = 0.80, two-sided. Three ranking arms give three
pairwise comparisons, so Bonferroni α = 0.0167 for that family.

Required questions per arm to detect an absolute difference in a proportion around
0.40, at top_k = 4 (ICC = 0.3 → design effect 1.9):

| Target effect | α | documents/arm | questions/arm, ICC=0 | questions/arm, ICC=0.3 |
|---|---|---:|---:|---:|
| +0.025 | 0.05 | 6,086 | 1,522 | 2,891 |
| +0.025 | 0.0167 | 8,114 | 2,029 | **3,855** |
| +0.10 | 0.05 | 388 | 97 | 185 |
| +0.10 | 0.0167 | 517 | 130 | **246** |

Minimum detectable effect at a given number of questions, same assumptions:

| n questions | α = 0.05 | Bonferroni α = 0.0167 |
|---:|---:|---:|
| 10 | +0.423 | +0.488 |
| **100** | +0.134 | **+0.154** |
| 246 | +0.085 | +0.098 |
| 300 | +0.077 | +0.089 |

**Declared deviation.** The working runs use `benchmark_100`, whose true MDE is
**+0.154**, not the +0.10 pre-registered below. A non-significant arm difference in
a 100-question run therefore means "not detectable at n=100" and does **not** rule
out a real effect of +0.10. Say this in the limitations, and do not upgrade a
100-question null into a claim of no effect. The 300-question run is what restores
the pre-registered +0.10.

**Consequence, decided in advance:** an effect of +0.025 is out of reach — at ~22 s per
question it is more than a day of compute per arm. The pre-registered minimum
detectable effect is therefore **+0.10 absolute**, which `benchmark_300` covers with
300 ≥ 246. An arm difference below +0.10 will be reported as "not detectable at this
sample size", not as a null result and not as a trend.

Reporting rules:

- Every point estimate carries a 95 % CI (`mean_ci` in `metrics.py`).
- Report effect size (Cohen's h for proportions) next to every p-value.
- No stopping early on a good-looking intermediate result. The dataset size is fixed
  before the run.
- Any comparison added after seeing the data is labelled exploratory.

## 7. Reference commands

```bash
# 0. record the corpus once (use the arm that makes the most calls)
MARAG_RERANK=embed ./venv311/bin/python -m eval_harness.run_eval \
  --dataset data/benchmark_300.json --generators marag,single_agent \
  --judge ollama:llama3.1 --judge-pool --corpus record:data/corpus_snapshot_b300

# 1. ranking ablation, every arm on the identical frozen corpus
for arm in none bm25 embed; do
  MARAG_RERANK=$arm ./venv311/bin/python -m eval_harness.run_eval \
    --dataset data/benchmark_300.json --generators marag,single_agent \
    --judge ollama:llama3.1 --judge-pool --corpus replay:data/corpus_snapshot_b300
done

# 2. answer-format confound removed, synthesis model held constant
MARAG_RERANK=embed ./venv311/bin/python -m eval_harness.run_eval \
  --dataset data/benchmark_300.json \
  --generators marag,marag:ollama:llama3.1,single_agent:ollama:llama3.1 \
  --judge ollama:llama3.1 --corpus replay:data/corpus_snapshot_b300

# 3. the fetch-time diagnosis behind C1
./venv311/bin/python -m eval_harness.diagnose_rewriter
```

## 8. Threats to validity

Each is either closed with a mechanism or declared open. Nothing here is dropped
silently.

| # | Threat | Status |
|---|---|---|
| T1 | **Corpus drift.** Live sources change between runs; 10/10 questions returned different document sets across consecutive runs. | **Closed** by `corpus_snapshot.py` record/replay, enforced by the `frozen` flag. Must actually be used by the headline run. |
| T2 | **Judge independence.** `ollama:llama3.1` judges a pipeline whose rewriter is llama3.1. | **Open.** Closing action: re-judge the headline run with an independent judge and report both. |
| T3 | **Pooling bias.** Only retrieved documents are judged; recall denominators are pool-relative. | **Declared**, quantified in §2, and mitigated for the fetch question by `--judge-pool`. |
| T4 | **Sample size.** n=10 for every current number. | **Open** until `benchmark_300` carries the headline. MDE fixed at +0.10 in §6. |
| T5 | **Clustering.** 4 documents per question are not 4 independent observations. | **Closed** by aggregating to per-question scores before testing; design effect reported where a document-level test appears. |
| T6 | **Answer-format confound.** Template vs prose answers judged against each other. | **Closed** by the `marag_llm` arm; must be the arm quoted for answer metrics. |
| T7 | **Synthesis-model confound.** Bare `single_agent` uses mistral, marag uses llama3.1. | **Closed** by holding the model constant in the §7 step 2 command. |
| T8 | **Benchmark backfill.** Templated rather than observed questions. | **Closed by the data** — measured 0 `backfill_template` rows in both files. Still report the source mix. |
| T12 | **Underpowered working set.** `benchmark_100` supports MDE +0.154, not the pre-registered +0.10. | **Declared** in §6. Closed only by the 300-question run. |
| T9 | **Reranker degradation.** `embed` can silently fall back to BM25. | **Closed** — `rerank_degraded` is recorded per run and per row. |
| T10 | **Arm provenance.** A sweep could not previously prove which arm produced a directory. | **Closed** — `rerank_spec` is read off the live reranker into `config.json`. |
| T11 | **Single machine, single seed.** | **Declared.** Report the machine; run ≥3 seeds where the metric is stochastic. |
