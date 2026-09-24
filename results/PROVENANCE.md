# Provenance — which run produced which number

Every number in `paper/tosem_amara.tex` and the run that produced it. The paper
claims the ablation arms are released; this file is what makes that claim
checkable.

Two caveats apply throughout and are stated in the paper:

1. **Live sources.** Every run retrieves from live APIs whose contents change.
   A given run is reproducible from its own saved `qrels.json` and
   `per_query.jsonl`; two runs made hours apart are not strictly paired.
2. **The qrels cache key fix.** Relevance judgments were originally cached by a
   question's row position, so datasets with overlapping ids could read each
   other's labels. Runs made before the fix are marked **pre-fix** below and
   should not be mixed with post-fix runs in a controlled comparison. A run
   directory containing `qrels_cache_snapshot.json` is post-fix.

## Table 1 — the metric inversion

| Row | Run | Cache |
|---|---|---|
| Bespoke score, both systems (n=50) | conference version; not re-run here | — |
| nDCG@1 / nDCG@3 / MRR, both systems (n=10) | `run_1788128243_237950e265eb` | pre-fix |

## Table 3 — ranking and retrieval ablation

Panel (a), single-phrasing retrieval, n=10:

| Ranking function | Run | Cache |
|---|---|---|
| Substring boost | `run_1788128243_237950e265eb` | pre-fix |
| Okapi BM25 | `run_1788128704_237950e265eb` | pre-fix |
| Embedding cosine | `run_1788129232_237950e265eb` | pre-fix |

Panel (b), union retrieval:

| Configuration | Run | Cache | n |
|---|---|---|---|
| Substring boost, rewritten query | `run_1788147304_237950e265eb` | post-fix | 10 |
| Substring boost, original question | `run_1788148035_237950e265eb` | post-fix | 9 |
| Embedding cosine, original question | `run_1788133873_237950e265eb` | post-fix | 10 |

The embedding row was originally reported as nDCG@3 0.973 from
`run_1788129818_237950e265eb` (pre-fix). Re-measured post-fix it is 0.765,
reproduced independently by `run_1788135008_237950e265eb`. The paper reports
0.765.

**Panel (b) is not a fully controlled ablation.** Its three rows come from
separate runs against live sources, and the reranker and the ranked phrasing vary
across them. The panel (a) → (b) contrast is large enough to survive that; the
within-panel (b) differences are not, and the paper says so.

## `tab:scaled-retrieval` and `tab:scaled-answer` — the scaled evaluation

**Re-measured 2026-09-03 on a frozen corpus. Cite the replay run.**

| Run | Corpus | Role |
|---|---|---|
| `run_1788467936_6a8e9993db65` | `record:results/corpus_scaled_20260902`, `frozen=false` | recording pass; **latency column comes from here** |
| `run_1788473855_6a8e9993db65` | `replay:` same dir, `frozen=true`, 6,348 hits, 0 corpus misses | **the citable run** |
| `run_1788139377_6a8e9993db65` | live, unfrozen | **superseded** — see below |

Dataset `data/benchmark_300.json`, `--limit 100 --stratify category,ecosystem`
(hash `6a8e9993db65`, reproduced exactly under seed 42); generators `marag`,
`marag:ollama:llama3.1`, `single_agent:ollama:llama3.1`; judge
`ollama:llama3.1`; `top_k=4`; `MARAG_RERANK=embed`, `MARAG_RANK_QUERY=original`.

The earlier run is superseded rather than merely repeated. It executed before
the release-fetch repair (`ed206a2`), where truncation ran ahead of the ranking
function and shipped releases were unreachable for any product with an active
CVE feed. nDCG@3 moves 0.859 / 0.859 / 0.863 to 0.922 / 0.922 / 0.924 — about
six points that the defect, not the architecture, was costing. Both arms shared
that retriever, so the ordering never changed; only the level did.

Two figures in the paper are recomputed on the frozen run and no longer match
the superseded one: fetch-time loss is **13 of 172 (7.6%)**, previously 19 of
158 (12.0%); and the two multi-agent arms' top-k sets *and* candidate pools now
coincide on **100 of 100** questions as ordered lists and as sets, with no
question excluded, where the live run agreed on top-k but on pools only on 88
of the 93 questions that had one. That residual was endpoint variability
between two arms querying live, which is what freezing removes.

Latency is taken from the recording pass. A replay reads documents and model
responses from cache and its timings measure nothing.

### Superseded detail

All cells previously from `run_1788139377_6a8e9993db65`, n=100, post-fix.

- Dataset: `data/benchmark_300.json`, `--limit 100 --stratify category,ecosystem`
- Generators: `marag`, `marag:ollama:llama3.1` (reported as `marag_llm`),
  `single_agent:ollama:llama3.1` — synthesis model held constant
- Reranker: `MARAG_RERANK=embed`; ranked phrasing: original question
- Judge: `ollama:llama3.1`

This run stalled at question 98 and was later completed. Numbers reported in an
earlier draft as n=96 were hand-computed from `per_query.jsonl` mid-run; the
paper now uses the completed n=100 artifact.

## `tab:gt-run` — the ground-truth sample

**Re-measured 2026-09-03 on a frozen corpus. Cite the replay run.**

| Run | Corpus | Role |
|---|---|---|
| `run_1788474232_67177cd53aab` | `record:results/corpus_gt_20260902`, `frozen=false` | recording pass; latency column |
| `run_1788479105_67177cd53aab` | `replay:` same dir, `frozen=true`, 6,227 hits, 0 corpus misses | **the citable run** |
| `run_1788160859_67177cd53aab` | live, unfrozen, pre-repair | superseded |

Dataset `data/benchmark_100.json`, no limit; generators, judge and knobs as for
the scaled evaluation above.

The point this sample makes is unchanged by the repair, which is why it is
worth reporting: its nominal ordering on retrieval is still the reverse of
`tab:scaled-retrieval` (`marag` 0.795 against `single_agent` 0.773 here,
against 0.922 and 0.924 there), with intervals overlapping throughout. Two
independent samples disagreeing on sign is the evidence that no difference is
being measured, and freezing the corpus removes drift as the explanation for
the disagreement.

### Superseded detail

All cells previously from `run_1788160859_67177cd53aab`, n=100, post-fix.

- Dataset: `data/benchmark_100.json` (28 reference answers, selected to prefer
  ground-truth records within each ecosystem-by-category cell)
- Generators and reranker as above; judge `ollama:llama3.1`
- This run shared the machine with other work, so its absolute latencies are
  inflated; only the within-run ratio is meaningful.

This is an independent sample of the same comparison. Its nominal ordering on
retrieval, faithfulness and correctness is the reverse of Tables 4 and 5, with
overlapping intervals throughout — which is the paper's evidence that no
difference is being measured.

## Fetch-time loss

Both figures are the same measurement: the share of the baseline's
judge-labelled relevant documents absent from the multi-agent **candidate pool**
(not its top-k).

| Figure | Set | Run |
|---|---|---|
| 22 of 23 (96%) | 10 ground-truth questions | `run_1788128704_237950e265eb` |
| 13 of 172 (7.6%) | 100-question benchmark subset, frozen | `run_1788473855_6a8e9993db65` |
| 19 of 158 (12.0%) | same subset, pre-repair and unfrozen | `run_1788139377_6a8e9993db65` (superseded) |

A top-k version of the second figure gives 23 of 158 (14.6%). An earlier draft
reported that number against the pool-based 96%, which mixed definitions.

## The full 300-question run

`run_1788302755_7cdc5685d75a`, n=300, post-fix. The largest sample in the
project, and the run that settles open item 1 of the handoff.

- Dataset: `data/benchmark_300.json` (the whole file, no `--limit`); seed 42; `top_k=4`
- Generators: `marag`, `marag:ollama:llama3.1` (reported as `marag_llm`),
  `single_agent:ollama:llama3.1` — synthesis model held constant
- Reranker: `embed:nomic-embed-text`; judge: `ollama:llama3.1`
- Corpus: `record:data/corpus_snapshot_b300_full_0901`, 13,283 responses
  recorded (7,899 files, 84 MB), `frozen=false`

Paired Wilcoxon against `single_agent`, Holm-corrected across the family:

| Metric | Arm | Mean delta | W/T/L | p_holm |
|---|---|---:|---:|---:|
| nDCG@3 | marag | +0.009 | 16/269/15 | 0.302 |
| nDCG@3 | marag_llm | +0.006 | 16/269/15 | 0.302 |
| nDCG@5 | marag | +0.001 | 20/250/30 | 1.000 |
| Recall@5 | marag | -0.011 | 12/267/21 | 0.502 |
| MRR | marag | +0.006 | 4/290/6 | 0.667 |
| Faithfulness | marag (template) | **-0.196** | 33/50/217 | **<0.001** |
| Faithfulness | marag_llm (prose) | +0.002 | 20/262/18 | 0.787 |
| Answer relevance | marag | +0.011 | 22/259/19 | 0.477 |

Three things this run establishes that the earlier n=100 tables could not:

1. **Retrieval parity is now well-powered.** Every retrieval metric is null at
   n=300 with tie counts of 250-290 out of 300. The n=100 tables showed the same
   thing with intervals wide enough that a reader could dismiss them as
   underpowered; this sample removes that objection.
2. **The parity is not an artifact of the arms retrieving the same documents.**
   Only 100 of 300 questions (33.3%) produce identical top-k document lists
   across `marag` and `single_agent`; 195 (65.0%) retrieve materially different
   documents, and `marag`'s mean candidate pool is 23.1 against the baseline's
   15.5. The multi-agent pipeline fetches half again as many candidates and
   different ones, and it does not move any retrieval metric.
3. **The answer-format confound reproduces decisively.** The template arm loses
   0.196 of faithfulness across 217 of 300 questions at p<0.001, while the same
   retrieval rendered as prose is indistinguishable from the baseline
   (+0.002, p=0.787). At n=100 this was a three-number table; here it is a
   well-powered paired test.

**Two cautions on this artifact.**

*Latency.* Do not quote the mean latencies from `report.md` (55.6 / 50.4 /
22.6 s). Questions 164 and 165 recorded 1,000-5,200 s on every arm — the host
stalled, not the systems. Medians are 20.3 / 26.3 / 8.8 s, giving **2.3x** for
`marag` and **3.0x** for `marag_llm` over the baseline. Use the medians.

*Pairing.* The run spans two calendar days (paused at 93/300, resumed), so
questions early and late in the file saw different live corpora. This does not
break the paired comparison: within a question the three arms execute
back-to-back (median 129 s for all three), so both systems see the same corpus
for the same question. It does mean the run is not comparable to any other run,
and the recorded snapshot is a record of what was fetched, not a frozen corpus
(`frozen=false` — record mode never sets it true).

For a frozen, byte-identical-documents comparison, cite the ladder below
instead. This run is the large-sample corroboration of its coordination result,
not a replacement for it.

## The full 500-question run, and the own-post leak it exposed

`run_1789429742_8fda4edb2d21`, n=500, `data/benchmark_500.json` (a strict
superset of `benchmark_300.json`: all 300 `source_id`s plus 200 new; ids are
renumbered, so join the two files by `source_id`, never by `id`). Same
configuration as the 300 run: seed 42, `top_k=4`, generators `marag`,
`marag:ollama:llama3.1`, `single_agent:ollama:llama3.1`, reranker
`embed:nomic-embed-text`, judge `ollama:llama3.1`, rules off. Corpus
`record:data/corpus_snapshot_b500_full_0914`, 19,707 responses, `frozen=false`.
Launched 2026-09-14, died at 181/500 with the session that started it, resumed
2026-09-16 with `--resume`, finished 2026-09-17. Same pairing caveat as the 300
run: three arms back-to-back per question, so the paired comparison holds and
nothing else is comparable across runs.

Paired against `single_agent`, Holm-corrected (`comparison.md` in the run dir):

| Metric | Arm | Mean delta | W/T/L | p_holm |
|---|---|---:|---:|---:|
| nDCG@3 | marag | -0.010 | 35/416/49 | 0.497 |
| nDCG@5 | marag | -0.016 | 42/388/70 | 0.164 |
| Recall@5 | marag | -0.030 | 30/416/54 | 0.022 |
| MRR | marag | -0.013 | 17/449/34 | 0.306 |
| Faithfulness | marag (template) | **-0.110** | 43/159/298 | **<0.001** |
| Faithfulness | marag_llm (prose) | +0.014 | 66/383/51 | 0.031 |
| Answer relevance | marag_llm | +0.013 | 40/435/25 | 0.012 |
| Correctness (n=65) | marag | -0.005 | 11/43/11 | 0.935 |

Latency medians 56.9 / 60.6 / 26.7 s (2.1x, 2.3x); the means are inflated by
two questions above 10,000 s on every arm and, as with the 300 run, must not
be quoted. Top-k lists are identical across `marag` and `single_agent` on 125 of
500; `marag`'s mean pool is 19.8 against 13.2.

**The absolute retrieval numbers fell by 0.34 for every arm** (nDCG@3 0.827 ->
0.483 for `marag`; the same for the baseline), on the *same 300 questions*, with
the judge, reranker and code paths unchanged. The cause is not in the systems:

Every Reddit-mined question is a real post title and carries that post's `url`.
The live Reddit endpoints return the post itself, its `doc_id` is `sha1(url)`,
and the judge grades the post the question was lifted from as relevant. In the
300 run the question's own post was in the candidate pool for **247 of 262**
Reddit questions, judged relevant for 232, and was the *only* relevant document
for 140. By 14-17 September the feed had aged past most of those posts: own
post in pool for 171 of 445, only-relevant for 82. `scripts/leak_report.py`
recomputes the metrics with the own post struck from ranking and qrels:

| Run | Arm | nDCG@3 | nDCG@3 no own post | own post in top-k |
|---|---|---:|---:|---:|
| n=300 | marag | 0.827 | 0.319 | 82.7% |
| n=300 | single_agent | 0.818 | 0.324 | 82.3% |
| n=500 | marag | 0.483 | 0.294 | 33.8% |
| n=500 | single_agent | 0.494 | 0.309 | 34.2% |
| n=100 frozen ladder | single_agent | 0.731 | 0.269 | 72.0% |
| n=100 frozen ladder | rewrite_only | 0.210 | 0.263 | 4.0% |

Leak-free, the two large runs agree with each other (0.29-0.32 on every arm),
and the parity result stands: n=500 paired deltas vs `single_agent` are
-0.015 nDCG@3 (37/410/53, p_holm 0.43), -0.032 Recall@5 (p_holm 0.12), -0.016
MRR (p_holm 0.41); n=300 is the same picture (all p_holm >= 0.83).

Three consequences for numbers already cited:

1. **Every absolute retrieval number in this file above ~0.3 is mostly the
   leak.** The direction of paired comparisons between arms that retrieve the
   own post at the same rate (all `marag*` vs `single_agent*` arms, 72-83% each)
   is unaffected; the magnitudes are not interpretable as retrieval quality.
2. **The `rewrite_only` drop is the leak.** Rewriting the query stops it
   matching the post title verbatim, so the own post falls out of top-k (4% vs
   72%). With the own post struck, `rewrite_only` is level with `single_agent`
   on the frozen ladder (nDCG@3 -0.006, 8/83/9; Recall@5 +0.032). The "rewriting
   damages retrieval, union fetch repairs it" reading of the ladder does not
   survive; what union fetch repairs is the ability to look up the answer key.
   The n=10 Table 1/Table 3 numbers were not re-examined here (different
   dataset and qrels format) and should be assumed affected until they are.
3. **The grounding gain shrinks.** A1 -> A1g leak-free is +0.052 nDCG@3
   (13/80/7), not significant after Holm across the 21-test family the script
   runs; it needs re-testing in its own family before it is quoted.

Since 2026-09-17 the harness strikes the question's own `url` from every arm's
candidate tiers before ranking (`RetrieverAgent.exclude_urls`, set per question
by `run_eval`; `config.json` records `exclude_own_post`). It is on by default;
`--no-exclude-own-post` restores the old behaviour. Every run above predates it
and is not leak-free by construction; the table is a post-hoc correction.

## The clean 500-question run (own post excluded)

`run_1789703506_8fda4edb2d21` — same dataset, arms, judge, reranker, seed and
`top_k` as the leaky run above; the only change is `exclude_own_post: true`
(commit `d80305a`). Corpus `record:data/corpus_snapshot_b500_clean_0917`,
29,020 responses, `frozen=false`. Ran 2026-09-17 19:45 to 2026-09-19 without
interruption. `scripts/leak_report.py` confirms the question's own post is in
**0 of 445** Reddit questions' pools. The first leak-free measurement.

| Arm | nDCG@3 | nDCG@5 | Recall@5 | MRR | Faithfulness | Ans. rel. |
|---|---:|---:|---:|---:|---:|---:|
| marag (template) | 0.304 | 0.316 | 0.351 | 0.344 | 0.844 | 0.923 |
| marag_llm (prose) | 0.306 | 0.318 | 0.353 | 0.345 | 0.915 | 0.968 |
| single_agent | 0.301 | 0.323 | 0.366 | 0.344 | 0.910 | 0.966 |

Paired vs `single_agent`, Holm across the family:

| Metric | Arm | Mean delta | W/T/L | p_holm |
|---|---|---:|---:|---:|
| nDCG@3 | marag | +0.003 | 40/418/42 | 1.000 |
| nDCG@5 | marag | -0.007 | 45/387/68 | 1.000 |
| Recall@5 | marag | -0.015 | 39/408/53 | 0.654 |
| MRR | marag | +0.000 | 28/434/38 | 1.000 |
| Faithfulness | marag (template) | **-0.066** | 28/189/283 | **<0.001** |
| Faithfulness | marag_llm (prose) | +0.005 | 79/364/57 | 0.376 |
| Answer relevance | marag (template) | -0.043 | 34/225/241 | <0.001 |
| Correctness (n=72) | marag (template) | +0.129 | 16/54/2 | 0.002 |

The leak-free column of the earlier runs predicted 0.29-0.32 nDCG@3 for every
arm; measured, 0.301-0.306. Parity is exact: every retrieval delta is within
0.015 with 387-434 ties out of 500, and the multi-agent pool is still half again
larger (19.3 vs 12.8) for it. 273 of 500 questions have no judged-relevant
document in any arm's pool — on this benchmark, the corpus does not contain an
answer for most questions, and no arm changes that.

Latency medians 53.9 / 53.6 / 26.4 s (2.0x, 2.0x); means carry 6/5/1 stalls
above 600 s and are not quotable.

**Do not quote the correctness row.** The template arm's +0.129 on the 72
ground-truth questions is a judge artifact: the winning answers say the sources
do not cover the question (e.g. "does not appear to be directly related") under
a "✅ VERIFIED from live releasetrain.io APIs" banner and a list of version
strings, and `llama3.1` scores that 0.7 against a ground truth the answer does
not state. The prose arms, which say plainly they could not find it, score 0.
This is the judge-independence confound (FINDINGS.md) showing up as a
false positive; it needs a stronger judge before it means anything.

## The tier-prior finding (Finding 9)

`run_1789892227_8fda4edb2d21` — the clean-run configuration replayed under
`strict:data/corpus_snapshot_b500_clean_0917` with `--dump-pools` and the judge
off, 2026-09-20. Pools only; its `per_query.jsonl` carries no scores. Pools
are 20-30% larger than the original run's (the snapshot backfilled under
replay), so bench numbers compare rankers with each other, not with the clean
run. `rerank_bench.jsonl` and `rerank_bench_llm_embed.jsonl` in that dir are
the per-(query, ranker) rows; the judgments they added (3,142 + 16) are in
`qrels_cache.json`.

| Ranker (marag_llm / single_agent) | nDCG@3 | Recall@5 | MRR |
|---|---:|---:|---:|
| tiered:embed (as run) | 0.250 / 0.248 | 0.197 / 0.208 | 0.353 / 0.349 |
| flat:bm25 | 0.322 / 0.315 | 0.318 / 0.313 | 0.429 / 0.430 |
| flat:rrf | 0.410 / 0.400 | 0.386 / 0.381 | 0.502 / 0.512 |
| flat:embed | 0.458 / 0.452 | 0.418 / 0.412 | 0.543 / 0.544 |
| flat:llm12 over rrf (qwen2.5:7b-instruct) | 0.453 / 0.447 | 0.414 / 0.404 | 0.539 / 0.542 |
| flat:llm20@embed (marag only, second pass) | 0.489 | 0.441 | 0.562 |

`run_1789951801_3b855840be3a` (`rank_tiers: tiered`) and
`run_1789951917_3b855840be3a` (`rank_tiers: flat`) — 100 questions of
`benchmark_500.json`, `--stratify category --seed 42`, arms
`marag:ollama:llama3.1,single_agent:ollama:llama3.1`, judge `ollama:llama3.1`,
same strict snapshot, 2026-09-20. Paired flat - tiered: nDCG@3 +0.227 both
arms (CIs above zero), faithfulness -0.02 / -0.03, answer relevance
-0.03 / -0.03. Latency is not quotable from either: replay served nearly every
call.

## The ablation ladder (grounding vs coordination)

Two runs, same 100 questions, same eight arms. **Cite the frozen one.**

| Run | Corpus | n | Cache | Role |
|---|---|---|---|---|
| `run_1788319745_67177cd53aab` | `record:results/corpus_ladder_20260901`, `frozen=false`, 12,680 responses recorded | 100 | post-fix | recording pass, live fetches |
| `run_1788422938_67177cd53aab` | `replay:results/corpus_ladder_20260901`, `frozen=true`, 12,344 hits / 240 misses, **0 on document hosts** | 100 | post-fix | **the citable run** |

- Dataset: `data/benchmark_100.json`; seed 42; `top_k=4`
- Reranker: `embed:nomic-embed-text`; judge: `ollama:qwen2.5:7b-instruct`
- Generators: `raw:ollama:mistral`, `single_agent:ollama:mistral`,
  `single_agent_grounded:ollama:mistral`, `rewrite_only:ollama:mistral`,
  `marag:ollama:mistral`, `marag_retry:ollama:mistral`, `marag`,
  `single_agent_template` — synthesis model held at `mistral` on every arm that
  makes an LLM call, and the judge wrote none of the answers.

Only the replay run served every arm byte-identical documents; the recording
run fetched live and its arms hit the feeds hours apart, which is the same
not-strictly-paired caveat as item 1 above. The replay reproduces the recording
run's conclusions to three decimals, so the pair is reported together and the
frozen run is the one quoted.

Headline results, paired Wilcoxon on per-question differences (frozen run):

| Comparison | Metric | Mean delta | Better / worse | p |
|---|---|---|---|---|
| A1 -> A1g (grounding) | nDCG@3 | +0.049 | 14 / 5 | 0.0070 |
| A1 -> A1g | Recall@3 | +0.051 | 12 / 4 | 0.0035 |
| A1 -> A1g | nDCG@5 | +0.042 | 15 / 9 | 0.0268 |
| A1 -> A3 (coordination) | nDCG@5 | +0.018 | 9 / 10 | 0.8721 |
| A1 -> A3 | Recall@5 | +0.007 | 6 / 8 | 1.0000 |
| A1g vs A3 | nDCG@5 | -0.024 | 12 / 20 | 0.2172 |

Four things this run establishes that the numbers alone do not say:

1. **`mrr` and `ndcg@1` are null for A1 -> A1g**, not significant, despite
   nominal p of 0.0431 and 0.1088. Those come from 5 and 3 non-zero pairs, where
   the smallest two-sided p the signed-rank test can attain is 0.0625 and 0.25 —
   the normal approximation reported a value below the attainable floor. Same
   failure mode as the n=10 inversion in Table 1.
2. **Rung A4 measures nothing on this benchmark.** `marag_llm_retry` returned
   identical documents *and* identical answers to `marag_llm` on 100 of 100
   questions. Retry fires below self-quality 0.15; the minimum observed was
   0.300. Report it as a rung that had no opportunity to act, not as a rung with
   no effect.
3. **Rung A2 is the reason A3 looks like progress.** `rewrite_only` scores
   nDCG@5 0.231 against the baseline's 0.742; `marag_llm` adds union fetch and
   returns to 0.761, level with the baseline. Union fetch repairs the damage
   rewriting does rather than improving on single-agent retrieval, and omitting
   A2 from the ladder hides that.
4. **Template rendering costs about 0.10 faithfulness**, in both cells of the
   2x2 and with the tightest intervals in the run: `marag_llm` -> `marag`
   -0.095 (51 worse / 19 better) and `single_agent` ->
   `single_agent_template` -0.102 (52 worse / 13 better), both p < 0.0001. Any
   template-versus-prose comparison measures this before it measures retrieval.

Two limits on what these runs can be compared against:

- **Retrieval numbers collected before commit `ed206a2` (2026-09-01) are void**
  for any product with an active CVE feed. `fetch_vendor_releases` cut its
  candidate list to `limit` before the `canonical_score` sort ran, so shipped
  releases were unreachable — measured, 0 shipped releases in 40 retrieved
  documents for `q=linux`. Both arms shared that retriever, so the direction of
  earlier comparisons likely holds while the absolute values do not.
- **The A1g arm was corrected mid-measurement.** Its first version retrieved on
  the bare product name and scored *below* the baseline it exists to improve;
  the version measured here retrieves on products plus content terms
  (commit `08cbcc2`). A partial run of the earlier arm exists at
  `run_1788315588_67177cd53aab` (11 questions) and is not reportable.

Latency is not comparable across arms in either run: the recording pass ran
overnight on a laptop that entered clamshell sleep, so its wall-clock times
include suspend, and the replay pass reports sub-second times because documents
and model responses both come from cache.

## The rules ablation (does `AGENT_RULES.md` change anything?)

The app prepends `AGENT_RULES.md` to every prompt; the harness did not, so
the file had never been measured. `scripts/phase_rules_ablation.sh` records
a corpus once and replays it for both settings, so `MARAG_RULES` is the only
thing that differs. Run 2026-09-14, `table_50_questions.json`, n=50, arms
`marag` and `single_agent`, judge `ollama:llama3.1`, `--judge-pool`,
`MARAG_RERANK=embed` pinned by the script. Every config records
`rules_active` and `rules_sha` (`239a9527…`), so no run's setting is
inferred from its position in a log.

**Cite the replays.** The record passes are `frozen=false` by construction.

| Run | Rules | Corpus | Role |
|---|---|---|---|
| `run_1789442318_417cbdda5764` | off | `replay:results/snap_rules_50`, `frozen=true`, 2,005 hits, 0 corpus misses | **citable** |
| `run_1789443187_417cbdda5764` | on | same, 2,075 hits, 0 corpus misses | **citable** |
| `run_1789426665_417cbdda5764` | off | `record:results/snap_rules_50` | recording pass |
| `run_1789433706_417cbdda5764` | on | same | recording pass |

Paired Wilcoxon on per-question differences, rules off → on:

| Arm | Metric | off → on | Better / worse | p |
|---|---|---|---|---|
| `single_agent` | faithfulness | 0.808 → **0.883** | 16 / 7 | **0.011** |
| `single_agent` | nDCG@5 | 0.506 → 0.502 | 3 / 6 | 0.515 |
| `marag` | faithfulness | 0.725 → 0.759 | 13 / 9 | 0.158 |
| `marag` | nDCG@5 | 0.488 → 0.519 | 10 / 6 | 0.326 |

Retrieval is null on every metric for both arms, as it should be: the rules
enter the prompt, and the prompt does not touch retrieval. The effect is on
faithfulness, and it is clear for the single-agent arm and borderline for the
multi-agent one — whose template rendering already constrains what the
answer can say, leaving less for the rules to fix.

**Independently replicated.** A second session ran the identical sweep the
same afternoon into its own snapshot, `corpus_rules_20260914`, same dataset
hash and same `rules_sha`. Its frozen replays are `run_1789446039` (off) and
`run_1789446712` (on):

| Arm | Metric | Δ (this sweep) | Δ (replication) |
|---|---|---|---|
| `single_agent` | faithfulness | +0.075, p=0.011 | +0.071, p=0.019 |
| `marag` | faithfulness | +0.034, p=0.158 | +0.051, p=0.045 |
| `single_agent` | nDCG@5 | −0.004, p=0.515 | +0.000, p=0.779 |
| `marag` | nDCG@5 | +0.031, p=0.326 | +0.034, p=0.148 |

Two frozen corpora, recorded independently, agree on sign and size. The
single-agent faithfulness gain is the finding; the multi-agent one crosses
0.05 in one sweep and not the other, and should be reported as borderline.

Two things not to read into these numbers:

- `mrr` and `pool_recall` on `marag` move on 3 non-zero pairs, where the
  smallest attainable p is 0.25. Null, not evidence.
- The script uses the bare specs: `single_agent` synthesises through
  `mistral` (`generators.py`, `build_generators`), and `marag` is the
  template arm, which makes no synthesis call. The judge is `llama3.1`.
  Every pass shares that configuration, so the off/on comparison is
  unaffected — but the absolute faithfulness values are not comparable to
  `tab:scaled-answer`, which held synthesis at `llama3.1` on both arms, and
  the `marag` row here carries the template-rendering penalty the 2×2
  quantified at about 0.10.

The 20-question pilot that preceded this, and the earlier 50-question attempt
that ran 16 questions in five and a half hours, both lived in session
scratchpads and are gone. This sweep was run from the checkout so its
snapshot and runs sit under `results/`.

## Reproducing an arm

```bash
MARAG_RERANK=none|bm25|embed \
MARAG_RANK_QUERY=original|rewritten \
python -m eval_harness.run_eval \
    --dataset validation_gt.json --generators marag,single_agent \
    --judge ollama:llama3.1
```

`MARAG_RERANK=none` with `MARAG_RANK_QUERY=rewritten` is the configuration the
conference version shipped.
