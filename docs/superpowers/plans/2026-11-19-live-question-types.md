# Live Question Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The console recognises six new question types (package safety, down now, past incident, end of life, comparison, how-to/compatibility) and answers each from a fixed live source, with the type and source shown on screen.

**Architecture:** A new console-only module `live_sources.py` holds the type classifier (`kind`), the per-type fetchers (`fetch`) and the package-safety check (`package_safety`). `websearch.py` gains one hardened search helper. `app_1.run_pipeline` calls the module behind the existing web-search toggle. Package advisories with a fix go into the console's verdict pool before Step 6; everything else only feeds `results["web"]`, which `answer_agent` already cites.

**Tech Stack:** Python 3.11, `ddgs` 9.16.1 (installed), `requests` 2.34.2 (installed), `packaging.version` (installed as a transitive dependency), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-19-live-question-types-design.md`

## Global Constraints

- **The paper stays frozen.** No edits to `graph.py`, `decide.py`, `intent.py`, `grounding.py`, `multiagent_rag_v3.py` or `eval_harness/`. None of them may import `live_sources`. Reading `graph._COMPARE_RE` from `live_sources` is fine (that direction doesn't touch the paper).
- Everything new runs only when the web-search toggle is on (`checks["web_search"]` / `MARAG_WEB_FALLBACK=1`). Default unchanged.
- Web text never creates a green light. Only OSV advisories that have a fixed version newer than the checked version, and that carry a CVE alias, enter `results["decision_advisories"]`.
- Every web/API doc goes through `websearch._to_doc` (screen + scrub + `[untrusted:community]` wrap), then gets `label`, `source`, `host`, `date` set.
- Tests are offline (`tests/conftest.py` blocks sockets). Stub `websearch.search` and `live_sources._get_json`.
- Status hosts verified 2026-11-19: `github: www.githubstatus.com`, `npm: status.npmjs.org`, `cloudflare: www.cloudflarestatus.com`, `openai: status.openai.com`, `reddit: www.redditstatus.com`, `vercel: www.vercel-status.com`, `docker: www.dockerstatus.com`, `discord: discordstatus.com`, `atlassian: status.atlassian.com`. Endpoint: `https://<host>/api/v2/summary.json`.
- endoflife.date: `https://endoflife.date/api/all.json` (slug list), `https://endoflife.date/api/{slug}.json` (cycles: `cycle`, `eol`, `latest`, `support`). Aliases: `node→nodejs`, `node.js→nodejs`, `postgres→postgresql`, `k8s→kubernetes`.
- Registries: PyPI `https://pypi.org/pypi/{name}/json` → `info.version`; npm `https://registry.npmjs.org/{name}/latest` → `version`. OSV: POST `https://api.osv.dev/v1/query` with `{"version": v, "package": {"name": n, "ecosystem": "PyPI"|"npm"}}`.
- No `Co-Authored-By` trailer on commits. Check no keys or `secrets.toml` are staged before every commit.
- Work happens in a fresh worktree off `origin/main` (another session is using the main checkout). The first commit adds the spec and this plan.

## Review Focus

1. A DuckDuckGo news hit with no `date` → the row is shown without a date and sorted last, with no crash. (Task 3 test `test_incident_undated_hit_sorts_last`.)
2. A product that isn't on endoflife.date ("Is Bun 1.2 still supported?" when the slug list lacks it) → falls back to a DuckDuckGo text search for "<product> end of life", with `resolved=False`. (Task 3 test `test_eol_unknown_slug_falls_back_to_web`.)
3. A status page that returns non-JSON or a 5xx (status.gitlab.com does today) → `meta["error"]` is set and the question falls through to the `incident` news search. (Task 3 test `test_status_page_failure_falls_back_to_incident`.)
4. A package name on both PyPI and npm with no ecosystem in the question → PyPI is used, and `meta["source"]` says so. (Task 4 test `test_no_ecosystem_prefers_pypi`.)
5. A question matching two types ("Is GitHub down, should I switch to GitLab?") → a fixed precedence picks `down_now`. (Task 2 test `test_precedence_down_now_over_compare`.)

---

### Task 0: Worktree and docs commit

- [ ] **Step 1:** `git fetch origin && git worktree add ../marag-live -b feat/live-question-types origin/main`
- [ ] **Step 2:** Copy `docs/superpowers/specs/2026-11-19-live-question-types-design.md` and this plan into the worktree at the same paths.
- [ ] **Step 3:** Commit.

```bash
git add docs/superpowers/specs/2026-11-19-live-question-types-design.md docs/superpowers/plans/2026-11-19-live-question-types.md
git commit -m "docs: design and plan for live question types in the console"
```

---

### Task 1: Hardened search helper

**Files:**
- Modify: `websearch.py` (`_raw_search`, add `search`)
- Test: `tests/test_websearch_search.py`

**Interfaces:**
- Produces: `websearch.search(query: str, limit: int = MAX_RESULTS, timelimit: str | None = None, news: bool = False) -> tuple[list[dict], str | None]`. The error is `None` on success, including a real empty result. On failure it is `"search failed: <ExceptionName>"`, or `"no backend"` when ddgs isn't importable. News hits keep ddgs's keys (`date`, `title`, `body`, `url`, `source`).
- Produces: module-level `_sleep = time.sleep` (patched in tests).
- `_raw_search(query, limit)` becomes `return search(query, limit)[0]`.

- [ ] **Step 1: Write failing tests**

```python
def test_retries_once_after_exception(monkeypatch):
    calls = []
    def boom_then_ok(q, limit, timelimit, news):
        calls.append(q)
        if len(calls) == 1:
            raise RuntimeError("ratelimit")
        return [{"title": "t", "body": "b", "href": "https://x.org"}]
    monkeypatch.setattr(websearch, "_ddg", boom_then_ok)
    monkeypatch.setattr(websearch, "_sleep", lambda s: None)
    hits, err = websearch.search("q")
    assert len(calls) == 2 and err is None and len(hits) == 1

def test_two_failures_report_error_not_empty(monkeypatch):
    def boom(*a): raise RuntimeError("ratelimit")
    monkeypatch.setattr(websearch, "_ddg", boom)
    monkeypatch.setattr(websearch, "_sleep", lambda s: None)
    assert websearch.search("q") == ([], "search failed: RuntimeError")

def test_empty_twice_is_a_real_miss(monkeypatch):
    monkeypatch.setattr(websearch, "_ddg", lambda *a: [])
    monkeypatch.setattr(websearch, "_sleep", lambda s: None)
    assert websearch.search("q") == ([], None)

def test_news_and_timelimit_are_passed_through(monkeypatch):
    seen = {}
    monkeypatch.setattr(websearch, "_ddg", lambda q, l, t, n: seen.update(t=t, n=n) or [{"title": "x"}])
    websearch.search("q", timelimit="m", news=True)
    assert seen == {"t": "m", "n": True}
```

- [ ] **Step 2:** Run `venv311/bin/python -m pytest tests/test_websearch_search.py -v`. Expected: FAIL (`search` not defined).
- [ ] **Step 3: Implement.** Add `_ddg(query, limit, timelimit, news) -> list[dict]`, which opens `DDGS()` and calls `.news(...)` or `.text(...)` with `max_results=limit` and `timelimit` (omit the kwarg when `None`). Exceptions propagate. Then `search` calls `_ddg`, and on an exception or an empty list calls `_sleep(2)` and tries once more. Rewrite `_raw_search` as the wrapper above.
- [ ] **Step 4:** Run the new tests plus `tests/test_trusted_answer.py` (it runs `websearch._demo()`). Expected: PASS.
- [ ] **Step 5:** `fallback()` and `trusted()` return `meta["error"]` from `search` (swap their `_raw_search` calls to `search`). Add `assert "error" in meta` to `_demo` for both. Re-run step 4.
- [ ] **Step 6: Commit** — `git commit -m "websearch: one retry, and a failed search reports an error instead of 0 results"`

---

### Task 2: Question-type classifier

**Files:**
- Create: `live_sources.py`
- Test: `tests/test_live_sources.py`

**Interfaces:**
- Produces: `KINDS = ("package_safety", "down_now", "incident", "eol", "compare", "compat", "howto")`. Tuple order is the precedence: the first type whose cues match wins.
- Produces: `kind(query: str, vendors: Sequence[str] = ()) -> str | None`.
- Produces: `package_ref(query: str) -> tuple[str, str | None, str | None] | None`, i.e. `(name, ecosystem, version)` with ecosystem `"PyPI"`, `"npm"` or `None`.
- Produces: `STATUS_HOSTS: dict[str, str]` (the nine hosts in Global Constraints) and `status_product(query) -> str | None`.
- Produces: `KIND_LABEL = {"package_safety": "Package safety", "down_now": "Is it down", "incident": "Incident", "eol": "End of life", "compare": "Comparison", "compat": "Compatibility", "howto": "How-to"}`.

- [ ] **Step 1: Write failing tests**

```python
import pytest, live_sources as L

@pytest.mark.parametrize("q,want", [
    ("Is the requests package safe to use?", "package_safety"),
    ("is lodash npm safe", "package_safety"),
    ("Is requests 2.31.0 safe? (pip)", "package_safety"),
    ("Is GitHub down?", "down_now"),
    ("is openai down right now", "down_now"),
    ("What was the Microsoft outage about?", "incident"),
    ("Is Azure down?", "incident"),            # no status host -> incident
    ("Is Python 3.9 still supported?", "eol"),
    ("When is Node 20 end of life?", "eol"),
    ("Should I use Postgres or MySQL for a new project?", "compare"),
    ("Does Django 5 support Python 3.13?", "compat"),
    ("How do I fix EACCES on npm install?", "howto"),
    ("What is the latest Linux version?", None),
    ("Any critical CVEs in Chrome?", None),
])
def test_kind(q, want):
    assert L.kind(q) == want

def test_package_safety_never_fires_for_a_catalog_vendor():
    assert L.kind("Is the firefox package safe?", vendors=["firefox"]) != "package_safety"

def test_safe_to_update_without_package_cue_is_not_package_safety():
    assert L.kind("Is it safe to update Firefox right now?") is None

def test_precedence_down_now_over_compare():
    assert L.kind("Is GitHub down, should I switch to GitLab?") == "down_now"

@pytest.mark.parametrize("q,want", [
    ("Is the requests package safe to use?", ("requests", None, None)),
    ("Is requests 2.31.0 safe? (pip)", ("requests", "PyPI", "2.31.0")),
    ("npm install left-pad 1.3.0 safe?", ("left-pad", "npm", "1.3.0")),
    ("Is it safe?", None),
])
def test_package_ref(q, want):
    assert L.package_ref(q) == want

def test_frozen_paper_modules_do_not_import_live_sources():
    import pathlib, re
    root = pathlib.Path(L.__file__).parent
    frozen = ["graph.py", "decide.py", "intent.py", "grounding.py", "multiagent_rag_v3.py",
              *[str(p.relative_to(root)) for p in (root / "eval_harness").rglob("*.py")]]
    for f in frozen:
        assert not re.search(r"\bimport live_sources\b|\bfrom live_sources\b", (root / f).read_text()), f
```

- [ ] **Step 2:** Run `venv311/bin/python -m pytest tests/test_live_sources.py -v`. Expected: FAIL (no module).
- [ ] **Step 3: Implement** `kind`, `package_ref` and `status_product` with compiled regex cues (wording is the builder's call; the tests pin the behaviour). `compare` reuses `graph._COMPARE_RE`. `down_now` needs a "down / not working / outage now / today" cue **and** `status_product(query)`; the same cue without a status product is `incident`. `package_safety` needs a package cue ("package", "library", "module", "npm", "pip", "pypi", "pip install X", "npm install X") **and** a `package_ref`, **and** `vendors` empty. Add a module docstring stating it is console-only, plus a `ponytail:` note that cues are hand rules and misses fall through to today's behaviour.
- [ ] **Step 4:** Re-run. Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "live_sources: question-type classifier (console only)"`

---

### Task 3: Fetchers for the five answer-only types

**Files:**
- Modify: `live_sources.py`
- Test: `tests/test_live_sources.py`

**Interfaces:**
- Consumes: `websearch.search`, `websearch._to_doc`, `kind`, `status_product`.
- Produces: `_get_json(url: str, post: dict | None = None, timeout: int = 10) -> tuple[dict | list | None, str | None]` (uses `requests`, and returns an error string instead of raising).
- Produces: `fetch(kind: str, query: str) -> tuple[list[dict], dict]`. Meta keys: `kind`, `source` (human text, e.g. `"GitHub status page"`, `"endoflife.date"`, `"DuckDuckGo news, last month"`), `n`, `error` (`str | None`), `resolved` (`bool`: the product was found by name in a structured source).
- Every doc has `label` (e.g. `"Status page - githubstatus.com"`, `"endoflife.date - python 3.9"`, `"News - The Verge, 2026-11-17"`), `source="live"`, `url`, `date`, `host`.

Per type:
- `down_now`: `_get_json(summary.json)` → one doc: `status.description`, then each `incidents[]` `name — status (updated_at)`. On an error, run `fetch("incident", query)` and keep the status error in `meta["error"]`.
- `incident`: `search(query, timelimit="m", news=True)`; if empty, `search(query, timelimit="m")`. Newest first, undated rows last.
- `eol`: slug from `all.json` (`functools.lru_cache` on the fetch) plus aliases; cycle matched by the question's version (`3.9`, `20`). The doc reads `"Python 3.9: end of life 2025-10-31, latest 3.9.25"`. If no slug matches, `search("<product> end of life")` with `resolved=False`.
- `compare`: `search(query)`.
- `compat`: `search(query, timelimit="y")`.
- `howto`: `search(query)`.

- [ ] **Step 1: Write failing tests** (stub `L._get_json` and `websearch.search` with monkeypatch)

```python
def test_down_now_reads_status_page(monkeypatch):
    monkeypatch.setattr(L, "_get_json", lambda url, **k: ({"status": {"description": "Partial Outage"},
        "incidents": [{"name": "Actions delayed", "status": "investigating", "updated_at": "2026-11-19T10:00:00Z"}]}, None))
    docs, meta = L.fetch("down_now", "Is GitHub down?")
    assert meta["resolved"] and meta["error"] is None and meta["source"] == "GitHub status page"
    assert "Partial Outage" in docs[0]["text"] and "Actions delayed" in docs[0]["text"]
    assert docs[0]["label"] == "Status page - githubstatus.com"

def test_status_page_failure_falls_back_to_incident(monkeypatch):
    monkeypatch.setattr(L, "_get_json", lambda url, **k: (None, "HTTP 503"))
    monkeypatch.setattr(websearch, "search", lambda q, limit=5, timelimit=None, news=False:
        ([{"title": "GitHub outage", "body": "b", "url": "https://n.com/a", "date": "2026-11-19T09:00:00+00:00", "source": "N"}], None))
    docs, meta = L.fetch("down_now", "Is GitHub down?")
    assert docs and "HTTP 503" in meta["error"]

def test_incident_newest_first_with_dates(monkeypatch): ...      # two dated hits -> sorted desc, label "News - <source>, <YYYY-MM-DD>"
def test_incident_undated_hit_sorts_last(monkeypatch): ...       # one hit without "date" -> last, label has no date
def test_eol_reads_cycle(monkeypatch): ...                       # all.json ["python"], python.json cycle 3.9 eol 2025-10-31 -> text contains "end of life 2025-10-31", resolved True
def test_eol_alias_postgres(monkeypatch): ...                    # "Is Postgres 13 still supported?" -> requests .../postgresql.json
def test_eol_unknown_slug_falls_back_to_web(monkeypatch): ...    # all.json lacks "bun" -> search called with "bun end of life", resolved False
def test_search_error_reaches_meta(monkeypatch): ...             # search returns ([], "search failed: RuntimeError") -> meta["error"] == that string, docs == []
```

The implementer writes the bodies of the `...` tests from the one-line assertions given.

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `_get_json` and `fetch` as specified above.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "live_sources: status page, endoflife.date and dated web fetchers"`

---

### Task 4: Package safety (OSV)

**Files:**
- Modify: `live_sources.py`
- Test: `tests/test_live_sources.py`

**Interfaces:**
- Consumes: `package_ref`, `_get_json`, `websearch._to_doc`.
- Produces: `package_safety(query: str) -> dict` with keys:
  - `verdict_docs: list[dict]`: advisories that have a CVE alias **and** a `fixed` event newer than the checked version (`packaging.version.Version`). Each has `source="cve"`, `title=<OSV id>`, `url="https://osv.dev/vulnerability/<id>"`, and `text` leading with `"<name> <version>: "`, then the CVE aliases, then the summary, then `"Fixed in <v>."`.
  - `answer_docs: list[dict]`: one doc per advisory (all of them, including unfixed and no-CVE), labelled `"OSV - <id>"`. Unfixed ones read `"<name> <version>: unfixed advisory <id>, no fixed release yet. <summary>"`. With no advisories, a single doc reads `"OSV: no known advisories against <name> <version>"`.
  - `meta`: `kind="package_safety"`, `source` (e.g. `"OSV via PyPI, requests 2.34.2"`), `n`, `error`, `resolved` (registry hit).
- Version: the version from the question if there is one, else the registry's latest. Ecosystem: from the question, else try PyPI, then npm.

- [ ] **Step 1: Write failing tests** (stub `_get_json` with a URL→response dict)

```python
REQ = "Is requests 2.31.0 safe? (pip)"
def osv(*vulns): return {"vulns": list(vulns)}
FIXED = {"id": "GHSA-9wx4-h78v-vm56", "aliases": ["CVE-2024-35195"], "summary": "Session verify bypass",
         "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.32.0"}]}]}]}
UNFIXED = {"id": "GHSA-aaaa", "aliases": ["CVE-2026-1"], "summary": "x",
           "affected": [{"ranges": [{"events": [{"introduced": "0"}]}]}]}
NO_CVE = {"id": "PYSEC-2026-1", "aliases": [], "summary": "y",
          "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.32.0"}]}]}]}

def test_fixed_cve_advisory_reaches_verdict(stub):        # stub OSV -> osv(FIXED)
    r = L.package_safety(REQ)
    assert [d["title"] for d in r["verdict_docs"]] == ["GHSA-9wx4-h78v-vm56"]
    assert r["verdict_docs"][0]["text"].startswith("requests 2.31.0: ") and "CVE-2024-35195" in r["verdict_docs"][0]["text"]
    assert r["verdict_docs"][0]["source"] == "cve"

def test_unfixed_advisory_stays_out_of_verdict(stub):     # osv(UNFIXED)
    r = L.package_safety(REQ)
    assert r["verdict_docs"] == [] and "no fixed release yet" in r["answer_docs"][0]["text"]

def test_no_cve_advisory_is_shown_only(stub):             # osv(NO_CVE)
    r = L.package_safety(REQ)
    assert r["verdict_docs"] == [] and r["answer_docs"][0]["label"] == "OSV - PYSEC-2026-1"

def test_clean_result_is_not_a_green_light(stub):         # osv() and no version in question; PyPI latest 2.34.2
    r = L.package_safety("Is the requests package safe?")
    assert r["verdict_docs"] == []
    assert "no known advisories against requests 2.34.2" in r["answer_docs"][0]["text"]

def test_question_version_is_checked_not_latest(stub):    # assert the OSV POST body carried "2.31.0"
def test_no_ecosystem_prefers_pypi(stub):                 # PyPI and npm both resolve -> meta["source"] starts "OSV via PyPI"
def test_unknown_package_is_unresolved(stub):             # both registries 404 -> resolved False, verdict_docs [], meta["error"] set
def test_osv_failure_is_an_error_not_clean(stub):         # OSV returns (None, "timeout") -> no "no known advisories" doc, meta["error"] == "timeout"
```

The `stub` fixture monkeypatches `L._get_json` with a dict keyed by URL, recording POST bodies.

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `package_safety` as specified above.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "live_sources: OSV package check; only fixed CVE advisories reach the verdict"`

---

### Task 5: Wire into the console

**Files:**
- Modify: `app_1.py`: `run_pipeline` (grounding at ~956, before `# Step 6 — Decision Gate` at ~1255, the trusted-search block at ~1309), `ask` (fast-path line at ~2322), the trace panel (after the `wf` lines at ~2307)
- Modify: `answer_agent.py`: `collect_evidence` web loop (~557), `unresolved_products` (~829)
- Test: `tests/test_live_wiring.py`

**Interfaces:**
- Consumes: `live_sources.kind`, `live_sources.fetch`, `live_sources.package_safety`, `live_sources.KIND_LABEL`.
- Produces: `results["live"]: dict | None` (the meta from Task 3/4).

Changes:
1. In `run_pipeline`, after grounding: `live_kind = live_sources.kind(query, g.vendor_names) if web_fallback else None`, and `results["live"] = None`.
2. Before Step 6, if `live_kind == "package_safety"`: call `package_safety(query)`, extend `results["decision_advisories"]` with `verdict_docs`, extend `results["web"]` with `answer_docs`, and set `results["live"] = meta`.
3. The trusted block currently **overwrites** `results["web"]` (line ~1314). Change it to append: `results["web"] = (results.get("web") or []) + web_docs`.
4. After the trusted block, if `live_kind` is set and isn't `package_safety`: call `fetch(live_kind, query)`, append the docs to `results["web"]`, and set `results["live"] = meta`.
5. In `ask`: take the fast path only when `live_sources.kind(q) is None` or web search is off. An EOL question must not be answered with "latest version is …".
6. In `collect_evidence`: `label = w.get("label") or <existing label expression>`.
7. In `unresolved_products`: `if (results.get("live") or {}).get("resolved"): return []`, placed before the catalog checks.
8. In the trace panel: when `results.get("live")` is set, show `**Live source:** <KIND_LABEL> question → <source>, <n> result(s)`, followed by ` — <error>` when there is one.

- [ ] **Step 1: Write failing tests** (offline: stub the three feed fetchers on `app_1` the way `tests/test_app_decision.py` does, and stub the `live_sources` functions)

```python
def test_osv_fixed_advisory_moves_the_verdict(stubbed_app):
    # package_safety stub returns one verdict_doc for requests 2.31.0 with CVE-2024-35195
    r = app_1.run_pipeline("Is requests 2.31.0 safe? (pip)", show_steps=False, checks={"web_search": True})
    assert r["decision"]["verdict"] == "patch_urgently"
    assert r["live"]["kind"] == "package_safety"

def test_firefox_safety_stays_on_the_feed_path(stubbed_app):
    r = app_1.run_pipeline("Is it safe to update Firefox right now?", show_steps=False, checks={"web_search": True})
    assert r["live"] is None

def test_web_off_means_no_live_calls(stubbed_app):
    # live_sources stubs raise if called
    app_1.run_pipeline("Is GitHub down?", show_steps=False, checks={"web_search": False})

def test_trusted_and_live_docs_both_kept(stubbed_app):    # trusted returns 1 doc, fetch returns 1 -> len(r["web"]) == 2
def test_live_label_is_used_as_evidence_label():           # collect_evidence({"web": [{"label": "Status page - githubstatus.com", ...}]})[0].label == that
def test_resolved_live_source_passes_vendor_gate():        # unresolved_products("Is left-pad 1.3.0 safe?", {"grounding": g_no_vendor, "live": {"resolved": True}}) == []
def test_eol_question_skips_fast_path(stubbed_app):        # ask("Is Python 3.9 still supported?", checks={"web_search": True}) never calls run_fast
```

- [ ] **Step 2:** Run `venv311/bin/python -m pytest tests/test_live_wiring.py -v`. Expected: FAIL.
- [ ] **Step 3:** Make changes 1–8.
- [ ] **Step 4:** Run the new tests. Expected: PASS. **If `test_osv_fixed_advisory_moves_the_verdict` fails because `decide._about` rejects the row** (no vendor, two-token fallback), don't touch `decide.py`. Stop, report it, and drop change 2's `decision_advisories` line (OSV becomes shown-only) after the user agrees. The spec says this.
- [ ] **Step 5:** Run the full suite with `venv311/bin/python -m pytest -q`. Expected: same pass/fail count as `origin/main` before the branch, plus the new tests.
- [ ] **Step 6: Commit** — `git commit -m "console: route outage, EOL, comparison, how-to and package questions to live sources"`

---

### Task 6: Live check in the console

- [ ] **Step 1:** Start the console with `MARAG_WEB_FALLBACK=1` (see `docs/Running-the-System.md`) and ask, one per type: "Is GitHub down?", "What was the Microsoft outage about?", "Is Python 3.9 still supported?", "Postgres or MySQL for a new project?", "Does Django 5 support Python 3.13?", "Is the requests package safe to use?", "Is requests 2.31.0 safe? (pip)", "Is it safe to update Firefox right now?".
- [ ] **Step 2:** For each, record the type line, the sources cited and the verdict. Expected: the first six show their live source. 2.31.0 shows "Patch now" citing an OSV advisory. Firefox shows no live line and the same verdict as on `origin/main`.
- [ ] **Step 3:** Screenshot the trace panel for two questions as proof.
