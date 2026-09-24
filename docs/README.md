# Documentation

The working documentation for this project, linked from the
[README](../README.md#documentation) and rendered by GitHub in place.

| Page | What it covers |
|---|---|
| [Overview](Overview.md) | What the system is, and the negative result to read first |
| [Architecture](Architecture.md) | The agents, the pipeline, the feedback loop, and the two agents added after the evaluation |
| [Evaluation and Findings](Evaluation-and-Findings.md) | How the negative result was found, localized and repaired; every number and its provenance |
| [Results and Data Sources](Results.md) | The result tables, the paper's own scores, and what the corpus is made of |
| [Running the System](Running-the-System.md) | Setup, the demo, the CLI, and every environment variable that changes behaviour |
| [Benchmarks and Data](Benchmarks-and-Data.md) | Question sets, live sources, rebuilding, and freezing the corpus |
| [Deployment](Deployment.md) | The Streamlit deployment and what degrades without a model |
| [Roadmap and Open Questions](Roadmap-and-Open-Questions.md) | What is unfinished, what is unproven, and what would settle it |
| [Q&A Prep — 2026-09-24](QA-Prep-2026-09-24.md) | Anticipated review questions and the honest answer to each, as of that date |

These live in the repository rather than in the GitHub wiki so a documentation
change is reviewable in a pull request next to the code it describes. Links
between pages are ordinary relative Markdown links, so they resolve both on
GitHub and in a local editor.

If the wiki is ever populated instead, these files can be copied into
`<repo>.wiki.git` as-is — GitHub creates that repository only after the first
page is saved through the Wiki tab, and page links there are written without the
`.md` suffix.
