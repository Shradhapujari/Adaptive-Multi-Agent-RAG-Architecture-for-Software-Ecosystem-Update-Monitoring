# Component update-order ranking — 2026-10-14

Thirty ecosystem components ranked by update urgency. Live pull from
releasetrain.io, `scripts/component_stability_ranking.py`.

Two independent scores, reported side by side and deliberately not blended:

- **risk / sev** — this project's heuristic (`monitor.risk`): severity-weighted
  advisories in the trailing 90 days, plus a staleness term. `risk` caps at 100,
  which ties the top 14; `sev` is the same weighted sum uncapped, used only to
  order within that tie.
- **stability** — releasetrain.io's own 0–1 score (higher = more stable), taken
  from the most recent scored row for that product. Nothing here has shown that
  a merged score beats either alone, so they stay separate.

Sorted by `risk` desc, then `sev` desc. Higher = update sooner.

| # | component | risk | sev | band | advisories (90d) | latest | age (d) | stability | scored rows |
|---:|---|---:|---:|---|---:|---|---:|---:|---:|
| 1 | wordpress | 100 | 3126 | Critical | 299 | 7.1.3 | 8 | 0.89 | 1/300 |
| 2 | linux | 100 | 847 | Critical | 132 | 7.2.0 | 0 | 0.75 | 54/186 |
| 3 | gitlab | 100 | 630 | Critical | 58 | 18.11.0 | 181 | 0.35 | 1/59 |
| 4 | windows | 100 | 613 | Critical | 56 | 10.0.28000 | 36 | 0.88 | 1/108 |
| 5 | docker | 100 | 442 | Critical | 31 | 29.9.0 | 6 | 0.75 | 4/35 |
| 6 | kubernetes | 100 | 399 | Critical | 31 | 1.38.0 | 0 | 0.30 | 66/97 |
| 7 | android | 100 | 371 | Critical | 29 | 202625294.0.0 | 43 | 0.53 | 184/213 |
| 8 | git | 100 | 335 | Critical | 26 | 2.56.0 | 16 | 0.75 | 1/28 |
| 9 | postgresql | 100 | 288 | Critical | 22 | 18.6.0 | 62 | 0.75 | 1/23 |
| 10 | macos | 100 | 215 | Critical | 23 | 27.0.1 | 16 | 0.84 | 3/27 |
| 11 | mysql | 100 | 158 | Critical | 11 | 26.7.0 | 78 | 0.75 | 42/53 |
| 12 | rust | 100 | 142 | Critical | 14 | 1.99.0 | 1 | 0.75 | 64/78 |
| 13 | chrome | 100 | 124 | Critical | 13 | 157.0.8103 | 1 | 0.90 | 287/300 |
| 14 | ios | 100 | 113 | Critical | 9 | 27.0.1 | 16 | 0.83 | 6/17 |
| 15 | ubuntu | 79 | 79 | Critical | 13 | 26.104.0 | 27 | 0.35 | 4/17 |
| 16 | firefox | 44 | 44 | Medium | 9 | 156.0.0 | 1 | 0.35 | 168/179 |
| 17 | debian | 38 | 38 | Medium | 6 | 13.7.0 | 32 | 0.35 | 2/8 |
| 18 | arch | 12 | 12 | Low | 4 | — | — | n/a | 0/4 |
| 19 | grafana | 12 | 12 | Low | 2 | 13.2.4 | 1 | 0.90 | 60/63 |
| 20 | fedora | 3 | 3 | Low | 1 | 45.0.0 | 29 | 0.49 | 1/2 |
| 21 | safari | 0 | 0 | Low | 0 | 27.0.0 | 30 | 0.52 | 25/25 |
| 22 | edge | 0 | 0 | Low | 0 | — | — | n/a | 0/0 |
| 23 | brave | 0 | 0 | Low | 0 | 1.97.56 | 7 | 0.90 | 7/7 |
| 24 | opera | 0 | 0 | Low | 0 | — | — | n/a | 0/0 |
| 25 | node | 0 | 0 | Low | 0 | 26.11.1 | 0 | 0.90 | 66/66 |
| 26 | python | 0 | 0 | Low | 0 | 3.15.0 | 5 | 0.75 | 29/29 |
| 27 | home assistant | 0 | 0 | Low | 0 | — | — | n/a | 0/0 |
| 28 | nextcloud | 0 | 0 | Low | 0 | 35.0.1 | 20 | 0.90 | 5/5 |
| 29 | mongodb | 0 | 0 | Low | 0 | — | — | n/a | 0/0 |
| 30 | neovim | 0 | 0 | Low | 0 | 0.12.6 | 0 | 0.90 | 71/71 |

## Caveats

**Four components have no data at all.** `edge`, `opera`, `home assistant` and
`mongodb` returned zero rows from `/api/v/search`. Their score of 0 and band of
"Low" mean *the feed knows nothing about them*, not *they are safe to defer*.
They should be read as unranked. `arch` has 4 rows but none carry a stability
score. Do not cite ranks 22–29 as evidence that these components are stable.

**The score is a coverage proxy as much as a risk measure.** WordPress tops the
list at 299 advisories largely because its plugin ecosystem files CVEs per
plugin, so one "component" aggregates thousands of independent publishers.
Comparing its 3126 against the Linux kernel's 847 compares reporting conventions,
not attack surface.

**`risk` saturates.** Fourteen of thirty components hit the 100 cap, so the
headline band separates almost nothing at the top. The ordering within those
fourteen comes entirely from the uncapped `sev` tiebreak, which is an unvalidated
severity-weighted count, not a calibrated risk model.

**Stability is sparsely scored and uses the latest scored row, not the latest
row.** The "scored rows" column gives the ratio. Where it reads 1/300
(wordpress) or 1/108 (windows), the stability figure rests on a single row that
may be considerably older than the listed release — it is a weak signal for
those components and a reasonable one for chrome (287/300) or neovim (71/71).

**Live, non-frozen pull.** These numbers move daily. Re-running will not
reproduce this table; the date in the filename is the only version marker.

## Note on the `/api/v/by-stability` endpoint

An earlier revision of the script sourced stability from
`/api/v/by-stability`, joining it to components by product name. That endpoint
returns **100 rows covering 8 distinct products regardless of the `limit`
parameter** — a request for `limit=2000` still yields 100. Twenty-nine of the
thirty components are absent from it, so the column was structurally `n/a` and
the single value it did produce was a false match (`macos` scored 0.15 from an
unrelated row; its actual stability is 0.84).

Every row from `/api/v/search` already carries its own `stability` field, which
is what this table uses. That is one fewer HTTP call and 27 real values in place
of 1 wrong one. `fetch_by_stability` and `match_rt_stability` have been deleted
from the script; `latest_stability` replaces them and also returns the scored-row
count shown in the last column.

Separately: the `word_match` product filter added to `fetch_component_rows` was a
verified no-op. `/api/v/search?q=<name>` is already product-scoped — all 186
`q=linux` rows have `versionProductName == "linux"`. The comment claiming it
de-pooled "six distinct products" described a bug that was not occurring. The
filter and the helper have both been removed.
