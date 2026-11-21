# Head-to-head comparison + held-out test split — design (draft, not approved)

## Why
People ask "how do you compare to competitors?" There is no measured answer today.
Research comes first; a product may follow if the scope validates.

## Goals
- Score our system and named competitors on the same questions, the same labels, the same metric.
- Lead metric: **false-green rate** (said update when the gold label is hold). Also accuracy and abstention.
- Keep a test split no competitor and no model trainer has seen (option 2).

## Non-goals / anti-goals
- No product, integrations or team features yet (that's open core, later).
- Anti-goal: a comparison we tuned on. If our system is adjusted after seeing test scores, the number is void.

## Constraints found
1. `data/decision_benchmark_200.jsonl` has **0 labels**: every a1/a2 verdict is empty. Nothing can be scored yet.
2. Every benchmark file (100/300/500/1000, decision 200, calibration 100) is **already public** on GitHub.
   None of them can serve as a held-out test set.

## Approaches considered
- **A. Public 200 = dev, fresh held-out test (picked).** Label the public 200 and publish them as the dev split.
  Build a new test set from questions posted after a freeze date, never pushed. It also avoids training-data contamination.
- B. Pull 200 from the repo and call them held out. Rejected: already public, can't be undone.
- C. Skip the hold-out and compare on the public 200 only. Rejected: contradicts option 2.

## Systems in the comparison
| system | how it is run |
|---|---|
| ours (`marag_decide`) | `graph.run`, frozen corpus |
| single-agent RAG baseline | existing arm |
| raw local LLM (llama3.1) | no retrieval |
| ChatGPT, Gemini | `scripts/ask_external_models.py` (exists; needs API keys) |
| OSV-style scanner | OSV API lookup for the named package — the "known CVE only" baseline |

All LLM systems get the same prompt that requires one label: act / hold / insufficient_evidence,
so no fuzzy mapping of free text. The scanner maps "advisory found" to hold, else act.

## Order of work
1. Label the public 200 (two annotators, `compute_kappa.py`). Already the blocker for everything.
2. Run all systems on the 200 → first published comparison table (dev numbers).
3. Freeze a date; collect + label a fresh test set kept local (gitignored); run once, report once.

## Left to the builder
Prompt wording, test-set size (default 200), the exact OSV mapping per ecosystem.
