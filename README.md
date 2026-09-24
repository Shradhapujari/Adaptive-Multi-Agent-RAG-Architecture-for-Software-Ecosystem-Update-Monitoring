# An Adaptive Multi-Agent RAG Architecture for Software Ecosystem Update Monitoring

> Multi-agent RAG system that answers software update questions — *"are there known Siri issues after iOS 26.4?"* — by integrating release notes, security advisories, and community discussions, with a self-improving retrieval memory that learns from its own outcomes. Runs locally on Llama 3.1 8B.

- **Live demo** — <https://software-update-questions.streamlit.app/> (public, no key required)
- **Paper** — *An Adaptive Multi-Agent RAG Architecture…*, AgenticSE '26 (ACM CAIS 2026), retargeted and submitted to **TOSEM**. [PDF](https://drive.google.com/file/d/1WssnrTSiUxtYd2wWdV5QUKbIcB2-iPLH/view?usp=sharing) · source in [`paper/`](paper/)
- **Authors** — Shradha Devendra Pujari, Dr. Solomon Berhe, University of the Pacific

---

## Read this first: the headline did not survive re-scoring

The paper reports **+17.2%** retrieval quality over a single-agent baseline. Re-scored with standard IR metrics instead of the paper's bespoke keyword-overlap score, **that result inverts** — and the cause was a real defect, not a metric artifact:

- The Query Rewriter's output **replaced** the user's wording at every live endpoint, so 22 of 23 relevant documents the baseline found were never fetched. Reranking cannot recover a document that was never retrieved.
- Making the rewrite **additive** (both phrasings searched, pools unioned) and ranking against the original question takes nDCG@3 from **0.188 → 0.765** in one step.
- That reaches **parity, not superiority**. At n = 300 every retrieval metric is null (nDCG@3 +0.009, *p* = 0.302), at roughly **2.3× latency**. A separate 0.23 "faithfulness deficit" turned out to be an answer-**format** confound and vanishes when the same retrieval is rendered as prose.
- A second defect — benchmark questions retrieving **their own source post** — inflated every absolute score before 2026-09-17. Fixed at fetch time (`exclude_own_post`); the clean n = 500 rerun scores nDCG@3 **0.30 on every arm**.

So the project's contribution is **a negative result and its remedy**, not an improvement claim. Full chain of measurements, confounds and superseded readings: [`eval_harness/FINDINGS.md`](eval_harness/FINDINGS.md); every number maps to a run id in [`results/PROVENANCE.md`](results/PROVENANCE.md).

What does hold: **zero hallucinated version numbers** across version-specific evaluation, and the whole system runs **fully locally** on Apple Silicon via Ollama, with 731 offline tests.

---

## Documentation

Everything long-form lives in [`docs/`](docs/) and renders on GitHub in place.

| Page | What it covers |
|---|---|
| [Overview](docs/Overview.md) | What the system is, and the negative result to read first |
| [Architecture](docs/Architecture.md) | The agents, the pipeline, the feedback loop, and the two agents added after the evaluation |
| [Evaluation and Findings](docs/Evaluation-and-Findings.md) | How the negative result was found, localized and repaired |
| [Results and Data Sources](docs/Results.md) | The result tables, the paper's own scores, and what the corpus is made of |
| [Running the System](docs/Running-the-System.md) | Setup, the demo, the CLI, and every environment variable that changes behaviour |
| [Benchmarks and Data](docs/Benchmarks-and-Data.md) | Question sets, live sources, rebuilding, and freezing the corpus |
| [Deployment](docs/Deployment.md) | The Streamlit deployment and what degrades without a model |
| [Roadmap and Open Questions](docs/Roadmap-and-Open-Questions.md) | Known limitations, what is unproven, and what would settle it |

---

## Architecture in one picture

Four specialized agents coordinated by an Orchestrator, with a retrieval-level feedback loop (plus a Temporal Grounder and an Answer Presenter added to the demo *after* the evaluation — see [Architecture](docs/Architecture.md)):

```
        User Question ──▶ Orchestrator ──┬──▶ Query Rewriter ──▶ Retriever ──▶ Evaluator
                                         │                                        │
                                         └──── retry if score < θ = 0.30 ◀────────┘
                                                        │
                                                        ▼
                                          Generated Answer (grounded + cited)
```

| Agent | Responsibility |
|---|---|
| **Orchestrator** | Coordinates the pipeline; manages retrieval retries when the Evaluator flags low quality |
| **Query Rewriter** | Normalizes user terminology to vendor wording; biased by the Self-Improvement Memory. Its output is *added* to the search, never substituted |
| **Retriever** | Vendor-aware search across a vendor registry and software subreddits; unions the rewritten and original phrasings, then reranks against the original question (`rerank.py`) |
| **Evaluator** | Deterministic 0.0–1.0 score over retrieval volume, release-note, community and CVE matches; retries below 0.30 |

**Self-Improvement Memory** — expansion terms that lead to successful retrieval accumulate score, failures decrement it. No human feedback, no labeled data, no retraining. Top learned terms after 50 queries: `vulnerability` (+2.20), `patch` (+1.58), `advisory` (+1.23). *(Measured against a drifting corpus — mechanism sound, magnitude unestablished; see [Results](docs/Results.md).)*

---

## Quickstart

Requires Python 3.11, [Ollama](https://ollama.com/download) with `llama3.1:8b`, and ~16 GB RAM (24 GB recommended).

```bash
git clone https://github.com/Shradhapujari/Adaptive-Multi-Agent-RAG-Architecture-for-Software-Ecosystem-Update-Monitoring.git
cd Adaptive-Multi-Agent-RAG-Architecture-for-Software-Ecosystem-Update-Monitoring
python3.11 -m venv venv311 && source venv311/bin/activate
pip install -r requirements.txt
ollama pull llama3.1:8b
streamlit run app_1.py        # the demo, on http://localhost:8501
```

```bash
python multiagent_rag_v3.py                # CLI, for execution traces
python -m eval_harness.run_eval --help     # reproduce the evaluation
pytest -q                                  # 731 offline tests, no network
```

Everything else — environment variables, the presenter model, the evaluation harness, the Claude Code launcher — is in [Running the System](docs/Running-the-System.md).

> ⚠️ The system reads **live** ecosystem APIs, so results shift as upstream data changes. For controlled comparison, snapshot the corpus (`corpus_snapshot.py`; see [Benchmarks and Data](docs/Benchmarks-and-Data.md)).

---

## Repository layout

**Start here**

| Path | What it is |
|---|---|
| `app_1.py` | Streamlit demo — the deployed app and the main way to interact with the system |
| `multiagent_rag_v3.py` | The four-agent system (pure Python; cleanest execution trace) |
| `eval_harness/generators.py` | Every evaluation arm, including the single-agent baseline (`SingleAgentGenerator`) |
| `eval_harness/` | IR + judge evaluation harness — generators, metrics, benchmarks, providers, [FINDINGS](eval_harness/FINDINGS.md) |
| `docs/` | All working documentation (table above) |

**Pipeline modules**

| Path | What it is |
|---|---|
| `temporal.py` | Temporal Grounder — resolves "today"/"last week" to absolute dates before retrieval |
| `fetch_union.py` | Multi-phrasing union fetch with window-aware ranking |
| `rerank.py` | Candidate reranking — `none` / `bm25` / `embed`, selected by `MARAG_RERANK` |
| `answer_agent.py` | Answer Presenter — prose answer with bracketed evidence |
| `guardrail.py`, `grounding.py`, `yesno.py` | Answer-side checks: invented versions, groundedness, yes/no verdicts |
| `vendor.py`, `intent.py`, `keywords.py`, `store.py` | Vendor detection, intent classification, query terms, retrieval store |
| `self_improving_agent.py` | Persistent term-weight memory |
| `corpus_snapshot.py` | Record/replay of the live corpus, for frozen comparisons |
| `marag_app.py` | One-line shim importing `app_1.py`; Streamlit Cloud is configured to serve this filename |

**Data, results, and the paper**

| Path | What's in it |
|---|---|
| `data/` | Evaluation question sets (`benchmark_300.json`, `benchmark_1000.json`, …) and supporting data |
| `results/` | Run outputs; [`results/PROVENANCE.md`](results/PROVENANCE.md) maps every reported number to a run id |
| `results/legacy/` | Pre-re-scoring result files from the conference paper (`eval_50_results_v2.json`, `ablation_results.json`, the accuracy runs) |
| `scripts/` | Reporting and phase scripts (`paper_figures.py`, `leak_report.py`, ablation phases) |
| `tests/` | Offline test suite |
| `paper/` | TOSEM manuscript source and figures — read [`paper/README.md`](paper/README.md) before editing the bibliography |
| `specs/`, `slides/`, `Poster/` | Specifications, talk slides, and the poster |

`app.py` is an earlier demo kept for reference; `app_1.py` is the one that ships.

---

## Tech stack

Llama 3.1 8B (primary) and Mistral 7B, local via [Ollama](https://ollama.com) at temperature 0 · HuggingFace BGE-Large, FAISS, ChromaDB · Streamlit · RLAIF-style retrieval-level feedback with a persistent term-weight memory · tested on Apple Silicon, 24 GB unified memory, Metal acceleration.

---

## Citation

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

Open to collaboration on larger-scale multi-ecosystem evaluation, learned reward models and adaptive thresholds, community-source credibility estimation, multilingual extensions, and head-to-head benchmarks against other multi-agent RAG systems. Open an issue or reach out.

**Contact:** Shradha Devendra Pujari — `s_pujari@u.pacific.edu` · [GitHub](https://github.com/Shradhapujari) · [LinkedIn](https://linkedin.com/in/shradha-pujari-98900)

**Advisor:** Dr. Solomon Berhe — `sberhe@pacific.edu`

Thanks to the maintainers of public software ecosystem data sources, communities, and open APIs that made this study possible.

## License

MIT — see [`LICENSE`](LICENSE).
