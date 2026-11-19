# Head-to-Head Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score our system and named competitors on the same labelled decision questions, leading with false-green rate, on a public dev split and a private held-out test split.

**Architecture:** One script, `scripts/head_to_head.py`, loads a decision sheet, takes gold labels where both annotators agree, asks each system for one label (act / hold / insufficient_evidence), and prints a table. Systems are plain functions `(row) -> label | None`. The held-out set is built by a small script into a gitignored folder.

**Tech Stack:** Python 3.11 stdlib, existing `eval_harness.providers.make_client`, `decide.decide` + `decide.COLLAPSE`, `urllib` for the OSV API, pytest.

**Spec:** `docs/superpowers/specs/2026-11-19-head-to-head-design.md`

## Global Constraints

- Labels are exactly `act`, `hold`, `insufficient_evidence` (`decide.COLLAPSE` maps our five-way verdict onto them).
- Lead metric: false-green rate = predicted `act` ÷ rows whose gold is `hold`.
- Gold = rows where `a1.verdict == a2.verdict` and neither is null; others are counted as "no gold" and skipped.
- No new dependencies. API keys from env / `.env` only; never committed (check `.env` is ignored before every commit).
- Held-out questions and labels never enter git: `data/heldout/` is gitignored.
- No `Co-Authored-By` trailer on commits.
- Tuning rule: no change to `decide.py`/`graph.py` may be motivated by held-out scores. The held-out run happens once.

## Review Focus

1. A competitor reply with no clean label ("It depends… probably safe") → counts as `None` ("unparsed"), reported in its own column, never silently counted as act or abstain.
2. A missing API key → that system's row reads "skipped", the run continues.
3. A gold set with zero `hold` rows → false-green prints "n/a (0 hold)", no ZeroDivisionError.
4. OSV network failure or unknown ecosystem → OSV returns `None` for that row, not `act` (a scanner that failed must not look like a green light).
5. A label word inside other text ("don't act yet, hold") → the parser takes the `VERDICT:` line only, not the first word it sees.

---

### Task 1: Scoring core

**Files:**
- Create: `scripts/head_to_head.py`
- Test: `tests/test_head_to_head.py`

**Interfaces:**
- Produces: `load_gold(path: str) -> list[dict]` (rows with added key `gold`), `parse_verdict(text: str) -> str | None`, `score(gold: list[str], pred: list[str | None]) -> dict` with keys `n, accuracy, false_green, abstain, unparsed, n_hold`.

- [ ] **Step 1: Write the failing tests**

```python
from scripts.head_to_head import parse_verdict, score, load_gold

def test_parse_takes_verdict_line_only():
    assert parse_verdict("don't act yet\nVERDICT: hold") == "hold"
    assert parse_verdict("verdict: Insufficient_Evidence") == "insufficient_evidence"
    assert parse_verdict("It depends, probably safe") is None

def test_score_false_green():
    s = score(["hold", "hold", "act", "insufficient_evidence"],
              ["act", "hold", "act", None])
    assert s["false_green"] == 0.5 and s["n_hold"] == 2
    assert s["accuracy"] == 0.5 and s["unparsed"] == 1

def test_score_no_hold_rows():
    assert score(["act"], ["act"])["false_green"] is None

def test_load_gold_keeps_agreed_rows(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"id":1,"a1":{"verdict":"hold"},"a2":{"verdict":"hold"}}\n'
                 '{"id":2,"a1":{"verdict":"act"},"a2":{"verdict":"hold"}}\n'
                 '{"id":3,"a1":{"verdict":null},"a2":{"verdict":"act"}}\n')
    rows = load_gold(str(p))
    assert [r["id"] for r in rows] == [1] and rows[0]["gold"] == "hold"
```

- [ ] **Step 2:** Run `venv311/bin/python -m pytest tests/test_head_to_head.py -v` → FAIL (module missing).
- [ ] **Step 3:** Implement the three functions. `parse_verdict` uses one regex on `^\s*verdict:\s*(act|hold|insufficient_evidence)\b`, case-insensitive, multiline. `abstain` = share of predictions equal to `insufficient_evidence`.
- [ ] **Step 4:** Re-run → PASS.
- [ ] **Step 5:** Commit `feat: head-to-head scoring core`.

### Task 2: Systems

**Files:**
- Modify: `scripts/head_to_head.py`
- Test: `tests/test_head_to_head.py`

**Interfaces:**
- Consumes: `parse_verdict` (Task 1).
- Produces: `PROMPT: str` (asks for reasoning then a last line `VERDICT: <label>`, defines the three labels as in `docs/decision_annotation_guide.md`); `ours(row) -> str | None` = `COLLAPSE[decide(row["evidence"], row["query"], vendors=[row["vendor"]]).verdict]`; `llm_system(spec: str, pooled: bool) -> Callable[[dict], str | None] | None` (None when `make_client(spec).available()` is false); `osv(row) -> str | None` (`hold` if the OSV query returns any vuln, `act` if none, `None` on error or when the ecosystem has no OSV mapping).
- Systems run: `ours`, `ollama:llama3.1` closed, `openai:gpt-4o-mini` closed + pooled, `gemini:gemini-2.5-flash` closed + pooled, `osv`. Closed = question + context only (what a user would type); pooled = also the row's evidence titles/text, so reasoning is compared on identical evidence.

- [ ] **Step 1: Write the failing tests**

```python
def test_ours_returns_collapsed_label():
    row = {"query": "Is it safe to update Firefox?", "vendor": "Firefox", "evidence": []}
    assert ours(row) in {"act", "hold", "insufficient_evidence"}

def test_llm_system_skips_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm_system("openai:gpt-4o-mini", pooled=False) is None

def test_osv_failure_is_not_green(monkeypatch):
    import scripts.head_to_head as h
    monkeypatch.setattr(h, "_osv_query", lambda *a: (_ for _ in ()).throw(OSError()))
    assert h.osv({"query": "q", "vendor": "lodash", "ecosystem": "npm", "evidence": []}) is None
```

- [ ] **Step 2:** Run tests → FAIL.
- [ ] **Step 3:** Implement. Reuse `load_dotenv` by importing it from `scripts/ask_external_models.py`. OSV: `_osv_query(package, ecosystem) -> list` POSTs to `https://api.osv.dev/v1/query`; map the sheet's `ecosystem` values `npm_node→npm`, `pip_python→PyPI`, `cargo_rust→crates.io`, `debian→Debian`, `ubuntu→Ubuntu`, `android→Android`, `linux_kernel→Linux`; every other ecosystem (iOS, Windows, Chrome, WordPress, …) → `None`. The report shows OSV's coverage n, because most of the 24 ecosystems are outside what a scanner sees — that gap is itself a finding.
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** Commit `feat: head-to-head systems (ours, LLMs, OSV)`.

### Task 3: CLI + report

**Files:**
- Modify: `scripts/head_to_head.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `python scripts/head_to_head.py SHEET [--out results/head_to_head_<name>.md]` prints and writes a markdown table: system, n, accuracy, false-green (with n_hold), abstain, unparsed, plus a "skipped" line per unavailable system, and the sheet's sha1 (reuse `file_hash` from `build_decision_benchmark.py`). Per-row predictions go to a sibling `.jsonl`.

- [ ] **Step 1:** Run it on a 3-row hand-made sheet in the scratchpad; expected: table prints, systems without keys say "skipped".
- [ ] **Step 2:** Commit `feat: head-to-head CLI and report`.

### Task 4 (human gate): Label the dev split

- [ ] Two annotators fill `a1`/`a2` on `data/decision_benchmark_200.jsonl` with `scripts/annotate.py`.
- [ ] `python scripts/compute_kappa.py data/decision_benchmark_200.jsonl verdict` → report κ; zero evidence-obligation errors.
- [ ] Run `scripts/head_to_head.py data/decision_benchmark_200.jsonl --out results/head_to_head_dev.md`; copy the table into `docs/` as the first published comparison (dev numbers, clearly labelled).

### Task 5: Held-out test split

**Files:**
- Create: `build_heldout.py`
- Modify: `.gitignore` (add `data/heldout/`)

**Interfaces:**
- Consumes: `load_pools`, `file_hash` from `build_decision_benchmark.py`; `graph.asks`.
- Produces: `python build_heldout.py QUESTIONS.json RUN_DIR --after 2026-11-20` → `data/heldout/decision_heldout.jsonl` in the same row format as the dev sheet, only questions created after the freeze date, and none whose id or text is in any `data/benchmark_*.json`.

- [ ] **Step 1:** Test `tests/test_heldout.py::test_drops_old_and_public_questions`: given 3 questions (one before the date, one whose text is in a public benchmark, one new), output has only the new one.
- [ ] **Step 2:** Run → FAIL; implement; run → PASS.
- [ ] **Step 3:** `git check-ignore data/heldout/x` prints the path.
- [ ] **Step 4:** Commit `feat: held-out decision split builder (output gitignored)`.
- [ ] **Step 5 (human):** collect fresh questions, fetch pools, label, run `head_to_head.py` once, report once.
