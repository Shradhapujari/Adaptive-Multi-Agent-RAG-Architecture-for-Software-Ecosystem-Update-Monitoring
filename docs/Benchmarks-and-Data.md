# Benchmarks and Data

## Question sets

| Set | n | Coverage | Use |
|---|---:|---|---|
| `validation_gt.json` | 10 | Hand-judged ground truth | Directional only; wide, overlapping CIs |
| `data/benchmark_100.json` | 100 | 21 ecosystems | The scaled evaluation reported in the paper |
| `data/benchmark_300.json` | 300 | 24 ecosystems, 60 per category | The headline evaluation; run in full (`run_1788302755_7cdc5685d75a`) |
| `table_50_questions.json` | 50 | Original evaluation | The +17.2% result |

Categories: releases · bugs · security · community · general.

Ecosystems in the 300-question set include Apple (iOS, macOS), Android, Windows,
four Linux distributions, browsers, containers, package managers, self-hosted
apps, databases and LLM releases.

## Building and refreshing

```bash
python build_multiecosystem_benchmark.py            # replays the cache — idempotent
python build_multiecosystem_benchmark.py --refresh  # re-mines the live endpoints
```

Two upstream data defects are handled rather than inherited:

- **CVE rows label the index token, not the affected product.** Templating them
  naively fabricates questions like *"Is iOS v4.2.0 vulnerable?"* Rows that
  cannot be attributed confidently are dropped.
- **Some feed dates are corrupt.** Dropped for the same reason.

Every question carries a `source` field, so mined and templated items stay
distinguishable in analysis.

## Live sources

> These counts are the figures measured for the conference paper and are not
> re-measurable: the endpoints return query results without a collection total.
> The one that can be checked has moved — `/api/c/names` returned 14,223 product
> names then and returns **1,348** today (checked 2026-09-23), with 364
> subreddits. Read every absolute size below as a reading of the service at a
> point in time; evaluation runs record or replay their own corpus snapshot and
> are unaffected.

**Verified (Tier 1)**

- Vendor registry — 6,578 entries
- Software release notes — 31,958 entries
- CVE / vulnerability advisories — 24,139 entries
- LLM / AI model releases — the same `/api/v/` collection filtered by product
  type and name (OpenAI, Anthropic, Google, Meta, Mistral, DeepSeek, Qwen, xAI,
  Ollama)
- Apple Developer RSS, CISA KEV, CIRCL CVE Atom feed

**Community (Tier 2)**

- Reddit discussions — 208,466 posts
- Software update risk discussions — 2,637 posts
- Vendor-specific subreddit queries
- Google News

Verified and community sources are kept separate and weighted differently in the
Evaluator's score.

The lake behind these endpoints is a MongoDB store covering Reddit posts, Stack
Overflow posts, release notes, CVE advisories and LLM releases. **Stack Overflow
is present in the lake but not yet wired into the Retriever.**

## An endpoint behaviour worth knowing before you design a query

`/api/v/` matches `q` against **product names**, not free text. Measured against
the live endpoint on 2026-08-31:

| `q` | releases returned |
|---|---:|
| `Linux` | 606 |
| `critical Linux updates` | 0 |
| `Any critical Linux updates on Aug 31, 2026 (2026-08-31)?` | 0 |

Any sentence-shaped phrasing — the user's, the rewriter's, or a date-grounded
one — retrieves nothing from it. This is why the demo also fetches an extracted
product term and unions the results, and why a date narrows results only *after*
the fetch. See [Architecture](Architecture.md).

## Freezing the corpus

The live sources drift while a run is in progress, so a comparison that must be
exact is replayed rather than re-fetched:

```bash
MARAG_CORPUS=record:data/corpus_snapshot_myrun python -m eval_harness.run_eval ...
MARAG_CORPUS=replay:data/corpus_snapshot_myrun python -m eval_harness.run_eval ...
```

Record once, then replay for every arm. Give each ablation **its own directory**:
a warm replay against a shared snapshot can backfill it, at which point the
snapshot is no longer the thing you recorded.
