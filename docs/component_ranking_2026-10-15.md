# Component update-order ranking — 2026-10-15

Thirty ecosystem components ranked by update urgency. Live pull from
releasetrain.io, `scripts/component_stability_ranking.py`.

Two independent scores, reported side by side and deliberately not blended:

- **risk / sev** — this project's heuristic (`monitor.risk`): severity-weighted
  advisories in the trailing 90 days, plus a staleness term. `risk` caps at 100,
  which ties the top 14; `sev` is the same weighted sum uncapped, used only to
  order within that tie.
- **stability** — releasetrain.io's own 0–1 score (higher = more stable), read
  from the most recent scored row for that product. Nothing here has shown that
  a merged score beats either alone, so they stay separate.

Sorted by `risk` desc, then `sev` desc. Higher = update sooner.

| # | component | risk | sev | band | advisories (90d) | latest | age (d) | stability | scored rows |
|---:|---|---:|---:|---|---:|---|---:|---:|---:|
| 1 | wordpress | 100 | 3005 | Critical | 299 | 7.1.3 | 9 | 0.89 | 1/300 |
| 2 | linux | 100 | 907 | Critical | 136 | 7.37.0 | 3 | 0.75 | 55/191 |
| 3 | gitlab | 100 | 630 | Critical | 58 | 18.11.0 | 182 | 0.35 | 1/59 |
| 4 | windows | 100 | 613 | Critical | 56 | 10.0.28000 | 37 | 0.88 | 1/108 |
| 5 | docker | 100 | 467 | Critical | 32 | 29.9.0 | 7 | 0.75 | 4/36 |
| 6 | kubernetes | 100 | 424 | Critical | 32 | 1.38.0 | 1 | 0.30 | 76/108 |
| 7 | android | 100 | 374 | Critical | 30 | 202658941.0.0 | 44 | 0.53 | 184/214 |
| 8 | git | 100 | 360 | Critical | 27 | 2.56.0 | 17 | 0.75 | 1/29 |
| 9 | postgresql | 100 | 294 | Critical | 23 | 18.6.0 | 63 | 0.75 | 1/24 |
| 10 | macos | 100 | 215 | Critical | 23 | 27.0.1 | 17 | 0.85 | 3/27 |
| 11 | mysql | 100 | 158 | Critical | 11 | 26.7.0 | 79 | 0.75 | 42/53 |
| 12 | rust | 100 | 142 | Critical | 14 | 1.99.0 | 1 | 0.75 | 74/88 |
| 13 | chrome | 100 | 124 | Critical | 13 | 158.0.8105 | 1 | 0.90 | 287/300 |
| 14 | ios | 100 | 113 | Critical | 9 | 27.0.1 | 17 | 0.84 | 6/17 |
| 15 | ubuntu | 79 | 79 | Critical | 13 | 26.104.0 | 28 | 0.35 | 4/17 |
| 16 | firefox | 44 | 44 | Medium | 9 | 157.0.0 | 16 | 0.35 | 168/179 |
| 17 | debian | 38 | 38 | Medium | 6 | 13.7.0 | 33 | 0.35 | 2/8 |
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

## Caveats

**Four components have no data at all.** `edge`, `opera`, `home assistant` and
`mongodb` returned zero rows from `/api/v/search`. Their score of 0 and band of
"Low" mean *the feed knows nothing about them*, not *they are safe to defer*.
They should be read as unranked. `arch` has 4 rows but none carry a stability
score. Do not cite ranks 22–29 as evidence that these components are stable.

**The score is a coverage proxy as much as a risk measure.** WordPress tops the
list at 299 advisories largely because its plugin ecosystem files CVEs per
plugin, so one "component" aggregates thousands of independent publishers.
Comparing its 3005 against the Linux kernel's 907 compares reporting
conventions, not attack surface.

**`risk` saturates.** Fourteen of thirty components hit the 100 cap, so the
headline band separates almost nothing at the top. The ordering within those
fourteen comes entirely from the uncapped `sev` tiebreak, which is an unvalidated
severity-weighted count, not a calibrated risk model.

**Stability is sparsely scored and uses the latest scored row, not the latest
row.** The "scored rows" column gives the ratio. Where it reads 1/300
(wordpress) or 1/108 (windows), the stability figure rests on a single row that
may be considerably older than the listed release — it is a weak signal for
those components and a reasonable one for chrome (287/300) or neovim (78/78).

**Live, non-frozen pull.** These numbers move daily. Re-running will not
reproduce this table; the date in the filename is the only version marker.

## The `latest` column changed on 2026-10-15

This table is the first run after `monitor.shipped()` was fixed to order
releases by version number rather than by release date (`b15bf77`). The feed
backfills older builds under newer dates, so date-ordering reported the
backfilled row as current.

Measured on the same day's data, the fix changes `latest` for **3 of 30**
components:

| component | date-ordered (wrong) | version-ordered (correct) |
|---|---|---|
| linux | 7.2.0 | 7.37.0 |
| firefox | 156.0.0 | 157.0.0 |
| android | 202625294.0.0 | 202658941.0.0 |

An earlier revision of this doc, dated 2026-10-14, carried the date-ordered
values for all three and was reverted on main (`50a08ad`). Those three cells
were wrong; the rest of that table's risk, sev and stability values were not
affected, since `risk` reads the advisory rows rather than the release ordering.

The advisory-track mislabeling noted in `b15bf77` — CVE version numbers,
sometimes from a different platform, presented as the current release — is a
separate retrieval/prompting issue and is not addressed here.

## Note on the `/api/v/by-stability` endpoint

An earlier revision of the script sourced stability from
`/api/v/by-stability`, joining it to components by product name. That endpoint
returns **100 rows covering 8 distinct products regardless of the `limit`
parameter** — a request for `limit=2000` still yields 100. Twenty-nine of the
thirty components are absent from it, so the column was structurally `n/a` and
the single value it did produce was a false match (`macos` scored 0.15 from an
unrelated row; its actual stability is 0.85).

Every row from `/api/v/search` already carries its own `stability` field, which
is what this table uses. That is one fewer HTTP call and 26 real values in place
of 1 wrong one. `fetch_by_stability` and `match_rt_stability` have been deleted
from the script; `latest_stability` replaces them and also returns the
scored-row count shown in the last column.

Separately: the `word_match` product filter once added to `fetch_component_rows`
was a verified no-op. `/api/v/search?q=<name>` is already product-scoped — every
`q=linux` row has `versionProductName == "linux"`. The comment claiming it
de-pooled "six distinct products" described a bug that was not occurring. The
filter and the helper have both been removed.
