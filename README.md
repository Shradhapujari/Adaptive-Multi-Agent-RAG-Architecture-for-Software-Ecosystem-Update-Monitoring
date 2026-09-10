# An Adaptive Multi-Agent RAG Architecture for Software Ecosystem Update Monitoring

> Multi-agent RAG system that answers software update questions — *"are there known Siri issues after iOS 26.4?"* — by integrating release notes, security advisories, and community discussions, with a self-improving retrieval memory that learns from its own outcomes. Runs locally on Llama 3.1 8B.

📄 **Paper:** *An Adaptive Multi-Agent RAG Architecture for Software Ecosystem Update Monitoring* — presented at **AgenticSE '26** (Workshop on Agentic Software Engineering, ACM CAIS 2026), San Jose, CA, May 26–29, 2026. [[PDF](https://drive.google.com/file/d/1WssnrTSiUxtYd2wWdV5QUKbIcB2-iPLH/view?usp=sharing)]

👩‍💻 **Authors:** Shradha Devendra Pujari, Dr. Solomon Berhe — University of the Pacific, Department of Computer Science.

---

## TL;DR

- **+17.2%** retrieval quality over a single-agent RAG baseline on the paper's own retrieval-quality score (paired *t*-test, *t*(49) = 2.32, *p* = 0.020) — **but see the correction below**.
- **+9.3%** additional improvement from self-improvement memory across successive queries — no human feedback, no retraining (Cohen's *d* = 0.83) — **but measured against a drifting corpus; see the caveat under Results**.
- **Zero hallucinated version numbers** across version-specific evaluation; every claim traces back to a retrieved source.
- Runs **fully locally** on Apple Silicon (24 GB unified memory) via Ollama. No closed-model API calls.

> ### ⚠️ Correction — the headline above did not survive re-scoring
>
> Re-scored with standard IR metrics (nDCG@k / Recall@k / MRR over pooled judged
> relevance) rather than the paper's bespoke keyword-overlap score, the
> multi-agent pipeline **did not** beat the single-agent baseline — it lost
> badly (nDCG@3 **0.145 vs 0.765**, paired deficit 0.620, exact Wilcoxon
> *p* = 0.016, n = 10).
>
> The cause turned out to be a real defect, not a metric artifact: the Query
> Rewriter's output *replaced* the user's wording at every live endpoint, so
> **22 of the 23** relevant documents the baseline retrieved were never fetched
> at all. Reranking cannot recover a document that was never retrieved — which
> is why three successively stronger rerankers lifted MRR from 0.250 to 0.625
> while nDCG@3 stayed near 0.19.
>
> With the rewrite made additive (both phrasings searched, pools unioned) and
> ranking scored against the original question, nDCG@3 goes **0.188 → 0.765** in
> one step, and on the 100-question benchmark the share of the baseline's
> relevant documents missing from the candidate pool falls from **96% to 12%**.
>
> That reaches **parity, not superiority**: with both defects repaired and the
> synthesis model held constant, marag scores nDCG@3 **0.859 against the
> baseline's 0.863** (n = 100) at roughly twice the latency (23 s vs 12 s per
> question). Decomposition per se is not what produced the original +17.2%.
>
> An apparent 0.23 faithfulness deficit for the multi-agent system also proved
> to be an artifact of answer **format** — a structured template judged against
> fluent prose — and vanished when the same retrieval was synthesized through
> the baseline's own prompt (0.926 vs 0.931).
>
> **Both readings now hold at n = 300.** The whole 300-question benchmark has
> since been run (`run_1788302755_7cdc5685d75a`, three arms, synthesis model
> held constant). Every retrieval metric is null under a Holm-corrected paired
> Wilcoxon (nDCG@3 +0.009, *p* = 0.302; recall@5 −0.011, *p* = 0.502), and the
> parity is *not* the benchmark failing to discriminate: only **33%** of
> questions produce identical top-k lists, and marag's mean candidate pool is
> **23.1** against the baseline's **15.5**. The extra retrieval is real and it
> is inert. The format confound reproduces decisively — the template arm loses
> **0.196** faithfulness on 217 of 300 questions (*p* < 0.001) while the same
> retrieval rendered as prose is indistinguishable from the baseline (+0.002,
> *p* = 0.787). Median latency is 20.3 s (marag) against 8.8 s (baseline),
> **2.3×**; quote the medians, not the means — two questions recorded
> host-stall latencies of 1,000–5,200 s on every arm. This run is *not* a
> frozen comparison (it spans two calendar days); the frozen ladder replay
> `run_1788422938_67177cd53aab` is the citable artifact for byte-identical
> documents across arms.
>
> Full chain of measurements, confounds, and superseded readings:
> [`eval_harness/FINDINGS.md`](eval_harness/FINDINGS.md). Every number maps to a
> run id in [`results/PROVENANCE.md`](results/PROVENANCE.md).
>
> Two figures that were reported earlier and should **not** be reintroduced:
> nDCG@3 **0.973** (a pre-qrels-cache-keyfix artifact; post-fix and
> reproducibly, 0.765) and the scaled tables at n = 96 (a stalled run that has
> since completed at n = 100).

---

## Status

| | |
|---|---|
| **Live demo** | <https://software-update-questions.streamlit.app/> — public, no key required |
| **Paper** | Retargeted from the AgenticSE '26 workshop version and submitted to **TOSEM**, special section on Human–AI Collaboration in Software Engineering (1 September 2026). Source: `paper/tosem_amara.tex` |
| **Framing** | A negative result plus its remedy, not an improvement claim |
| **Tests** | 643 offline tests, no network required |

---

## Documentation

Working documentation lives in [`docs/`](docs/) and renders on GitHub in place —
kept in the repository rather than in a wiki so a documentation change is
reviewable in a pull request next to the code it describes.

| Page | What it covers |
|---|---|
| [Overview](docs/Overview.md) | What the system is, and the negative result to read first |
| [Architecture](docs/Architecture.md) | The agents, the pipeline, the feedback loop, and the two agents added after the evaluation |
| [Evaluation and Findings](docs/Evaluation-and-Findings.md) | How the negative result was found, localized and repaired; every number and its provenance |
| [Running the System](docs/Running-the-System.md) | Setup, the demo, the CLI, and every environment variable that changes behaviour |
| [Benchmarks and Data](docs/Benchmarks-and-Data.md) | Question sets, live sources, rebuilding, and freezing the corpus |
| [Deployment](docs/Deployment.md) | The Streamlit deployment and what degrades without a model |
| [Roadmap and Open Questions](docs/Roadmap-and-Open-Questions.md) | What is unfinished, what is unproven, and what would settle it |

Deeper than these: [`eval_harness/FINDINGS.md`](eval_harness/FINDINGS.md) for the
evidence chain, [`results/PROVENANCE.md`](results/PROVENANCE.md) for the run id
behind every reported number.

---

## Why this exists

Every time a software update ships — iOS, Linux, Firefox, a NAS firmware, whatever — the information you need is scattered. Release notes tell you the official version. CVE feeds tell you the security side. Reddit tells you what's actually breaking for real users. Ask a normal single-agent RAG system *"are there Siri issues after iOS 26.4?"* and you get a vague answer with no real evidence.

This system is built around the observation that single-agent RAG systems do query rewriting, retrieval, and evaluation all in one reasoning pass — which causes vocabulary mismatch (users say *"iPhone,"* release notes say *"iOS"*) and offers no feedback loop when retrieval fails. We decompose those tasks into four specialized agents and add a persistent memory of what worked.

---

## Architecture

Four specialized agents coordinated by an Orchestrator, connected through a retrieval-level feedback loop:

```
                  ┌──────────────────────┐
                  │   User Question      │
                  └──────────┬───────────┘
                             ▼
                  ┌──────────────────────┐
                  │  Orchestrator Agent  │
                  └──────────┬───────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌───────────────┐   ┌────────────────┐   ┌─────────────────┐
│ Query Rewriter│──▶│ Retriever      │──▶│ Evaluator       │
│   (Llama 3.1) │   │ (vendor-aware) │   │ (score 0.0–1.0) │
└───────────────┘   └────────────────┘   └─────────┬───────┘
        ▲                                          │
        │      retry if score < θ = 0.30           │
        └──────────────────────────────────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  Generated Answer    │
                  │  (grounded + cited)  │
                  └──────────────────────┘
```

| Agent | Responsibility |
|---|---|
| **Orchestrator** | Coordinates the pipeline; manages retrieval retries when the Evaluator flags low quality. |
| **Query Rewriter** | Normalizes user terminology to match how vendors actually write release notes. Pulls from Self-Improvement Memory to bias future queries toward learned-successful terms. |
| **Retriever** | Vendor-aware search across a registry of **14,223 vendors** and **628 software-related subreddits**. Restricts retrieval to vendor-specific sources when a vendor is detected. Searches **both** the rewritten and the original phrasing and unions the pools, then reranks the candidates against the user's original question (`rerank.py`). |
| **Evaluator** | Deterministic 0.0–1.0 score combining retrieval volume, release-note matches, community matches, and CVE matches. Triggers a retry if score < 0.30. |

### Self-Improvement Memory

Every query-expansion term that leads to a successful retrieval accumulates a positive score. Failed retrievals decrement scores. The Query Rewriter uses these scores to bias future queries. **No human feedback, no labeled data, no model retraining.**

Top learned terms after 50 queries (interpretable on inspection): `vulnerability` (+2.20), `patch` (+1.58), `advisory` (+1.23), `update` (+1.15), `kernel` (+0.98). These are exactly the terms a domain expert would tell you matter — the system found them on its own from retrieval outcomes.

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

Raw per-question results are in `eval_50_results_v2.json` and the per-question results table. Ablation results are in `ablation_results.json`.

---

## Tech stack

- **Models:** Llama 3.1 8B (primary), Mistral 7B (tested) — local via [Ollama](https://ollama.com), temperature 0
- **Frameworks:** LangChain, smolagents
- **Embeddings & search:** HuggingFace BGE-Large, FAISS, ChromaDB
- **Frontend:** Streamlit
- **Adaptation:** RLAIF-style retrieval-level feedback, persistent term-weight memory
- **Hardware tested:** Apple Silicon, 24 GB unified memory, Metal GPU acceleration

Multiple implementation variants are provided (Pure Python in `multiagent_rag_v3.py`, smolagents in `rag_smolagents_v2.py`) — they produce equivalent retrieval results on the evaluation dataset. The Pure Python implementation gives the cleanest execution trace.

---

## Getting started

### Requirements

- Python 3.11
- [Ollama](https://ollama.com/download) with `llama3.1:8b` pulled
- ~16 GB RAM minimum (24 GB recommended for comfortable inference)
- macOS/Linux (Apple Silicon recommended for Metal acceleration)

### Setup

```bash
# Clone
git clone https://github.com/Shradhapujari/Adaptive-Multi-Agent-RAG-Architecture-for-Software-Ecosystem-Update-Monitoring.git
cd Adaptive-Multi-Agent-RAG-Architecture-for-Software-Ecosystem-Update-Monitoring

# Virtual environment
python3.11 -m venv venv311
source venv311/bin/activate

# Dependencies
pip install -r requirements.txt

# Pull the model
ollama pull llama3.1:8b
```

### Run the Streamlit demo (recommended)

The deployed demo is live at <https://software-update-questions.streamlit.app/> (the
deploy target is `app_1.py`). To run it locally — ask a question and watch the agents
coordinate live:

```bash
streamlit run app_1.py
```

Then open the URL Streamlit prints (usually `http://localhost:8501`).
`marag_app.py` is a one-line shim that imports `app_1.py`, kept because the
Streamlit Cloud app is configured to serve that filename.

**Answer Presenter model.** With no model configured the final answer is composed
rule-based, which is what the deployed host does (Streamlit Community Cloud has no
Ollama and holds no API key). To have a model write it instead, set a provider spec —
in `.streamlit/secrets.toml` or the environment:

```bash
PRESENTER_MODEL=ollama:llama3.1 streamlit run app_1.py
```

Any spec `eval_harness/providers.py` understands works (`ollama:*`, `openai:*`,
`anthropic:*`). The UI always states which path produced the paragraph.

### Temporal grounding and cited answers

Two agents were added to the demo pipeline after the evaluation reported below, so
they are not part of any number in it:

- **Temporal Grounder** (`temporal.py`) — retrieval is similarity-based and no document
  contains the word *today*; it contains a date. So relative expressions are resolved to
  absolute ones before retrieval: *"Any critical Linux updates today?"* becomes *"Any
  critical Linux updates on Aug 31, 2026 (2026-08-31)?"*, in both the human and ISO
  forms so lexical and embedding scorers each have something to match. Handles
  today / yesterday / tomorrow, this-and-last week / month / year, "in the past N days",
  and "recently". Version ordinals (*latest*, *newest*) are deliberately left alone —
  they are ordinal over releases, not a date.

  Grounding the date into the *fetch* is what a naive version gets wrong: the release
  endpoint matches `q` against product names, so the dated phrasing returned 0 releases
  where the plain one returned 5. `fetch_union.py` therefore fetches every phrasing —
  plain, rewritten, dated, and the product term — unions the results, and uses the
  resolved window to *rank* rather than to filter, so a quiet day still returns
  something to read.

- **Answer Presenter** (`answer_agent.py`) — turns the retrieved documents into one
  readable paragraph with each claim cited in brackets, e.g. *"…resolves a kernel
  vulnerability [Release Notes - Linux v6.18.21, 2026-08-28]"*, replacing the bullet
  template the demo used to print. It reuses the harness's provider layer and its shared
  grounding instruction; `build_synthesis_prompt` itself is untouched, because the
  published answer-quality numbers were produced with that exact prompt.

### Run from the CLI

For scripted use or to inspect execution traces directly:

```bash
python multiagent_rag_v3.py
```

### Reproduce the evaluation

```bash
python evaluate_v3.py
```

> ⚠️ The system relies on live software ecosystem APIs. Results may shift over time as upstream data changes. For controlled comparison, snapshot the API responses (see *Reproducibility Notes* in the paper, §5.3).

---

## Repository layout

Key entry points:

| File | What it is |
|---|---|
| `app_1.py` | Streamlit demo — the deployed app, primary way to interact with the system |
| `temporal.py` | Temporal Grounder — resolves "today"/"last week" to absolute dates before retrieval |
| `fetch_union.py` | Multi-phrasing union fetch with window-aware ranking |
| `answer_agent.py` | Answer Presenter — prose answer with bracketed evidence |
| `marag_app.py` | Shim importing `app_1.py`, kept because the Cloud app is configured to serve this filename |
| `multiagent_rag_v3.py` | Main four-agent system (pure Python implementation) |
| `unified_agent_system.py` | Single-agent baseline used for comparison |
| `rag_smolagents_v2.py` | Equivalent implementation using HuggingFace smolagents |
| `rerank.py` | Candidate reranking for the Retriever — `none` / `bm25` / `embed` backends, selected by `MARAG_RERANK` |
| `build_multiecosystem_benchmark.py` | Builds `data/benchmark_300.json` from the live endpoints; idempotent, cached, `--refresh` to re-mine |
| `self_improving_agent.py` | Persistent term-weight memory for the Self-Improvement Memory |
| `evaluate_v3.py` | Evaluation harness (latest version) |
| `test_apis.py` | Standalone test of the underlying data-source APIs |
| `run_all.sh` | Shell script to run the full evaluation pipeline |
| `eval_harness/` | IR + judge evaluation harness — generators, metrics, benchmarks, providers, findings |
| `paper/` | TOSEM manuscript source (`tosem_amara.tex`) and its figures — see [`paper/README.md`](paper/README.md) before editing the bibliography |
| `docs/` | Working documentation — architecture, findings, running, benchmarks, deployment, roadmap |

Data and results:

| Path | What's in it |
|---|---|
| `data/` | Evaluation question sets and supporting data |
| `eval_50_results_v2.json` | Per-question scores for the 50-question evaluation |
| `ablation_results.json` | Ablation study results (per-component contribution) |
| `accuracy_test_results.json`, `accuracy_postfix_results.json` | Answer-accuracy evaluations |
| `results/PROVENANCE.md` | Run id behind every number reported in the paper |

Older / archived versions of the main scripts (`multiagent_rag.py`, `multiagent_rag_v2.py`, `evaluate.py`, `evaluate_v2.py`, `app.py`, etc.) are kept in the repo root for reference and reproducibility.

---

## Known limitations

We're explicit about these in the paper (§5) — they're real, and good directions to push on:

- **Apple is structurally harder.** Apple doesn't publish to the same release database other vendors do. We added dedicated Apple sources (Developer RSS, CISA KEV, CIRCL CVE) and iOS/Apple synonym expansion, but full coverage requires broader vendor onboarding.
- **Temporal queries — now handled, with a caveat.** Relative expressions are resolved to absolute dates before retrieval (`temporal.py`), and the resolved window ranks results rather than filtering them. The caveat is that the release endpoint matches `q` against *product names*, so a date in the query text cannot narrow it — the window is applied after the fetch, and an absolute-date question about a specific past day still depends on that day being inside what the endpoint returns.
- **Vendor extraction failures** on phrases like *"Synology NAS unreachable after upgrade"* — preprocessing strips domain terms. Future fix: embedding-based vendor matching over the full registry.
- **Community-source reliability.** Reddit is the weakest link. We require ≥10 comments, ≥3 author replies, quality ≥ 0.3, and separate verified from community sources — but a single popular wrong post can still bias an answer.
- **Evaluation size — addressed.** The original 50-question set was small; the benchmark now runs at n = 300 across 24 ecosystems. What remains open is not sample size but *frozen*-corpus comparability at that size: the n = 300 run records a live corpus rather than replaying one.
- **Heuristic thresholds** (θ = 0.30 for retry, the Evaluator scoring weights) were manually tuned. Learned reward models and adaptive threshold selection are in the roadmap.

---

## Roadmap

- [x] Larger multi-ecosystem benchmark — `data/benchmark_300.json` (300 questions, 24 ecosystems, 60 per category). Built **and run in full** (`run_1788302755_7cdc5685d75a`); see the correction above and `eval_harness/FINDINGS.md` Finding 6.
- [x] Rerank candidates against the original question rather than the rewrite — closed the retrieval defect described in the correction above.
- [x] Union fetch — issue both phrasings and union the candidate pools. This, not reranking, is what closed the defect.
- [x] Temporal grounding before retrieval (`temporal.py`) with window-aware ranking (`fetch_union.py`).
- [x] Cited prose answers in the demo (`answer_agent.py`), replacing the bullet template.
- [x] Finish the 300-question run — completed at 300/300 via `--resume`; retrieval parity holds and the format confound is confirmed at full sample.
- [ ] Report the self-reflective (Self-RAG / CRAG) baseline arm — implemented, run incomplete
- [ ] Measure self-improvement against a frozen corpus, so adaptation is separable from corpus drift
- [ ] Independent judge (`--judge openai:gpt-4o`) to remove the judge/system model-family overlap
- [ ] Embedding-based vendor matching (replace static alias dictionary)
- [ ] Learned reward model for the Evaluator (replace heuristic scoring)
- [ ] Adaptive threshold selection
- [ ] Head-to-head comparison with Self-RAG, CRAG, MA-RAG, MAIN-RAG (requires porting them to the software-ecosystem retrieval setting)
- [ ] Cross-post agreement analysis for community-source credibility
- [ ] Multilingual evaluation
- [ ] Persistent cross-session memory with decay/capping to prevent drift at scale

---

## Citation

If you build on this work, please cite:

```bibtex
@inproceedings{pujari2026adaptive,
  title     = {An Adaptive Multi-Agent RAG Architecture for Software Ecosystem Update Monitoring},
  author    = {Pujari, Shradha Devendra and Berhe, Solomon},
  booktitle = {Proceedings of the Workshop on Agentic Software Engineering (AgenticSE '26)},
  year      = {2026},
  address   = {San Jose, CA, USA},
  publisher = {ACM}
}
```

---

## Collaborate

I'm actively looking for collaborators on:

- Larger-scale evaluation across multiple software ecosystems
- Learned reward models / adaptive thresholds to replace the current heuristics
- Community-source credibility estimation
- Multilingual extensions
- Head-to-head benchmarks against other multi-agent RAG systems

If anything here connects to what you're working on — or you'd like to contribute — open an issue or reach out directly.

**Contact:** Shradha Devendra Pujari — `s_pujari@u.pacific.edu` · [GitHub @Shradhapujari](https://github.com/Shradhapujari) · [LinkedIn](https://linkedin.com/in/shradha-pujari-98900)

**Advisor:** Dr. Solomon Berhe — `sberhe@pacific.edu`

---

## Acknowledgments

Thanks to the maintainers of public software ecosystem data sources, online communities, and open APIs for making software-related information accessible for research. Their continued contributions enable the collection and evaluation of real-world software update questions that made this study possible.

---

## License

MIT — see [`LICENSE`](LICENSE) for details. You're free to use, modify, and build on this work; attribution is appreciated.
