# Component update-order ranking — 2026-10-15

Thirty ecosystem components ranked by update urgency. Live pull from
releasetrain.io, `scripts/component_stability_ranking.py`.

Two independent scores, reported side by side and deliberately not blended:

- **risk / sev** — this project's heuristic (`monitor.risk`): severity-weighted
  advisories in the trailing 90 days, plus a staleness term. `risk` caps at 100;
  `sev` is the same weighted sum uncapped, used only to order within that cap.
- **stability** — releasetrain.io's own 0–1 score (higher = more stable), read
  from the most recent scored row for that product. Nothing here has shown that
  a merged score beats either alone, so they stay separate.

Sorted by `risk` desc, then `sev` desc. Higher = update sooner.

| # | component | risk | sev | band | advisories (90d) | latest | age (d) | stability | scored rows |
|---:|---|---:|---:|---|---:|---|---:|---:|---:|
| 1 | wordpress | 100 | 3005 | Critical | 299 | 7.1.3 | 9 | 0.89 | 1/300 |
| 2 | linux | 100 | 773 | Critical | 126 | 7.37.0 | 3 | 0.75 | 55/181 |
| 3 | gitlab | 100 | 578 | Critical | 54 | 18.11.0 | 182 | 0.35 | 1/55 |
| 4 | windows | 100 | 481 | Critical | 43 | 10.0.28000 | 37 | 0.88 | 1/95 |
| 5 | android | 100 | 322 | Critical | 26 | 202658941.0.0 | 44 | 0.53 | 184/210 |
| 6 | kubernetes | 100 | 286 | Critical | 19 | 1.38.0 | 1 | 0.30 | 76/95 |
| 7 | postgresql | 100 | 207 | Critical | 16 | 18.6.0 | 63 | 0.75 | 1/17 |
| 8 | macos | 100 | 173 | Critical | 19 | 27.0.1 | 17 | 0.85 | 3/23 |
| 9 | docker | 100 | 167 | Critical | 11 | 29.9.0 | 7 | 0.75 | 4/15 |
| 10 | git | 100 | 160 | Critical | 12 | 2.56.0 | 17 | 0.75 | 1/14 |
| 11 | mysql | 97 | 97 | Critical | 7 | 26.7.0 | 79 | 0.75 | 42/49 |
| 12 | rust | 90 | 90 | Critical | 7 | 1.99.0 | 1 | 0.75 | 74/81 |
| 13 | chrome | 89 | 89 | Critical | 8 | 158.0.8105 | 1 | 0.90 | 287/295 |
| 14 | ios | 73 | 73 | High | 7 | 27.0.1 | 17 | 0.84 | 6/15 |
| 15 | ubuntu | 73 | 73 | High | 12 | 26.104.0 | 28 | 0.35 | 4/16 |
| 16 | firefox | 42 | 42 | Medium | 8 | 157.0.0 | 16 | 0.35 | 168/178 |
| 17 | debian | 15 | 15 | Low | 3 | 13.7.0 | 33 | 0.35 | 2/5 |
| 18 | arch | 12 | 12 | Low | 4 | — | — | n/a | 0/4 |
| 19 | grafana | 12 | 12 | Low | 2 | 13.2.4 | 0 | 0.90 | 70/73 |
| 20 | fedora | 3 | 3 | Low | 1 | 45.0.0 | 30 | 0.49 | 1/2 |
| 21 | safari | 0 | 0 | Low | 0 | 27.0.0 | 31 | 0.53 | 25/25 |
| 22 | edge ⚠ no data | 0 | 0 | Low | 0 | — | — | n/a | 0/0 |
| 23 | brave | 0 | 0 | Low | 0 | 1.97.57 | 1 | 0.90 | 8/8 |
| 24 | opera ⚠ no data | 0 | 0 | Low | 0 | — | — | n/a | 0/0 |
| 25 | node | 0 | 0 | Low | 0 | 26.12.0 | 0 | 0.75 | 76/76 |
| 26 | python | 0 | 0 | Low | 0 | 3.15.0 | 6 | 0.75 | 29/29 |
| 27 | home assistant ⚠ no data | 0 | 0 | Low | 0 | — | — | n/a | 0/0 |
| 28 | nextcloud | 0 | 0 | Low | 0 | 35.0.1 | 21 | 0.90 | 5/5 |
| 29 | mongodb ⚠ no data | 0 | 0 | Low | 0 | — | — | n/a | 0/0 |
| 30 | neovim | 0 | 0 | Low | 0 | 0.12.6 | 1 | 0.90 | 78/78 |

⚠ No rows returned for edge, opera, home assistant, mongodb.

## Regenerated after the advisory-attribution fix

This replaces an earlier 2026-10-15 table that counted advisories filed under
a component but belonging to a different product. On `isCve` rows the feed's
`versionProductName` is the ecosystem token the row was indexed under, not the
affected product: Backstage advisories arrived under `kubernetes`, Dokku under
`docker`, "Mocha Telnet Lite for iOS" under `ios`. `monitor.summarize()` now
drops an advisory when its own text positively names a different product
(`3d59ef6`, merged in #134).

114 of 798 ninety-day advisories were misattributed. Three components change
band and the top of the ranking reorders:

| component | advisories before → after | risk before → after | band |
|---|---|---|---|
| docker | 32 → 11 | 100 → 100 | — (rank 5 → 9) |
| git | 27 → 12 | 100 → 100 | — (rank 8 → 10) |
| kubernetes | 32 → 19 | 100 → 100 | — |
| chrome | 13 → 8 | 100 → **89** | Critical (held) |
| rust | 14 → 7 | 100 → **90** | Critical (held) |
| mysql | 11 → 7 | 100 → **97** | Critical (held) |
| ios | 9 → 7 | 100 → **73** | Critical → **High** |
| ubuntu | 13 → 12 | 79 → **73** | Critical → **High** |
| debian | 6 → 3 | 38 → **15** | Medium → **Low** |

The cap now ties 10 components rather than 14, so `sev` is doing less of the
ordering work than it was.

## Caveats

**The misattribution figure is a floor, not an estimate.** The filter only
fires when an advisory's text positively names some other product, and only
40–60% of advisory texts parse at all. The unparseable remainder is kept, so
an unknown number of foreign advisories are still counted. Treat every
advisory count here as an upper bound.

**Four components have no data at all.** `edge`, `opera`, `home assistant` and
`mongodb` returned zero rows from `/api/v/search`. Their score of 0 and band of
"Low" mean *the feed knows nothing about them*, not *they are safe to defer*.
They should be read as unranked. `arch` has 4 rows but none carry a stability
score. Do not cite ranks 22–29 as evidence that these components are stable.

**The score is a coverage proxy as much as a risk measure.** WordPress tops the
list at 299 advisories largely because its plugin ecosystem files CVEs per
plugin, so one "component" aggregates thousands of independent publishers.
Comparing its 3005 against the Linux kernel's 773 compares reporting
conventions, not attack surface. Note that WordPress is also the component the
attribution fix barely touched, because its advisories genuinely do name
WordPress plugins.

**`risk` saturates.** Ten of thirty components hit the 100 cap, so the headline
band separates nothing among them. Their ordering comes entirely from the
uncapped `sev` tiebreak, which is an unvalidated severity-weighted count, not a
calibrated risk model.

**Stability is sparsely scored and uses the latest scored row, not the latest
row.** The "scored rows" column gives the ratio. Where it reads 1/300
(wordpress) or 1/95 (windows), the stability figure rests on a single row that
may be considerably older than the listed release — a weak signal for those
components, a reasonable one for chrome (287/295) or neovim (78/78). The
denominator is the post-filter row count; the numerator is unaffected by the
filter in practice, since advisory rows almost never carry a stability score.

**Live, non-frozen pull.** These numbers move daily. Re-running will not
reproduce this table; the date in the filename is the only version marker.

## The `latest` column

`monitor.shipped()` orders releases by version number, not release date
(`b15bf77`). The feed backfills older builds under newer dates, so
date-ordering reported the backfilled row as current. Measured on the same
day's data that fix changes `latest` for 3 of 30 components:

| component | date-ordered (wrong) | version-ordered |
|---|---|---|
| linux | 7.2.0 | 7.37.0 |
| firefox | 156.0.0 | 157.0.0 |
| android | 202625294.0.0 | 202658941.0.0 |

## Note on the `/api/v/by-stability` endpoint

An earlier revision of the script sourced stability from
`/api/v/by-stability`, joining it to components by product name. That endpoint
returns **100 rows covering 8 distinct products regardless of the `limit`
parameter** — a request for `limit=2000` still yields 100. Twenty-nine of the
thirty components are absent from it, so the column was structurally `n/a` and
the single value it did produce was a false match (`macos` scored 0.15 from an
unrelated row; its actual stability is 0.85).

Every row from `/api/v/search` already carries its own `stability` field, which
is what this table uses. `fetch_by_stability` and `match_rt_stability` have
been deleted; `latest_stability` replaces them and also returns the scored-row
count shown in the last column.

Separately: the `word_match` product filter once added to `fetch_component_rows`
was a verified no-op. `/api/v/search?q=<name>` is already product-scoped — every
`q=linux` row has `versionProductName == "linux"`. The comment claiming it
de-pooled "six distinct products" described a bug that was not occurring. The
filter and the helper have both been removed.

## A second ranking: rollout sequencing, not patch urgency

The table above answers "how much known-vulnerability exposure has this
component accumulated" — higher `risk`/`sev` means more unpatched advisory
weight sitting on it right now. Asked separately (an SRE/infra-architect
framing, Claude Sonnet 5, single conversational pass, no retrieval) was a
different question: **in what order should these 30 be rolled through an
update cycle to minimize cascading failure and reboot outages** — i.e. blast
radius and dependency position, not CVE backlog. The two are not competing
predictions of the same value, so a big delta below is not a disagreement.

| component | risk/sev rank | rollout-order rank | Δ | rollout-order rationale |
|---|---:|---:|---:|---|
| neovim | 30 | 1 | +29 | single-user editor, no dependents, instant revert |
| linux | 2 | 30 | −28 | kernel everything else runs on; most dependents, hardest rollback |
| brave | 23 | 3 | +20 | sandboxed consumer browser, isolated per device |
| windows | 4 | 29 | −25 | broad fleet, boot-failure risk, hard rollback |
| safari | 21 | 2 | +19 | sandboxed consumer browser, isolated per device |
| opera | 24 | 5 | +19 | isolated browser, smallest install base here |
| android | 5 | 26 | −21 | large fleet, though vendor-staged rollout tempers it |
| macos | 8 | 28 | −20 | desktop/server fleet, hard rollback |
| kubernetes | 6 | 25 | −19 | orchestrates many hosts at once, cluster-wide blast radius |
| python | 26 | 9 | +17 | interpreter regressions stay in dev/build until something depends on the new version |
| mongodb | 29 | 13 | +16 | no listed app confirmed to depend on it specifically |
| node | 25 | 10 | +15 | same as python: dev-environment risk only, pre-deployment |
| docker | 9 | 24 | −15 | single-host runtime, but every container on that host is exposed |
| edge | 22 | 4 | +18 | sandboxed consumer browser, isolated per device |
| ios | 14 | 27 | −13 | Apple's rollout is closer to all-at-once than Android's |
| home assistant | 27 | 16 | +11 | single app, contained blast radius |
| nextcloud | 28 | 17 | +11 | single app, contained blast radius |
| firefox | 16 | 7 | +9 | sandboxed browser, but Gecko has broken extensions/policy more than Chromium forks historically |
| chrome | 13 | 6 | +7 | sandboxed, but widest browser install base here |
| grafana | 19 | 12 | +7 | update before the risky infra below so telemetry is live for the rest of the rollout |
| postgresql | 7 | 15 | −8 | GitLab's datastore; validate before GitLab updates |
| ubuntu | 15 | 23 | −8 | widest distro footprint; goes after its upstream Debian |
| debian | 17 | 22 | −5 | base many images inherit from |
| mysql | 11 | 14 | −3 | WordPress/Nextcloud can sit on it; validate before those |
| arch | 18 | 20 | −2 | rolling release, smallest/most isolated install base |
| fedora | 20 | 21 | −1 | faster cadence catches packaging regressions early |
| rust | 12 | 11 | +1 | no running service here is built on it |
| git | 10 | 8 | +2 | CLI only; nothing here calls it as a running service |
| gitlab | 3 | 19 | −16 | depends on postgresql + git; also the CI/CD system teams rely on |
| wordpress | 1 | 18 | −17 | depends on mysql; plugin ecosystem makes it the most failure-prone app here |

**Why the sign flips for the browsers/editor vs. the OS/kernel/orchestration
layer**: `risk`/`sev` is near-zero for `neovim`/`safari`/`brave`/`edge`/`opera`
largely because the advisory feed has little or nothing filed against them
(see the "four components have no data at all" caveat above — three of those
four, `edge`/`opera`/`home assistant`/`mongodb`, are the ones with the biggest
positive deltas here too, for the same underlying reason: no signal either
way). Low advisory volume reads as "not urgent to patch" in the heuristic and
as "safe to patch first" in the rollout framing — same input, opposite
reasons, same direction. `linux`/`windows`/`macos`/`kubernetes` diverge for
the opposite reason: real advisory volume drives `risk`/`sev` up, while blast
radius and rollback difficulty drive rollout order down (later).

**This ranking is a single model's reasoning, not a measurement.** It was
produced in one conversational pass with no retrieval, no cross-model check,
and no scoring script — contrast with `scripts/rank_components_llm.py`
(present in this checkout, not yet run against live API keys), which asks
ChatGPT, Gemini, and local Ollama the same question independently and reports
Spearman/Kendall agreement. Treat the table above as one qualitative opinion
worth sanity-checking against that script's output, not as a second data
point of the same weight as the `risk`/`sev` pull.
