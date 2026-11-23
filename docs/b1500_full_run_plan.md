# benchmark_1500 full run — plan

Written 2026-11-22, from the 50-question pilot (record `run_1795254167_b73e1e248451`,
strict replay `run_1795338277_b73e1e248451`, both on `9d12b84`).

## What the run is

| | |
|---|---|
| Questions | all 1,500 of `data/benchmark_1500.json` (519 with ground truth), no `--limit`, no `--stratify` |
| Arms | `marag`, `marag:ollama:llama3.1`, `single_agent:ollama:llama3.1` (`marag_decide` dropped, user 2026-11-21) |
| Judge | `ollama:llama3.1` (default) |
| News | `MARAG_NEWS=feeds` |
| marag synthesis | `MARAG_SYNTH_MODEL=llama3.1` (PR #198; mistral cannot load beside llama3.1 on this host) |
| Code | detached worktree of `origin/main` at one pinned commit, never moved mid-run |
| Corpus | new folder `data/corpus_snapshot_b1500_full_<MMDD>`: one `record:` pass, then one `strict:` pass |
| Result to quote | the **strict** run only; the record run is never frozen |

Not comparable with any `benchmark_1000` / `benchmark_500` run (new question set), nor with the
pilot (older code: #191, #193, #194 merged after `9d12b84`).

## Before starting — all must hold

1. **A second pilot passed.** The first one failed (strict replay `run_1795338277` stopped at
   question 34 of 50): its only corpus miss was corrupt entry `41bcadc57e0b54d0b22b`
   (`by-subreddit?q=openai`), and `marag`'s mistral call timed out on 29 of 33 questions. Re-run
   the 50-question pilot on the pinned commit, into a fresh snapshot folder, with the night-1
   settings below: record, then strict, both 50/50 with 0 corpus misses and no 30 s `marag` cells.
2. **Snapshot writes are atomic — done, #196 (`875e1de`).** The first pilot snapshot has 2
   corrupt entries (`41bcadc57e0b54d0b22b`, `adaead50ffc007959f18`) from in-place gzip writes by
   parallel fetch threads; `_load` reads one as a miss, which aborts a strict replay.
2b. **`MARAG_SYNTH_MODEL=llama3.1` — done, #198 (`6b7164f`).** `ollama ps` shows llama3.1 pinned "Forever"
   (`keep_alive -1`); Ollama logs `system_limited` with 2.5–4.6 GiB free, and mistral gets no
   reply in 120 s. With the default, `marag`'s answer is "NO ANSWER" whenever memory is short.
   The run is pinned to `27656ba`, the #215 merge (moved from `6b7164f` by #202 and #206):
   #201, #204, #212 and #215 change `vendor.advisory_names_vendor`, which `fetch_vendor_releases`
   runs for all three arms, so the eval drops the wrong-product advisories the app does --
   kernel "rust:" CVEs, npm packages, and products named as the platform ("X for Linux",
   "Chrome on Android"; 51 of 584 live releasetrain rows). #200, #203, #209 and #210 are
   console-only, and the pilot's snapshot and synth checks are unaffected. Night 1 first ran on
   `8e3ff42` (`run_1795415581_922f6707656d`, 91 questions) and was restarted on `27656ba`
   with a new snapshot, `corpus_snapshot_b1500_full_1123`; that first run is not quoted.
3. **The machine stays awake.** The pilot record pass took 18.6 h instead of ~3 h: from 02:00 the
   Mac went into *Clamshell Sleep* on battery, and questions 10–19 took 37,600 s of wall clock.
   Run on AC power, lid open, every command wrapped in `caffeinate -dimsu`.
4. **Fixed questions checked live once** (rust / Linux / GitHub advisories, Fedora 44 "latest",
   Arch bare "Yes") on the pinned commit, so a regression shows before 50 hours are spent.
5. **No other eval on this host** (`ps aux | grep eval_harness.run_eval` empty). The harness also
   takes `~/.marag_eval.lock`.
6. **Prediction written down** (below), and `.streamlit/secrets.toml` still git-ignored.

## Time

Per-question medians from the pilot record log (sleep-hit questions excluded by using medians):
`marag` 44 s, `marag:llama3.1` 48 s, `single_agent:llama3.1` 13 s. The strict replay ran ~48 s per
question with four arms.

| Pass | Per question (3 arms, incl. judging) | 1,500 questions |
|---|---|---|
| record | ~2 min | **~50 h** |
| strict replay | ~40–45 s | **~18 h** |

Re-measure after the first night and update this table.

## How it is chunked

One run, resumed across nights, not one run per chunk. `--resume <run_dir>` skips every question
already scored for all three arms and loses at most the one in flight, and the run gate refuses a
resume whose commit, corpus spec or `MARAG_*` settings moved (`resumed-across-change`). So:

- Start once; stop in the morning with **Ctrl-C**; resume the next night with the same command
  plus `--resume`. The worktree and env must be identical every time.
- The snapshot's `recorded_at` pins `MARAG_NOW` to the first night, so every night answers
  "today" as the same date.
- Record pass ≈ 35 h at night 1's measured ~1.4 min/question (≈ 4 nights of ~10 h). Strict pass
  a few hours (pilot 2's strict medians were ~2 s per arm).

## Commands

Set once per shell (zsh):

```bash
export REPO=/Users/shradha/Adaptive-Multi-Agent-RAG-Architecture-for-Software-Ecosystem-Update-Monitoring
export WT=/Users/shradha/marag-b1500-full
export SNAP=$REPO/data/corpus_snapshot_b1500_full_MMDD
```

Worktree, once (pinned to `27656ba`, the #215 merge; the pilot 2 worktree, moved there with
`git -C $WT checkout --detach 27656ba`):

```bash
git -C $REPO fetch origin && git -C $REPO worktree add --detach $WT 27656ba
```

Record pass, night 1:

```bash
cd $WT && caffeinate -dimsu env -u PYTHONPATH MARAG_NEWS=feeds MARAG_SYNTH_MODEL=llama3.1 MARAG_CORPUS= $REPO/venv311/bin/python -m eval_harness.run_eval --dataset data/benchmark_1500.json --generators marag,marag:ollama:llama3.1,single_agent:ollama:llama3.1 --corpus record:$SNAP --prediction "<prediction>" >> results/b1500_full_record.log 2>&1
```

Record pass, nights 2+ (same line, plus `--resume`; the original prediction is kept):

```bash
cd $WT && caffeinate -dimsu env -u PYTHONPATH MARAG_NEWS=feeds MARAG_SYNTH_MODEL=llama3.1 MARAG_CORPUS= $REPO/venv311/bin/python -m eval_harness.run_eval --dataset data/benchmark_1500.json --generators marag,marag:ollama:llama3.1,single_agent:ollama:llama3.1 --corpus record:$SNAP --prediction "<prediction>" --resume <record_run_dir> >> results/b1500_full_record.log 2>&1
```

Strict pass (after the record pass reports 1,500/1,500), first night then `--resume` the same way:

```bash
cd $WT && caffeinate -dimsu env -u PYTHONPATH MARAG_NEWS=feeds MARAG_SYNTH_MODEL=llama3.1 MARAG_CORPUS= $REPO/venv311/bin/python -m eval_harness.run_eval --dataset data/benchmark_1500.json --generators marag,marag:ollama:llama3.1,single_agent:ollama:llama3.1 --corpus strict:$SNAP --prediction "<prediction>" >> results/b1500_full_strict.log 2>&1
```

## Each morning

1. Ctrl-C the run; confirm no `run_eval` process is left.
2. Rows so far: count distinct `query_id` in `<run_dir>/per_query.jsonl` (×3 rows each).
3. `grep -ciE "CorpusMiss|Traceback" results/b1500_full_*.log` → expect 0.
4. `gate.json`: `preflight_refusals` must be `[]`. Any `resumed-across-change` makes the run
   unquotable — stop and find what moved.
5. Snapshot health: every `$SNAP/*.json.gz` decompresses (the check that found the pilot's two
   corrupt entries).

## Prediction (confirmed by the user, 2026-11-22 — pass this text verbatim as `--prediction`)

> On benchmark_1500 under a strict frozen corpus, the paired nDCG@3 delta between `marag` and
> `single_agent:ollama:llama3.1` is within ±0.02 (null), as in the frozen three-arm b1000 run
> (FINDINGS 9–11); `marag:ollama:llama3.1` does not beat `marag` by more than 0.02.

## After the strict pass

1. `./venv311/bin/python scripts/check_runs.py <strict_run_dir>` — admissible, frozen corpus holds.
2. Copy both run dirs from `$WT/results/` into `$REPO/results/` (results stay local).
3. Quote the strict run's paired deltas with their CIs, per category and for the 519 ground-truth
   rows; medians for latency (sleep and Ollama stalls skew means).
4. Remove the worktree once the run dirs are copied.

## Known limits

- The judge is the same model as two arms (llama3.1): a self-evaluation bias that applies to both
  LLM arms, not to `marag`'s retrieval metrics.
- The snapshot also caches localhost model calls, including 56 recorded Ollama failures in the
  pilot; a cached failure replays as a failure, so answer scores can depend on Ollama stalls
  during recording. Retrieval metrics do not.
- Many model prompts miss that cache between record and replay and run live again (1–2 s calls in
  the first pilot's replay). Allowed by design: every arm in the strict pass still reads the same
  documents, so answers are not byte-identical to the record pass, but arm comparisons hold.
- `marag` answers are written by llama3.1, not mistral, so they are not comparable with earlier
  `marag` answer scores.
- The question set reflects the September cache, not November's feeds.
