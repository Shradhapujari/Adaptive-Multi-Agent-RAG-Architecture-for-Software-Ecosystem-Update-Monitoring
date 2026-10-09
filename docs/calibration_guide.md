# Human–judge calibration — annotation guide

File: `data/calibration_100.jsonl`, one (question, document) pair per line.
Fill in your block only (`a1` or `a2`), the `relevance` field. The judge's
label is in a separate file you must not open until both sheets are done.
Do not search the web; the document is all the judge saw.

## Scale — the same one the judge was given

| relevance | meaning |
|---|---|
| `2` | The document **answers the question directly**: it states the version, date, fix, stance or CVE the question asks for, about the asked product. |
| `1` | **Related**: same product or area, but not a direct answer (a different version, a neighbouring issue, a general release note). |
| `0` | **Irrelevant**: a different product, or nothing to do with the question. |

Rules of thumb:

- Judge the **document**, not the question's answerability. A question nobody
  can answer still has `0`s and `1`s.
- A headline-only document (`google_news` rows have no body) is judged on its
  title. Do not mark it down for the missing body.
- A document that names the right product and the right attribute but gives a
  value for a *different* version is `1`, not `2`.
- Community posts: `2` if the post or its top comment states the thing asked;
  `1` if it is the same complaint without the answer.

`note` is optional. Use it for an injected or spam document, or a pair you
think is mis-tagged (`asks`, `tier`).

## Protocol

Two annotators, all 100 pairs, independently. Then:

    python scripts/compute_kappa.py data/calibration_100.jsonl relevance \
        --judge data/calibration_100.judge.json

Report human–human κ (unweighted and quadratic-weighted), each human vs the
judge, and the judge vs the rows the humans agreed on, overall and per `asks`
× `tier`. Cells under 15 pairs are reported as counts, not κ. Decision rule:
the judge's labels are used in a stratum only where judge–human κ is within
0.10 of human–human κ there; elsewhere the stratum is human-labelled or
excluded, and the paper says which.

Sample size: with ~100 pairs and κ around 0.5 the 95% CI is roughly ±0.15;
that is wide enough to be honest about and narrow enough to separate "the
judge works" from "the judge is a coin toss".
