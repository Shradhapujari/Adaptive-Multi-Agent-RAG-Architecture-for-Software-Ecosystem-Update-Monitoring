# Four-way system comparison — 2026-10-14

Question put to every system verbatim: **"Is it safe to update Firefox right now?"**

| system | verdict | grounding | citations | latency |
|---|---|---|---:|---:|
| Ollama `llama3.1`/`mistral`, raw (no retrieval) | none — "generally safe … back up your data" | none | 0 | 7.7s |
| Single agent (baseline RAG) | none — describes, does not decide | 5 docs | 0 inline | 15.9s |
| Multi-agent pipeline (`marag_decide`, app_1.py) | 🟢 safe to update | 5 community · 5 releases · 0 CVE · quality 0.70 | 3 | 42.7s |
| ChatGPT | **not run** — no `OPENAI_API_KEY` set (SDK installed, provider ready) | — | — | — |
| Gemini | **not run** — no `GEMINI_API_KEY` set (provider added 2026-10-14, `google-genai` 2.30.1 installed) | — | — | — |

Both hosted rows are one command away once a key is present:

```bash
python scripts/ask_external_models.py
```

Caveat on the Gemini backend: `available()` is exercised, but `_generate()` has never
executed — no call has been made against the live API. Treat the first run as a smoke test.

Raw answers:

- **Ollama (raw):** "Yes, it is generally safe to update Firefox when a new version becomes
  available… ensure your system meets the minimum requirements and back up important data."
  No version, no CVE, no date — the ungrounded failure mode, as expected.
- **Single agent:** "Based on the provided sources, the latest Firefox update (v157.0.1) was
  released on October 6, 2026, addressing a mitigation bypass in the File Handling component."
- **Multi-agent:** "🟢 Safe to update: release note present, no advisory, fewer than 2 problem
  reports. [Firefox v139.0.0] [Firefox v154.0.0] [Firefox v157.0.0] It is safe to update
  Firefox right now."

## Three findings worth chasing

**1. Possible false green.** The multi-agent arm returned 🟢 on the reason "no advisory", in the
same session where the single agent — over the same sources — reported that v157.0.1 fixes a
*mitigation bypass in File Handling*, and where `scripts/component_stability_ranking.py` scored
firefox at risk 44 / Medium on **9 advisories in the last 90 days**. Three components of the same
system disagree on whether Firefox currently has an advisory. A green verdict that should have
been amber is the expensive direction of error.

**2. Three different "latest Firefox" versions in one session.**

| source | latest Firefox |
|---|---|
| `scripts/component_stability_ranking.py` (`/api/v/search`) | 156.0.0 |
| multi-agent citation | 157.0.0 |
| single agent | 157.0.1 |

Different endpoints and different filters, unreconciled. Worth pinning before any of these numbers
go in a deck.

**3. Multi-agent costs 2.7× the latency** of the baseline here (42.7s vs 15.9s) for a question
where it added a verdict and citations the baseline did not produce. Consistent with C3: the
value is the decision layer, not retrieval.

## Reproducing

```bash
venv311/bin/streamlit run app_1.py --server.port 8599 --server.headless true
```

Do **not** demo from a long-running instance. Two instances still up from 27 Sep and 4 Oct serve
stale module state and crash on the multi-agent path (`AttributeError: module 'tokens' has no
attribute 'delta'`, `module 'answer_agent' has no attribute 'split_summary'` — both functions
exist in the current source). Streamlit does not reload already-imported modules. Restart before
any demo.
