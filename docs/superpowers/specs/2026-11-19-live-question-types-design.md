# Live answers for non-update questions (console only) — design

## Why
The console answers update questions (latest version, what changed, CVEs) from the
releasetrain.io feeds. People also ask about outages, comparisons, package safety,
end of life, errors and compatibility. Today those get "no clear intent", and the
DuckDuckGo fallback is flaky, snippet-only and undated. Goal: in the console and
demo, every one of these gets a current answer with named sources, or an honest
"couldn't find it".

## Goals
- Recognise six new question types and answer each from a fixed live source.
- Show the type and the source on screen ("Outage question → GitHub status page").
- Tell "search blocked/failed" apart from "nothing found".

## Non-goals / anti-goals
- **The paper stays frozen.** `graph.py`, `decide.py`, `intent.py`, `grounding.py`,
  `multiagent_rag_v3.py` and `eval_harness/` do not change and never import the new
  module. A test enforces the import rule.
- No act/hold verdict for anything except package safety (type 4).
- Anti-goal: a web snippet ever producing a green light. Web text feeds the answer
  paragraph only, as today.
- Out of scope: the community feed ignoring `q` (releasetrain.io `/query/positive`
  returns the same posts for every query). That's an upstream bug, separate task.

## Approaches
- **A. Console-only router, picked.** One new `live_sources.py`: a rule-based type
  classifier plus one fixed source per type. Deterministic, testable offline, few
  network calls, type label is easy to show.
- B. Call every source on every question. Rejected: four extra calls per question
  worsen DuckDuckGo throttling, slower demo, noisy evidence.
- C. llama3.1 picks the type. Rejected: seconds per question, non-deterministic,
  llama3.1 has been unreliable at following instructions here.

## Question types and sources

| type | example | source | notes |
|---|---|---|---|
| `package_safety` | "Is the requests package safe?" | PyPI/npm registry for the latest version, then OSV `/v1/query` **with that version** | OSV without a version returns every historical advisory (16 for requests, all fixed), which would be a false red |
| `down_now` | "Is GitHub down?" | Statuspage `/api/v2/summary.json` from a hand list of hosts | Verified: github, npm, cloudflare, openai, reddit, vercel, docker, discord, atlassian. Products not on the list fall through to `incident` |
| `incident` | "What was the Microsoft outage about?" | `DDGS().news(q, timelimit="m")`, newest first, date on every row | Falls back to `text(q, timelimit="m")` if news is empty |
| `eol` | "Is Python 3.9 still supported?" | `endoflife.date/api/{slug}.json` | Slug from `api/all.json` (cached in-process) plus a small alias map (node→nodejs, postgres→postgresql, k8s→kubernetes). Cycle matched from the version in the question |
| `compare` | "Postgres or MySQL?" | DuckDuckGo text: one "A vs B" search | Changed from "one search per product": "Postgres" alone returns nothing useful |
| `howto` / `compat` | "Fix EACCES on npm install" / "Does Django 5 support Python 3.13?" | DuckDuckGo text; `compat` adds `timelimit="y"` | |
| none matched | anything else | today's behaviour, unchanged | |

## Verdict rule (type 4 only)
- **When it fires** *(my call)*: only with an explicit package cue ("package",
  "library", "module", "npm", "pip", "PyPI", "pip install X", "npm install X") **and**
  when grounding resolves no catalog vendor. "Is it safe to update Firefox?" stays on
  today's path, so an unrelated npm package named "firefox" can never reach the
  verdict. The other five types are additive (answer paragraph only) and may fire
  alongside a resolved vendor.
- **Which version** *(my call)*: the version named in the question if there is one,
  otherwise the latest from the registry. The clean message names the version checked.
- OSV advisories against that version go into the console's
  `results["decision_advisories"]` pool with `source: "cve"`, fetched **before**
  Step 6 (`graph.run`), because the verdict is decided there.
- **How rows are written** *(my call)*: text leads with "<package> <version>:" and
  includes the advisory's CVE aliases, because `decide` counts an advisory only when a
  CVE id appears in it (`_CVE_RE`, decide.py:442). OSV advisories with no CVE alias
  (GHSA/PYSEC only) are shown in the answer but don't reach the verdict.
  `ponytail:` known ceiling; lifting it needs a decide.py change, which is frozen.
  A test must show a requests row reaching the verdict for "Is requests 2.31.0 safe? (pip)"
  (the package cue is required, so the bare question doesn't fire).
  If `_about`'s two-token fallback blocks it, OSV is shown only, and the doc gets updated.
- `decide` turns any counted advisory into `patch_urgently` ("Patch now"); it never
  returns `hold` from advisories. That's right when a fixed release exists.
- **No fixed release** *(decided)*: an advisory against the checked version with no
  fixed version newer than it stays **out of the verdict pool**. The answer states it
  plainly ("requests 2.34.2: unfixed advisory GHSA-…, no fixed release yet"), and the
  verdict stays whatever the feeds support. Only advisories with a fix newer than the
  checked version go into `decision_advisories`, where "Patch now" is advice the user
  can follow.
- No change to `decide.py`. A clean OSV result does **not** create a green light. It
  shows as "OSV: no known advisories against requests 2.34.2", and the verdict stays
  whatever the feeds support (usually insufficient evidence). A false green costs more
  than a miss.
- The ecosystem comes from the question ("npm", "pip"/"PyPI", "python package",
  "node package"). If none is named, try PyPI then npm and show which one was used.
  If no package name can be pulled out of the question, type 4 doesn't fire.

## Vendor gate *(my call)*
`answer_agent.unresolved_products` declines an answer when a versioned product isn't
in the catalog ("Is left-pad 1.3.0 safe?"). A live source that resolved the product
**by name** (registry hit, endoflife.date slug hit, status-host match) counts as
resolving it, so the gate lets the answer through. A DuckDuckGo hit alone does not.

## Search hardening (`websearch.py`)
- One search helper used by everything: `search(query, limit, timelimit=None,
  news=False) -> (hits, error)`. One retry after ~2 s on exception or empty result.
  `_raw_search` stays as a thin wrapper so `fallback`/`trusted` and their tests keep
  working.
- `meta` gains `error`, so the console can say "search unavailable (rate-limited)"
  instead of "0 results".

## Wiring
- `run_pipeline` (app_1.py), behind the existing web-search toggle (default
  unchanged): `kind = live_sources.kind(query)`. For `package_safety` fetch OSV
  before Step 6. For the other types, fetch next to `websearch.trusted()` and append
  docs to `results["web"]`. Record `results["live"] = {kind, source, n, error}`.
- Every doc is screened and wrapped like today's web docs (`websearch._to_doc`), and
  carries a `label` ("Status page - githubstatus.com", "endoflife.date",
  "OSV", "News - The Verge, 2026-11-17").
- `answer_agent.collect_evidence` uses `w["label"]` when present.
- The console shows one line: "<Type> question → <source>", or the error.

## Tests
- `tests/test_live_sources.py`: one case per type through `kind()`, plus each
  fetcher with the network stubbed (including the OSV-with-version rule and
  search-failed ≠ empty).
- An import guard: none of the frozen paper modules import `live_sources`.

## Left to the builder
Cue wording for each type, the status-host list beyond the nine verified, the alias
map, the section heading for web evidence ("Vendor pages" may need renaming).
