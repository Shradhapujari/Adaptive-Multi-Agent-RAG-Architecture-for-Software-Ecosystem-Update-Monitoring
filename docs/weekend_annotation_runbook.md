# Weekend annotation runbook — pilot of 30–50 rows

Two annotators (a1 = Shradha, a2 = Dr. Berhe). Everything runs offline from
`main` at or after `9c2b5b3`; no model, no network, no Ollama needed.

```bash
cd /Users/shradha/Adaptive-Multi-Agent-RAG-Architecture-for-Software-Ecosystem-Update-Monitoring
git pull --ff-only
venv311/bin/python -m pytest -q tests/test_decide.py tests/test_graph.py tests/test_calibration.py
```

## 0. Which sheet first

| Sheet | Rows | You label | Guide |
|---|---|---|---|
| `data/calibration_100.jsonl` | 100 pairs | `relevance` 0/1/2 of one document to one question | `docs/calibration_guide.md` |
| `data/decision_benchmark_200.jsonl` | 200 questions | `verdict` + `evidence_doc_ids` | `docs/decision_annotation_guide.md` |

Pilot the **decision sheet** on rows 1–30 first (the steps below). If the two
of you disagree on more than ~10 of 30, stop and fix the guide before going
further; if not, continue to 50, then the rest. Calibration follows the same
steps with `relevance` in place of `verdict` and no `evidence_doc_ids`.

## 1. Work on your own copy, never the shared file

Each annotator edits a private copy so neither sees the other's labels:

```bash
cp data/decision_benchmark_200.jsonl ~/annot_a1.jsonl     # Shradha
cp data/decision_benchmark_200.jsonl ~/annot_a2.jsonl     # Dr. Berhe (on her machine, or a second copy here)
```

Do **not** open `data/calibration_100.judge.json` until both calibration
sheets are complete — it is the judge's labels, and the sheet is only blind
while it stays closed.

## 2. Label a row

One JSON object per line. Edit **only your block**. For row `id` 7, a1 fills:

```json
"a1": {"verdict": "hold", "evidence_doc_ids": ["1de579ba69d8", "dc368e2e7c1c"], "note": ""}
```

Rules the script enforces (from the guide):

- `verdict` ∈ `act` / `hold` / `insufficient_evidence`.
- `act` or `hold` → `evidence_doc_ids` has ≥ 1 id, every id from **this row's**
  `evidence` list.
- `insufficient_evidence` → `evidence_doc_ids` is `[]`.
- Read only the `evidence` list. No web search. Headline-only rows
  (`google_news`) are judged on the title.

Any text editor works; the script in §4 validates the result, so the editing
method does not matter. Keep one JSON object per line.

## 3. Score the system against your own labels (any time)

Works on a partially filled sheet; unlabelled rows are skipped.

```bash
venv311/bin/python decide.py --sheet ~/annot_a1.jsonl --gold a1
```

Reports `n`, `accuracy`, `macro_f1`, `abstention_precision` /
`abstention_recall` (over `insufficient_evidence`), and `evidence_precision` /
`evidence_recall` (overlap between the ids you cited and the ids the rule
used). The verdict distribution above it is the same 25 / 9 / 13 / 14 / 139
whatever you label — the rule does not see your block.

## 4. Merge the two copies and compute agreement

Once both of you have labelled the same rows, merge a2's block into a1's file
(ids match line for line):

```bash
venv311/bin/python - <<'EOF'
import json
a1 = [json.loads(l) for l in open("/Users/shradha/annot_a1.jsonl")]
a2 = {r["id"]: r for r in (json.loads(l) for l in open("/Users/shradha/annot_a2.jsonl"))}
for r in a1:
    r["a2"] = a2[r["id"]]["a2"]
with open("/Users/shradha/annot_merged.jsonl", "w") as f:
    for r in a1:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("merged", len(a1))
EOF

venv311/bin/python scripts/compute_kappa.py ~/annot_merged.jsonl verdict
```

What you get, in order:

1. `evidence obligation: N error(s)` — fix these first; they are sheet
   errors, not labels.
2. `a1 vs a2` — Cohen's κ with a bootstrap 95% CI, overall and per `asks` /
   `tier`. Strata under 15 rows print counts only (`--min-n` to change).
3. Nothing else for the decision sheet. For calibration, add
   `--judge data/calibration_100.judge.json` and the field `relevance`; you
   then also get each of you vs the judge and the judge vs the rows you agree
   on — this is what the Δ ≤ 0.10 rule in `docs/calibration_guide.md` reads.

## 5. Adjudicate and freeze

For every disagreement, a third pass (whoever did not label that row last, or
both together after κ is recorded) sets the gold label in a `gold` block:

```json
"gold": {"verdict": "hold", "evidence_doc_ids": ["1de579ba69d8"], "note": "a2 missed the top comment"}
```

Then:

```bash
venv311/bin/python decide.py --sheet ~/annot_merged.jsonl --gold gold
```

When the full 200 are adjudicated, copy the merged file back over
`data/decision_benchmark_200.jsonl`, record κ and the date in the manifest,
and commit on a branch — the sheet is frozen from that commit on.

## Monday checkpoint (12 Oct 2026)

- Pilot κ (a1 vs a2, n = 30–50) and the disagreement list.
- `decide.py --gold a1` and `--gold a2` on the pilot rows.
- Any guide changes the pilot forced, as a diff to
  `docs/decision_annotation_guide.md`.
