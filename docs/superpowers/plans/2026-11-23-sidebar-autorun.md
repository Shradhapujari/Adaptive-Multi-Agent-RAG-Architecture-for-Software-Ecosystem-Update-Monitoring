# Sidebar Questions Run on Click — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A click on any sidebar question (examples, Latest, Random, dropdown, Ask again) fills the box and answers it in every mode; a typed question still answers on Ask/Enter; a Reddit pick is answered from its own thread in the console too.

**Architecture:** One module-level `_submit(q, row=None)` in `app_1.py` writes both question boxes, the thread id, and a one-shot `auto_ask` flag. The console (`render_ask_view`) and classic view treat a popped `auto_ask` like their own Ask/Run button. `ask()` gains `reddit_id` and passes it to `run_pipeline`, skipping the fast path.

**Tech Stack:** Python, Streamlit, pytest (monkeypatched `app_1.st.session_state` as a dict, as existing tests patch `app_1.st`).

**Spec:** `docs/superpowers/specs/2026-11-23-sidebar-autorun-design.md`

## Global Constraints

- Opening the "Pick a Reddit question" expander runs nothing; only a click does.
- `auto_ask` is consumed once (`pop`), so a rerun never re-submits by itself.
- A thread id applies only while the box still holds that thread's title.
- Typed questions keep today's behaviour: console runs on Ask/Enter, classic on its Run button.

## Review Focus

- Dropdown still holding an old pick while Latest/Random is clicked → today the dropdown's `reddit_title != title` check re-applies the old pick in the same rerun and overrides the click. Fix: dropdown applies via `on_change` only. (Task 3)
- Typed question after a Reddit pick → must not carry the old thread id. (Task 2 test)
- Reddit pick routed to the fast path → fast path ignores the thread; must go full. (Task 2 test)
- Example click after a Reddit pick → clears `reddit_id`. (Task 1 test)
- Latest/Random with nothing matching the vendor → caption, no run, box unchanged. (Task 3, manual check)

---

### Task 1: `_submit` helper

**Files:**
- Modify: `app_1.py` (new function just above `render_ask_view`, ~line 2860)
- Test: `tests/test_sidebar_autorun.py`

**Interfaces:**
- Produces: `_submit(q: str, row: Optional[dict] = None) -> None` — sets `main_query` and `ask_query` to `q`; with `row`, sets `reddit_title = row["title"]`, `reddit_id = row.get("redditId")`; without, pops `reddit_id`; always sets `auto_ask = True`.

- [ ] **Step 1: Failing tests** (`monkeypatch.setattr(app_1.st, "session_state", state)` with `state = {}`)
  - `test_submit_fills_both_boxes_and_flags_a_run`: `_submit("Is it safe?")` → `state["main_query"] == state["ask_query"] == "Is it safe?"`, `state["auto_ask"] is True`.
  - `test_submit_with_a_thread_remembers_it`: `_submit("T", {"title": "T", "redditId": "abc"})` → `state["reddit_id"] == "abc"`, `state["reddit_title"] == "T"`.
  - `test_example_after_a_thread_forgets_it`: state starts with `reddit_id="abc"`; `_submit("Latest Django release notes")` → `"reddit_id" not in state`.
- [ ] **Step 2:** `pytest tests/test_sidebar_autorun.py -q` → FAIL (`_submit` missing).
- [ ] **Step 3:** Implement `_submit` in `app_1.py`.
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5:** Commit `app: one helper submits a sidebar question`.

### Task 2: Console and classic views run on the flag; `ask()` takes the thread

**Files:**
- Modify: `app_1.py` — `ask()` (~2674), `render_ask_view` (~2862-2890), classic run button (~3489-3505)
- Test: `tests/test_sidebar_autorun.py`

**Interfaces:**
- Consumes: `auto_ask`, `reddit_id`, `reddit_title` from Task 1.
- Produces: `ask(q, limit=5, source="agent", checks=None, reddit_id: Optional[str] = None)`.

- [ ] **Step 1: Failing tests** (monkeypatch `app_1.run_pipeline` to record kwargs and return `{"original_query": q}`, `app_1.run_fast` to record calls, `app_1._present_answer` to return a stub, `app_1.graph.route_query` to return `("fast", "version lookup")`)
  - `test_picked_thread_goes_full_path_with_its_id`: `ask("Did 44 break grub?", reddit_id="abc")` → `run_fast` not called, `run_pipeline` kwargs `reddit_id == "abc"`, `results["route"]["mode"] == "full"`.
  - `test_typed_question_has_no_thread`: `ask("Latest Node.js version?")` → if `run_pipeline` is reached its `reddit_id` is `None`.
- [ ] **Step 2:** Run → FAIL (unexpected kwarg).
- [ ] **Step 3:** In `ask()`: when `reddit_id`, set `route = {"mode": "full", "why": "picked Reddit thread"}` before the fast branch; pass `reddit_id=reddit_id` to `run_pipeline`.
- [ ] **Step 4:** In `render_ask_view`: `asked = asked or st.session_state.pop("auto_ask", False)`; `rid = st.session_state.get("reddit_id") if st.session_state.get("reddit_title") == q else None`; call `ask(..., reddit_id=rid)`. Inside the answer container after `_tab_short`, when `rid`: if `results.get("yesno")` and its `"answered"`, `st.success(yesno.verdict_line(yn))`; if `results.get("top_comment")`, `st.info` in the same "Top-voted comment (N points, u/author)" format as the compare column (~3576).
- [ ] **Step 5:** Classic view: `run_btn = run_btn or st.session_state.pop("auto_ask", False)` right after the Run button.
- [ ] **Step 6:** Run tests → PASS; also `pytest tests/test_console_layout.py tests/test_fast_path.py -q` → PASS.
- [ ] **Step 7:** Commit `console: answer a sidebar pick on click, from its own thread`.

### Task 3: Wire every sidebar control to `_submit`

**Files:**
- Modify: `app_1.py` — `_ask_thread` (~3190), Latest/Random (~3230-3270), dropdown (~3271-3276), examples (~3287), Ask again (~3319)

- [ ] **Step 1:** `_ask_thread(row)` becomes `_submit(row.get("title", ""), row)`.
- [ ] **Step 2:** Examples and "Ask again": body becomes `_submit(ex)` / `_submit(r.query)`.
- [ ] **Step 3:** Dropdown: drop the `reddit_title != title` check; apply with `on_change=` a callback that reads `st.session_state["reddit_pick"]` and calls `_ask_thread(q_opts[pick])` unless it is `"—"` (pass `q_opts` via `args`). Keep the "Feed unreachable" caption when `not q_rows`.
- [ ] **Step 4:** `pytest -q` (full suite) → no new failures vs `origin/main`.
- [ ] **Step 5:** Browser check (`.claude/launch.json` app): in Decision console, click an example → answer appears without pressing Ask; click Latest with Vendor=All → newest thread's title in box and answer with top comment; Random with a vendor → answers; typed question + Enter → answers; open the Reddit expander → nothing runs. One run at a time (Ollama).
- [ ] **Step 6:** Commit `sidebar: Latest, Random, picks and examples run on click`.
