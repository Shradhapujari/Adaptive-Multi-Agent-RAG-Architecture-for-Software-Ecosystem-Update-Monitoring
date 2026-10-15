# Benchmarking section — draft, 2026-10-15

Scope note, kept here rather than in the paper text: of the four systems
originally planned for this comparison, two produced real rankings today —
local Ollama (`llama3.1:latest`, parametric knowledge only) and our pipeline
(live ReleaseTrain pull, `scripts/component_stability_ranking.py`). ChatGPT
(`openai:gpt-4o-mini`) and Gemini (`gemini-2.5-flash`) were not run: no
`OPENAI_API_KEY` / `GEMINI_API_KEY` is set on this machine. The harness for
both (`scripts/rank_components_llm.py`) is already wired to the same prompt
and the same strict parser, so adding those two columns later is a matter of
adding keys to `.env` and re-running — not re-deriving the method. Raw model
output and the generating script are in
[`docs/llm_update_order_comparison_2026-10-15.md`](llm_update_order_comparison_2026-10-15.md).

Everything below is drawn only from that run. Component set is fixed at 30
(`component_stability_ranking.COMPONENTS`); note it does not include
BIOS/microcode or glibc specifically — "core low-level" below is represented
by `linux` as the kernel proxy, the lowest-level item actually in the
evaluated set.

## Comparative ranking

| # | Component | Ollama (`llama3.1`) rank | Pipeline rank |
|---:|---|---:|---:|
| 1 | wordpress | 14 | 1 |
| 2 | linux | 30 | 2 |
| 3 | gitlab | 4 | 3 |
| 4 | windows | 22 | 4 |
| 5 | android | 25 | 5 |
| 6 | kubernetes | 7 | 6 |
| 7 | postgresql | 1 | 7 |
| 8 | macos | 23 | 8 |
| 9 | docker | 6 | 9 |
| 10 | git | 5 | 10 |
| 11 | mysql | 2 | 11 |
| 12 | rust | 10 | 12 |
| 13 | chrome | 16 | 13 |
| 14 | ios | 24 | 14 |
| 15 | ubuntu | 28 | 15 |
| 16 | firefox | 17 | 16 |
| 17 | debian | 27 | 17 |
| 18 | arch | 29 | 18 |
| 19 | grafana | 15 | 19 |
| 20 | fedora | 26 | 20 |
| 21 | safari | 18 | 21 |
| 22 | edge | 21 | 22 |
| 23 | brave | 19 | 23 |
| 24 | opera | 20 | 24 |
| 25 | node | 8 | 25 |
| 26 | python | 9 | 26 |
| 27 | home assistant | 12 | 27 |
| 28 | nextcloud | 13 | 28 |
| 29 | mongodb | 3 | 29 |
| 30 | neovim | 11 | 30 |

Sorted by pipeline rank. **Rank 1 = most urgent to update.**

**Pairwise correlation (n = 30):** Spearman's ρ = −0.050, Kendall's τ =
−0.039. Treating ρ as a test statistic, t(28) = −0.26, p ≈ 0.79 — not
distinguishable from zero. One run, one baseline model; this is not a power
analysis, just a note against over-reading a single ρ.

## Discussion

The baseline and the pipeline disagree not at the margins but at the
extremes, and in opposite directions. `linux` sits at pipeline rank 2 — second
only to `wordpress` on severity-weighted advisory volume over the trailing 90
days — while Ollama places it dead last at rank 30. The same inversion runs
the other way for the database layer: Ollama ranks `postgresql`, `mysql`, and
`mongodb` 1st, 2nd, and 3rd, treating "database" as an inherently
update-urgent category, while the live feed currently shows `mongodb` at rank
29 and `postgresql` at 7 — there is simply little advisory activity against
these specific products in the current window. Read together, these are not
two systems that weight the same evidence differently; the baseline is not
conditioning on evidence about *this* 90-day window at all. It is reproducing
a static prior — "the kernel is mature and stable," "databases need careful,
urgent patching" — learned from training data with no mechanism to update
when that prior stops matching the live advisory stream. The pipeline's
ranking moves with releasetrain.io day to day (the 2026-10-14 snapshot placed
`macos` at rank 10 and `git` at rank 8; the run behind this table, pulled
fresh on 2026-10-15, placed them at 8 and 10) precisely because it has no
fixed prior to fall back on — a property that is a liability when the feed is
sparse or wrong (`docs/component_ranking_2026-10-14.md` already flags four
components with zero returned rows) but is the entire mechanism by which it
tracks `linux`'s and `wordpress`'s current advisory volume at all.

The one place the two systems land close together is the browser cluster:
pipeline ranks `chrome`, `firefox`, `safari`, `brave`, `opera`, `edge` at
13/16/21/23/24/22, and Ollama ranks the same six at 16/17/18/19/20/21 — both
systems cluster browsers in the middle-to-low urgency band, in roughly the
same relative order apart from `chrome`. That local agreement does not rescue
the global correlation: the kernel and database inversions pull in opposite
directions and the two nearly cancel, leaving ρ statistically indistinguishable
from a random pairing of two 30-item rankings. The practical reading is not
"the baseline is 5% anti-correlated with ground truth" — at this n that
number carries no weight on its own — but that a static-knowledge LLM's
update-order judgment and a live-advisory-driven ranking are not
interchangeable, and silently preferring the former over the latter for a
security-adjacent decision (which component to patch first) would rank the
single highest-CVE-volume component in the set as the lowest priority.

This comparison currently has one baseline arm, not three, and both systems
were queried once, not resampled across temperature or seed — the retry
logged in `llm_update_order_comparison_2026-10-15.md` (`llama3.1`'s first
attempt duplicated `postgresql` rather than producing a clean 30-item
permutation) is itself worth a sentence in the paper as a data point on
instruction-following at this list length, independent of the ranking
content. Extending to ChatGPT and Gemini, and to repeated runs for a
within-model variance estimate, is the natural next step before this table
is load-bearing for a submission.
