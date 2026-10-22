# Advisor-feedback refactor — change log & audit, 2026-10-16

Work from Dr. Berhe's feedback and the ReleaseTrain docs. Branch
`fix/gemini-empty-response-and-ranking-order` (uncommitted working tree).

## Provenance note on the "GR-1 / GR-2" and "DuckDuckGo" framing

The request cited "GR-1 / GR-2" patterns and a "DuckDuckGo fallback" from the
ReleaseTrain docs (`https://releasetrain.io/?view=docs`). The docs **do not**
contain those labels, nor "DuckDuckGo". They *do* describe (a) an unnamed
"deterministic web-search fallback" (`search_web`), (b) intent-based routing
where a bare vendor/product name "short-circuits to a document lookup with no
model call", and (c) opinion questions mapped to "Declined, no retrieval". The
code and paper here are therefore framed as **our** design — GR-1 = the local
lake, GR-2 = our bounded web fallback, with DuckDuckGo as our chosen provider —
and do **not** cite GR-1/GR-2 as a ReleaseTrain spec.

## Design decision (confirmed with the user)

Web fallback = **bounded escalation**, not replacement: on `ABSENT` try one web
search; if the web is *also* empty of a verifiable version/date/CVE, still
abstain. Kept **out of the frozen eval** (live reads aren't reproducible). Web
text is `[untrusted:community]`-wrapped and runs the same egress CVE validation.
This preserves the paper's abstention thesis rather than undercutting it.

## Change-log

| # | Change | Failure mode it addresses | File(s) |
|---|--------|---------------------------|---------|
| 1 | `route_query()` — fast vs full routing | Every question paid full-pipeline cost; basic "latest version of X?" needs one feed read, not the state machine + retries + verify | `graph.py` |
| 2 | `fast_run()` convenience | — (fast path falls out of the existing machine: identity rewrite, `max_rounds=1`, no verifier; SUFFICIENT→answer, else abstain) | `graph.py` |
| 3 | `websearch.py` — bounded DuckDuckGo fallback | "Answer not found" on `ABSENT` when the open web *does* have community/forum evidence — now one web hop, still abstains if the web is empty | `websearch.py` (new) |
| 4 | Untrusted wrapping + NFKC/zero-width screen + CVE/version extraction on web results | Web text is a prompt-injection surface; the system's guardrails must still apply to fallback evidence | `websearch.py` → reuses `guardrail.screen/scrub` |
| 5 | `run_pipeline(..., web_fallback=False)` + GR-2 block | Wires the bounded escalation into the ABSENT path only, on a healthy fetch; off by default so eval/other callers are untouched | `app_1.py` |
| 6 | Two-column / 5-tab / console **Decision console** view, default Ask mode | Multi-step classic UI "cluttered and overwhelming for live demos" (Dr. Berhe) | `app_1.py` (`render_ask_view` + `_tab_*` + `_console_log`) |
| 7 | Clean "Ask" button (not "Run"); classic single/compare/pipeline kept behind other modes | Berhe's stripped top bar; zero risk to the measured arms | `app_1.py` |
| 8 | Paper: bounded web-fallback paragraph (framed to preserve abstention thesis) | Documents GR-2 honestly as a mechanism, out of frozen eval | `paper/saner2027.tex`, `paper/tosem_amara.tex` |

The maintenance framing, the false-green write-up, and the ρ≈−0.05 ranking were
already in both papers (committed earlier on this branch); only the web-fallback
paragraph was added here.

## How each previous failure mode is addressed

- **False green ("safe" with live CVEs).** Already fixed on-branch (advisories
  reach the verdict regardless of intent; weakness-first NVD subject matching;
  `is_cve` key-name fix). **Verified live 2026-10-16** in the new console view:
  "Is it safe to update Firefox?" → **🔴 Patch urgently**, 8 advisory docs with
  a CVE id, confidence 1.00; Long-Answer prose agrees ("It is not safe to update
  Firefox"). The Guardrails tab shows NFKC, `[untrusted:community]`, and egress
  CVE validation all on.
- **"Answer not found" on sparse questions.** GR-2 bounded fallback — but the
  thesis (abstain when evidence doesn't exist anywhere) is kept: no backend or an
  empty web → the same honest abstention.
- **Every question paying full cost.** `route_query()` sends single-product
  factual lookups down the fast path; safety/comparison questions take the full
  pipeline. Mechanism only — latency/token effect not yet measured.
- **Replay reproducibility.** `graph.py` stays network-free; GR-2 lives at the
  orchestration layer and never enters `eval_harness`.

## Verification

- `graph.py` self-check: routing + fast-path asserts pass (`python graph.py`).
- `websearch.py` self-check: untrusted wrapping, version/CVE extraction, gate
  reads the wrapped text, no-backend → abstain (`python websearch.py`).
- `app_1.py`: launched (`app1` config), ran the Firefox query end-to-end in the
  browser; all five tabs + console render; honest 🔴 verdict confirmed.
- Full `pytest`: (see run; graph routing cases are in `graph._demo`).

## Not done / caveats

- DuckDuckGo backend not installed (`pip install ddgs` to enable the live hop);
  until then GR-2 shows "no backend" in the console and the ABSENT path abstains
  as before.
- Fast-path and GR-2 are **mechanisms, not measured results** — no latency/token
  or accuracy numbers; the papers say so explicitly.
- "Live console" is assembled from the completed run (one repaint), not
  token-streamed mid-run.
