#!/usr/bin/env python3
"""
Read run artifacts and answer the two questions a phase gate asks.

  1. Is each run admissible?  (evaluation-protocol.md §5)
  2. What does the arm table say, and does the frozen corpus actually hold?

Usage:
    ./venv311/bin/python scripts/check_runs.py                # 4 most recent runs
    ./venv311/bin/python scripts/check_runs.py <run_dir> ...  # specific runs

Nothing here recomputes metrics from the pipeline: it reads what the runs wrote,
which is the point. A number that cannot be re-derived from `results/<run_id>/`
does not belong in the paper.
"""

from __future__ import annotations

import glob
import json
import math
import os
import statistics as st
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")
FIX_COMMITS = ("a1c717c", "46ad7d0")


def descends(sha: str, ancestor: str) -> bool:
    """True iff `ancestor` is in `sha`'s history; False on any git error."""
    try:
        return subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, sha],
                              cwd=ROOT, capture_output=True).returncode == 0
    except OSError:
        return False


def load(run_dir: str) -> dict | None:
    cfg_p = os.path.join(run_dir, "config.json")
    pq_p = os.path.join(run_dir, "per_query.jsonl")
    if not (os.path.exists(cfg_p) and os.path.exists(pq_p)):
        return None
    return {
        "dir": run_dir,
        "name": os.path.basename(run_dir),
        "cfg": json.load(open(cfg_p)),
        "rows": [json.loads(l) for l in open(pq_p)],
    }


def admissibility(run: dict) -> list[tuple[bool, str]]:
    """evaluation-protocol.md §5, read off the artifact rather than remembered."""
    c = run["cfg"]
    corpus = c.get("corpus") or {}
    checks = [
        (corpus.get("mode") in ("replay", "strict"),
         f"corpus.mode is replay or strict (is {corpus.get('mode')})"),
        (bool(corpus.get("frozen")), f"corpus.frozen (corpus_misses={corpus.get('corpus_misses')})"),
        (not c.get("rerank_degraded"), f"reranker not degraded ({c.get('rerank_spec')})"),
        (bool(c.get("judge_active")), "judge active"),
    ]
    if "preflight_refusals" in c:  # post-gate run; older runs lack the key
        refusals = c["preflight_refusals"]
        sha = str(c.get("git_sha"))
        checks += [
            (refusals == [], f"no preflight refusals ({'; '.join(map(str, refusals)) or 'none'})"),
            (c.get("diagnostic") is not True, "not run as --diagnostic"),
            (corpus.get("mode") == "strict", f"corpus.mode == strict (is {corpus.get('mode')})"),
            (all(descends(sha, f) for f in FIX_COMMITS),
             f"git_sha {sha} descends from {', '.join(FIX_COMMITS)}"),
        ]
    return checks


def mean_ci(xs: list[float]) -> tuple[float, float]:
    xs = [x for x in xs if x is not None]
    if not xs:
        return (float("nan"), float("nan"))
    m = st.mean(xs)
    if len(xs) < 2:
        return (m, 0.0)
    return (m, 1.96 * st.stdev(xs) / math.sqrt(len(xs)))


def main(argv: list[str]) -> int:
    dirs = argv[1:] or sorted(glob.glob(os.path.join(RESULTS, "run_*")),
                              key=os.path.getmtime)[-4:]
    runs = [r for r in (load(d) for d in dirs) if r]
    if not runs:
        print("no runs with both config.json and per_query.jsonl")
        return 1

    print("=" * 78)
    print("ADMISSIBILITY  (evaluation-protocol.md §5)")
    print("=" * 78)
    admissible = []
    for r in runs:
        checks = admissibility(r)
        ok = all(p for p, _ in checks)
        arm = r["cfg"].get("rerank_spec", "?")
        n = r["cfg"].get("n_questions", "?")
        print(f"\n{r['name']}  arm={arm}  n={n}  ->  "
              f"{'ADMISSIBLE' if ok else 'NOT ADMISSIBLE'}")
        for passed, label in checks:
            print(f"   [{'x' if passed else ' '}] {label}")
        if ok:
            admissible.append(r)
    admissible_all = list(admissible)

    # ---- does the freeze actually hold? -------------------------------
    # Run over every run, not only admissible ones. This check is *most*
    # informative when the freeze flag already failed: it says whether the leak
    # actually changed the documents the arms saw, or was cosmetic.
    admissible = runs if len(admissible) < 2 else admissible
    if len(admissible) > 1:
        print("\n" + "=" * 78)
        print("FROZEN-CORPUS CHECK — identical pre-rerank pool across arms")
        print("=" * 78)
        keysets = [{(row["system"], row["query_id"]): tuple(row.get("pool_doc_ids") or [])
                    for row in r["rows"]} for r in admissible]
        common = set(keysets[0])
        for k in keysets[1:]:
            common &= set(k)
        same_set = sum(1 for k in common
                       if len({frozenset(ks[k]) for ks in keysets}) == 1)
        same_ord = sum(1 for k in common if len({ks[k] for ks in keysets}) == 1)
        print(f"  identical pool SET   : {same_set}/{len(common)}")
        print(f"  identical pool ORDER : {same_ord}/{len(common)}")
        if same_set != len(common):
            print("  ** GATE FAILS: the corpus was not frozen across these arms. **")

    # ---- arm table ----------------------------------------------------
    print("\n" + "=" * 78)
    print("ARM TABLE  (mean ± 95% CI half-width, per question)")
    print("=" * 78)
    metrics = ["mrr", "ndcg@1", "ndcg@3", "ndcg@5", "recall@5"]
    systems = sorted({row["system"] for r in runs for row in r["rows"]})
    for sysname in systems:
        print(f"\n-- {sysname}")
        hdr = f"{'metric':<12}" + "".join(
            f"{(r['cfg'].get('rerank_spec') or '?')[:14]:>20}" for r in runs)
        print(hdr)
        for m in metrics + ["pool_recall"]:
            cells = []
            for r in runs:
                rows = [x for x in r["rows"] if x["system"] == sysname]
                vals = ([x.get("pool_recall") for x in rows] if m == "pool_recall"
                        else [(x.get("ir") or {}).get(m) for x in rows])
                mu, hw = mean_ci(vals)
                cells.append("             n/a" if mu != mu else f"{mu:>11.3f} ±{hw:.3f}")
            print(f"{m:<12}" + "".join(f"{c:>20}" for c in cells))

    print("\nReminder: an arm difference below the minimum detectable effect for this "
          "n is 'not detectable at this sample size', not a null result.")
    return 0 if len(admissible_all) == len(runs) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
