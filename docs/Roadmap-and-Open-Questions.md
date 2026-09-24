# Roadmap and Open Questions

## The open question

**Is decomposition into agents worth its cost?** With both retrieval defects
repaired and the synthesis model held constant, the multi-agent pipeline reaches
*parity* with a single-agent baseline at roughly twice the latency. Nothing in
the evidence so far justifies the extra machinery on retrieval grounds alone.

That is a research question, not a bug. Answering it needs either a larger
sample that separates the two systems, or a task property that the decomposition
demonstrably exploits and the baseline cannot.

## Unfinished measurement

- **The self-reflective baseline** (Self-RAG-style critiques, CRAG-style
  correction, model held constant) is implemented with 43 tests; its run stopped
  at 8 of 100 questions and **no results are reported from it**.
- **Self-improvement, measured cleanly.** The +9.3% figure compares time-ordered
  tertiles against a corpus that drifts during the run. A frozen snapshot
  (`MARAG_CORPUS=record:` then `replay:`) or an interleaved design would separate
  adaptation from drift.
- **An independent judge.** The judge and the systems under test currently share
  a model family. `--judge openai:gpt-4o` with an API key set removes that
  overlap.

## Done

- [x] Rerank against the original question rather than the rewrite (`rerank.py`)
- [x] Union fetch — both phrasings issued, pools unioned. This, not reranking,
      is what closed the retrieval defect
- [x] 300-question multi-ecosystem benchmark built (`data/benchmark_300.json`)
- [x] Corpus record/replay for frozen comparisons
- [x] Temporal grounding before retrieval, with window-aware ranking
      (`temporal.py`, `fetch_union.py`)
- [x] Cited prose answers in the demo (`answer_agent.py`)
- [x] 300-question run completed at 300/300 (`--resume`) — retrieval parity
      holds and the format confound is confirmed at full sample
- [x] Own-post retrieval leak fixed — Reddit-mined questions were retrieving
      their own source post (`exclude_own_post`, default since 2026-09-17)
- [x] Clean, leak-free n = 500 rerun (`run_1789703506`): nDCG@3 0.30 on every
      arm, parity exact

## Planned

- [ ] Embedding-based vendor matching, replacing the static alias dictionary —
      today, phrases like *"Synology NAS unreachable after upgrade"* lose the
      vendor to preprocessing
- [ ] Run the 1,000-question benchmark (`data/benchmark_1000.json`) — built,
      not yet run
- [ ] Learned reward model for the Evaluator, replacing heuristic scoring
- [ ] Adaptive threshold selection, replacing the hand-tuned retry threshold
- [ ] Wire Stack Overflow into the Retriever — it is in the data lake, unused
- [ ] Head-to-head comparison with Self-RAG, CRAG, MA-RAG, MAIN-RAG in this
      retrieval setting
- [ ] Cross-post agreement analysis for community-source credibility
- [ ] Multilingual evaluation
- [ ] Persistent cross-session memory with decay and capping, to prevent drift at
      scale

## Known limitations

- **Apple is structurally harder.** Apple does not publish to the same release
  database other vendors do. Dedicated Apple sources (Developer RSS, CISA KEV,
  CIRCL CVE) and iOS/Apple synonym expansion help; full coverage needs broader
  vendor onboarding.
- **Community-source reliability.** Reddit is the weakest link. Thresholds (≥10
  comments, ≥3 author replies, quality ≥ 0.3) and the verified/community split
  help, but one popular wrong post can still bias an answer.
- **Temporal precision is bounded by the endpoint.** Relative dates are resolved
  before retrieval, but `/api/v/` matches product names, so the window ranks
  results after the fetch rather than narrowing it.
- **Heuristic thresholds.** θ = 0.30 for retry and the Evaluator's scoring
  weights were tuned by hand; learned reward models and adaptive threshold
  selection are in Planned above.
- **Correctness is low across the board.** 0.296 / 0.367 / 0.326 — every arm is
  wrong more often than right. That is the difficulty of the domain, not a
  ranking of the systems.

## Collaboration

Open to collaborators on larger-scale evaluation, learned reward models,
community-source credibility, multilingual extensions, and head-to-head
benchmarks against other multi-agent RAG systems.

**Contact:** Shradha Devendra Pujari — `s_pujari@u.pacific.edu` ·
Dr. Solomon Berhe — `sberhe@pacific.edu`
