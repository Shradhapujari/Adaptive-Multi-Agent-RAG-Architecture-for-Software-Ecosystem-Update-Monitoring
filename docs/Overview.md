# Adaptive Multi-Agent RAG for Software Ecosystem Update Monitoring

A multi-agent retrieval system that answers software-update questions — *"any
critical Linux updates today?"*, *"are there known Siri issues after iOS 26.4?"*
— by combining release notes, security advisories and community discussion, with
a retrieval-level feedback loop and a persistent term-weight memory.

**Live demo:** <https://software-update-questions.streamlit.app/> — public, no
API key required.

These pages are the working documentation. The [README][readme] is the front
door; `eval_harness/FINDINGS.md` is the evidence chain behind every number.

---

## Read this first: the result is a negative one

The published version of this system reported a **+17.2%** retrieval improvement
over a single-agent baseline, measured on a keyword-overlap quality score of our
own design. Re-scored with standard IR metrics over pooled relevance judgments,
the same system **lost** to the same baseline — nDCG@3 0.145 versus 0.765.

The disagreement was not a metric artifact. The Query Rewriter's output
*replaced* the user's wording at every retrieval endpoint, so 22 of the 23
relevant documents the baseline found were never fetched at all. Issuing both
phrasings and unioning the pools raises nDCG@3 from 0.188 to 0.765 in one step —
and brings the system to **parity** with the baseline, not superiority, at
roughly twice the latency.

[Evaluation and Findings](Evaluation-and-Findings.md) has the full chain, including
the readings that were superseded along the way and two numbers that should not
be reintroduced.

---

## Pages

| Page | What it covers |
|---|---|
| [Architecture](Architecture.md) | The agents, the pipeline, the feedback loop, and the two agents added after the evaluation |
| [Evaluation and Findings](Evaluation-and-Findings.md) | How the negative result was found, localized and repaired; every number and its provenance |
| [Running the System](Running-the-System.md) | Setup, the demo, the CLI, and every environment variable that changes behaviour |
| [Benchmarks and Data](Benchmarks-and-Data.md) | The question sets, the live sources, and how to rebuild or freeze them |
| [Deployment](Deployment.md) | The Streamlit deployment, what degrades without a model, and how to configure one |
| [Roadmap and Open Questions](Roadmap-and-Open-Questions.md) | What is unfinished, what is unproven, and what would settle it |

---

## Status

- **Paper** — retargeted from the AgenticSE '26 workshop version and submitted to
  **TOSEM**, special section on Human–AI Collaboration in Software Engineering
  (1 September 2026). Source in `paper/tosem_amara.tex`.
- **Tests** — 643 offline tests; no network, no fixed date required.
- **Open** — whether decomposition into agents is worth its cost is still
  unproven. At parity and twice the latency, that is the research question.

**Authors:** Shradha Devendra Pujari · Dr. Solomon Berhe — University of the
Pacific, Department of Computer Science.

[readme]: https://github.com/Shradhapujari/Adaptive-Multi-Agent-RAG-Architecture-for-Software-Ecosystem-Update-Monitoring#readme
