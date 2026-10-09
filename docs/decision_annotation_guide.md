# Decision benchmark — annotation guide

File: `data/decision_benchmark_200.jsonl`, one question per line. Fill in your
block only (`a1` or `a2`). Do not read the other annotator's block. Do not
search the web: label from the `evidence` list and nothing else — the system
under test sees exactly that pool and nothing else.

## Verdict (exactly one)

| verdict | meaning |
|---|---|
| `act` | The evidence supports a concrete recommendation: install / stay on this version / apply this fix / roll back. The asker could do something now. |
| `hold` | The evidence is about the right product and the asked attribute, but it is conflicting, outdated for the asked version, or says "not yet" — the right call is to wait and re-check. |
| `insufficient_evidence` | No document in the pool is about the asked product *and* the asked attribute. A document about the product that does not address the question is still insufficient. |

`hold` vs `insufficient_evidence`: `hold` requires evidence that *speaks to the
question*; `insufficient_evidence` means nothing does. If you are torn, it is
`insufficient_evidence`.

## Evidence obligation

- `act` or `hold`: list every `doc_id` you relied on in `evidence_doc_ids`
  (one or more). Only ids from this question's `evidence` list are valid.
- `insufficient_evidence`: leave `evidence_doc_ids` empty.

This is checked by script. A verdict of `act`/`hold` with no ids, or an id not
in the pool, is a sheet error, not a label.

## Notes

`note` is free text, optional. Use it when the question is unanswerable in
principle (opinion, "anyone else?"), when a document is injected / off-topic
spam, or when you suspect a fetch bug (headline-only rows from google_news are
expected — judge the title).

## Protocol

Two annotators label all 200 independently. Agreement is Cohen's κ over the
three verdicts, reported overall and per `asks` stratum (version / date /
fix_status / cve / other). Disagreements are adjudicated by a third reader
without seeing who labelled what; the adjudicated label is gold. Do not
discuss questions until both sheets are complete.
