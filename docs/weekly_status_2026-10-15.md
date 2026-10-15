# Weekly status — 2026-10-15

Since the Mon 12 Oct checkpoint ([weekend-runbook](weekend_annotation_runbook.md)).

## Headline: closed a false-green safety bug in the decision layer

The system answered 🟢 **"safe to update Firefox"** while 11 real Firefox
advisories were live in the feed, one of them 8 days old. Root cause was
**two independent gates**, both of which had to be fixed for the bug to stay
fixed — fixing only one still produced the green.

### Gate 1 — opinion intent excludes advisory evidence

"Is it *safe* to update X?" classifies as an `opinion` question, and the
intent rule that decides which document kinds an answer may cite
(`intent._CITABLE`) excludes CVE/advisory records for opinion questions. The
decision pool was built from that same citable set, so the verdict never saw
the advisories at all and fell through to `safe` with the rationale
"no advisory."

**Fix:** a safety *verdict* is not the same thing as the *prose* that may
cite it — withholding advisory evidence from the verdict is asymmetric (it
can only ever manufacture a false green, never a false red). Advisory rows
excluded from the display pool are now carried separately
(`decision_advisories`) and always reach `decide()`. The verdict is also
injected into the model's prompt *before* the shape instructions (so a local
model like llama3.1 won't ignore it as an afterthought) and force-prefixed
onto whatever the model writes, so the paragraph can never say "safe" under
a red badge.

### Gate 2 — weakness-first advisory phrasing

Even with Gate 1 fixed, the live NVD feed phrases most advisories
**weakness-first**: *"Mitigation bypass in the File Handling component. This
vulnerability was fixed in Firefox 157.0.1."* — the product name never
appears in the advisory's grammatical subject, only in the fix clause. The
rule that matches an advisory to the asked-about product
(`decide._subject_names_product`) required the product to appear *before*
the first predicate, so these records were rejected as "not about Firefox,"
re-manufacturing the same green on the live feed.

**Fix:** the product-match rule now also accepts a product named in a
"fixed/patched/resolved in …" clause, with the same cross-vendor and
platform-preposition guards the subject rule already uses (so "fixed in
Metabase 1.2" doesn't match a MySQL question, and "fixed in Firefox for iOS"
stays a Firefox advisory, not an iOS one).

### Verification

- **102 tests pass** (`test_decide.py`, `test_app_decision.py`,
  `test_answer_agent.py`), including a regression test pinned to this exact
  Firefox scenario for each gate.
- **Zero-delta on the frozen 200-question benchmark**: `patch_urgently`
  count is 22 before and after the Gate 2 fix — it adds live-feed coverage
  without moving any already-reported verdict.
- Live reproduction: the real weakness-first NVD record now returns
  `patch_urgently` instead of `insufficient_evidence`.

## Two new comparison analyses

- **LLM vs. live-pipeline update-urgency ranking**
  ([llm_update_order_comparison_2026-10-15.md](llm_update_order_comparison_2026-10-15.md)):
  30 components ranked independently by Ollama/llama3.1 (from its own
  knowledge) and by the live ReleaseTrain pull. **Spearman's ρ ≈ -0.05** —
  essentially no correlation. Supports the thesis claim that an LLM's
  internal sense of update risk is not a substitute for live monitoring.
- **Four-way system comparison**
  ([system_comparison_2026-10-14.md](system_comparison_2026-10-14.md)) on
  one question across raw Ollama (no retrieval), single-agent RAG, the
  multi-agent decision pipeline, and hosted models (ChatGPT/Gemini wired up,
  pending API keys). This is the run that surfaced the false green above.

## Housekeeping

- Added a SANER 2027 submission section (10+2 page track) to the paper.
- Fixed `shipped()` to order releases by version number instead of date.

## Next

- Re-run the 200-question decision benchmark end-to-end now that both gates
  are fixed.
- Fold the annotator κ from the calibration pilot into the paper.
