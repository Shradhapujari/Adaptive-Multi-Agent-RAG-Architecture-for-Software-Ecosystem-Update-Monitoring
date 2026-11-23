# General Software Questions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Product-named software questions that aren't about updates ("Is zoom better or teams?", "What happened to Microsoft recently?") get a web answer with no act/hold verdict, instead of an update verdict built from unrelated advisories.

**Architecture:** Two new answer-only live types, `news` and `general`, go at the end of `live_sources.kind()`'s precedence. They fire only on a positive general-question cue, and only when `intent.classify` makes no confident call and `_UPDATE_CUE` doesn't match. The console's existing answer-only path (`run_pipeline` drops the verdict; `_tab_short` uses the answer as the headline) carries them unchanged. A suggestion-only name list lets `vendor.suggest` catch "miscrosoft".

**Tech Stack:** Python 3.11 stdlib `re`, pytest, Streamlit console (`app_1.py`), DuckDuckGo through `websearch.search`.

**Spec:** `docs/superpowers/specs/2026-11-21-general-questions-design.md`

## Global Constraints

- Console-only: no change to the eval harness, `multiagent_rag_v3.py`, `graph.py` routing or `intent.py`. `test_frozen_paper_modules_do_not_import_live_sources` must keep passing.
- The default is unchanged: a question that matches none of the new cues keeps today's route.
- Typos are suggested, never silently substituted (the `vendor.suggest` "Nodej.s" decision of 2026-11-12).
- Work on a branch `feat/general-questions` cut from `main`. Commit messages carry **no** Co-Authored-By trailer (user preference). Before every commit: `git check-ignore -q .streamlit/secrets.toml && echo ignored`, and `git branch --show-current` reports `feat/general-questions`.
- Run tests with `venv311/bin/python -m pytest`.

## Review Focus

1. A version or "latest" question that opens with "What is" ("What is the latest Chrome version?") must keep the feed path. Release intent is confident there, so `kind` returns None. Test in Task 1.
2. An update complaint phrased generally ("Why is Chrome not updating?") must keep the verdict, because `_UPDATE_CUE` matches. Test in Task 1.
3. A question carrying both an outage cue and a news cue ("What happened during the GitHub outage?") must stay `incident`, which comes earlier in precedence. Test in Task 1.
4. A news search that returns nothing must report the error in `meta` just as `incident` does. Covered by reusing the `incident` fetcher; tested in Task 1.
5. The four suggestion-only names must not enter `known_products()`, or `vendor` detection's word-gap rule (d60eeef, "Microsoft Edge" → Edge) changes. Test in Task 2.

---

### Task 1: `news` and `general` live types, and "better … or" comparisons

**Files:**
- Modify: `live_sources.py`: `KINDS`, `KIND_LABEL`, `ANSWER_ONLY`, the new cue regexes beside `_HOWTO`, `kind()`, `_incident` → `_news`, `fetch()`
- Test: `tests/test_live_sources.py`

**Interfaces:**
- Produces: `live_sources.kind(query, vendors=()) -> Optional[str]` can now also return `"news"` or `"general"`. `live_sources.fetch("news" | "general", query) -> (docs, meta)` with `meta["kind"]` equal to the kind passed in. `KIND_LABEL["news"] == "News"` and `KIND_LABEL["general"] == "General"`. Both kinds are in `ANSWER_ONLY`.

- [ ] **Step 1: Create the branch**

Run: `git switch -c feat/general-questions main`
Expected: `Switched to a new branch 'feat/general-questions'`

- [ ] **Step 2: Write the failing tests**

Add rows to the `test_kind` parametrize table:

```python
    ("Is zoom better or teams?", "compare"),
    ("What happened to Microsoft recently?", "news"),
    ("Any news about Slack?", "news"),
    ("What's going on with Blockify?", "news"),
    ("What is Kubernetes?", "general"),
    ("How does Upsert work?", "general"),
    ("Why does Linux not need anti-virus software?", "general"),
    ("What is the latest Chrome version?", None),          # release intent
    ("What is CVE-2024-1234?", None),                      # update cue
    ("Why is Chrome not updating?", None),                 # update cue
    ("iOS 26.3 WiFi/RAM issues?", None),                   # update report, no general cue
    ("Latest Node.js version?", None),                     # release intent
    ("What happened during the GitHub outage?", "incident"),  # precedence
```

Then add the fetch tests, using the existing `_search_returns` helper:

```python
def test_news_searches_news_last_month(monkeypatch):
    seen = []
    _search_returns(monkeypatch, [{"title": "t", "body": "b", "href": "https://n.com/x",
                                   "date": "2026-11-20", "source": "N"}], seen=seen)
    docs, meta = L.fetch("news", "What happened to Microsoft recently?")
    assert seen[0] == {"q": "What happened to Microsoft recently?", "timelimit": "m", "news": True}
    assert meta["kind"] == "news" and docs[0]["label"].startswith("News - ")

def test_news_error_reaches_meta(monkeypatch):
    _search_returns(monkeypatch, [], err="search failed: RatelimitException")
    _, meta = L.fetch("news", "Any news about Slack?")
    assert meta["kind"] == "news" and meta["error"] == "search failed: RatelimitException"

def test_general_is_a_plain_search(monkeypatch):
    seen = []
    _search_returns(monkeypatch, [], seen=seen)
    _, meta = L.fetch("general", "What is Kubernetes?")
    assert seen[0]["news"] is False and seen[0]["timelimit"] is None and meta["kind"] == "general"

def test_news_and_general_replace_the_verdict():
    assert L.answer_only("news", "What happened to Microsoft recently?")
    assert L.answer_only("general", "What is Kubernetes?")
```

- [ ] **Step 3: Run them to make sure they fail**

Run: `venv311/bin/python -m pytest tests/test_live_sources.py -q`
Expected: the new `test_kind` rows and the four new tests FAIL. Every existing test passes.

- [ ] **Step 4: Implement in `live_sources.py`**

- Add `"news", "general"` to the end of `KINDS` and to `ANSWER_ONLY`. Add `"news": "News"` and `"general": "General"` to `KIND_LABEL`.
- `_NEWS = re.compile(r"\b(?:what happened|happening|going on with|recent(?:ly)?|lately|news|this week)\b", re.I)`
- `_GENERAL = re.compile(r"^\s*(?:what (?:is|are)|what's|how does|explain|why (?:does|is))\b", re.I)`
- `_BETTER_OR = re.compile(r"\bbetter\b[^?]*\bor\b|\bor\b[^?]*\bbetter\b", re.I)`. OR it into the existing `compare` condition in `kind()`.
- At the end of `kind()`, after the `howto` check:
  ```python
  if _UPDATE_CUE.search(q) or intent.classify(q).confident:
      return None
  if _NEWS.search(q):
      return "news"
  if _GENERAL.search(q):
      return "general"
  return None
  ```
  Add `import intent` with the module imports. intent is stdlib-only, so this creates no cycle.
- Rename `_incident(query)` to `_news(query, kind_="incident")` and pass `kind_` into both `_meta` calls. `fetch` keeps `incident` → `_news(query)` and adds `news` → `_news(query, "news")`. `general` falls through to the existing final `_plain(kind_, query, None, "DuckDuckGo")`, so it needs no branch.

- [ ] **Step 5: Run the tests to make sure they pass**

Run: `venv311/bin/python -m pytest tests/test_live_sources.py tests/test_live_wiring.py tests/test_vendor_cap_and_live_label.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add live_sources.py tests/test_live_sources.py
git commit -m "live: news and general question types, answered without a verdict"
```

---

### Task 2: typo suggestions for Microsoft, Zoom, Teams, Slack

**Files:**
- Modify: `vendor.py`: a new module constant next to `_PRETTY`, used in `_closest`
- Test: `tests/test_live_sources.py`, in a new `# ─── typo suggestions` section at the end

**Interfaces:**
- Produces: `vendor.suggest("What happended to miscrosoft recently?") == "microsoft"`, and `vendor.known_products()` is unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_suggestion_only_names_resolve_typos_without_becoming_known():
    import vendor
    assert vendor.suggest("What happended to miscrosoft recently?") == "microsoft"
    assert vendor.suggest("Is zom better or teems?") in ("zoom", "teams")
    assert not {"microsoft", "zoom", "teams", "slack"} & set(vendor.known_products())
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `venv311/bin/python -m pytest tests/test_live_sources.py -k suggestion_only -q`
Expected: FAIL. `suggest` returns None.

- [ ] **Step 3: Implement**

Add `_SUGGEST_ONLY = ("microsoft", "zoom", "teams", "slack")` to `vendor.py`. Its comment says why these stay out of `known_products`: membership there exempts a name from the word-gap drop in `detect_vendors` (d60eeef). In `_closest`, the default catalog becomes `list(known_products()) + list(_SUGGEST_ONLY)`. A catalog the caller passes in is left unchanged.

- [ ] **Step 4: Run the test, then the no-bogus-suggestion check**

Run: `venv311/bin/python -m pytest tests/ -q -k "suggest or vendor"`
Expected: all pass.

Run:
```bash
venv311/bin/python -c "
import json,vendor; from grounding import ground
qs=[r.get('question') or r.get('query') for r in json.load(open('data/benchmark_500.json'))]
nop=[q for q in qs if q and not ground(q).vendors]
print(len(nop), sum(1 for q in nop if vendor.suggest(q)))"
```
Expected: `168 0`. On 2026-11-21 this measured 0 suggestions with the four names added. If it rises, drop the name causing it from `_SUGGEST_ONLY` and note that in the commit message.

- [ ] **Step 5: Commit**

```bash
git add vendor.py tests/test_live_sources.py
git commit -m "vendor: suggest Microsoft, Zoom, Teams, Slack for typos without making them known products"
```

---

### Task 3: console wiring, and a reroute count over the benchmark

**Files:**
- Modify: `app_1.py`: the `_NEEDS_LIVE` dict (around line 2090)
- Test: `tests/test_live_wiring.py`

**Interfaces:**
- Consumes: Task 1's `"news"` and `"general"` kinds and `answer_only`.
- Produces: with web search off, `app_1._needs_live_note(q, live=False)` returns the "turn on web search" note for `news` and `general` questions.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("q", ["What happened to Microsoft recently?", "What is Kubernetes?"])
def test_general_questions_need_web_search(q):
    assert "Web search" in app_1._needs_live_note(q, live=False)
    assert app_1._needs_live_note(q, live=True) is None

def test_update_question_is_not_sent_to_web_search():
    assert app_1._needs_live_note("Is it safe to update Chrome?", live=False) is None
```

Also add a run-pipeline test modelled on `test_answer_only_question_shows_no_verdict` (same `empty_lake` fixture and stubs): "Is zoom better or teams?" with web on gives `results["decision"] is None` and `results["live"]["kind"] == "compare"`.

- [ ] **Step 2: Run them to make sure they fail**

Run: `venv311/bin/python -m pytest tests/test_live_wiring.py -q`
Expected: the two `_needs_live_note` tests FAIL. The zoom pipeline test may already pass once Task 1 is in; that's fine.

- [ ] **Step 3: Implement**

Add these entries to `_NEEDS_LIVE`: `"news": "what's been happening recently"` and `"general": "a general software question"`. Nothing else changes: `_tab_short` and `run_pipeline` already handle any answer-only kind.

- [ ] **Step 4: Run the full suite**

Run: `venv311/bin/python -m pytest tests/ -q`
Expected: all pass, with no new failures compared with `main`. Before trusting the comparison, record main's baseline with `git stash` (or by checking out `main` in a scratch worktree).

- [ ] **Step 5: Reroute count**

Run:
```bash
venv311/bin/python -c "
import json,collections,live_sources as L; from grounding import ground
qs=[r.get('question') or r.get('query') for r in json.load(open('data/benchmark_500.json'))]
c=collections.Counter(L.kind(q, ground(q).vendor_names) for q in qs if q)
print({k:c[k] for k in ('news','general','compare')})"
```
Expected: `news` + `general` together come to about 20, matching the design's measure. Above 30 means a cue is too broad: list the extra questions and tighten the regex before committing.

- [ ] **Step 6: Live check in the console**

Start the app with `preview_start`, turn web search on in Settings, and ask the five design questions. For each, check:
- the headline is an answer, not a verdict;
- the caption reads "News question → DuckDuckGo news, last month" (or Comparison / General);
- "What happended to miscrosoft recently?" shows "Did you mean **Microsoft**?".

Take a screenshot of one answer.

- [ ] **Step 7: Commit**

```bash
git add app_1.py tests/test_live_wiring.py
git commit -m "console: news and general questions need web search; zoom-vs-teams gets no verdict"
```
