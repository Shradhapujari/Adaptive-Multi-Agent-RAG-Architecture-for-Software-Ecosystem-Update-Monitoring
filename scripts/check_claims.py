#!/usr/bin/env python3
"""Quote gate: every number in paper/claims.tsv must re-derive from an admissible run.

    python scripts/check_claims.py            # exit 1 if any row fails
    python scripts/check_claims.py --hash results/<run>   # sha256 for the column

Numbers without a row in claims.tsv are not checked.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "check_runs", os.path.join(ROOT, "scripts", "check_runs.py"))
check_runs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_runs)

COLS = "file quote runs system metric stat value n sha256".split()


def _get(row, path):
    for k in path.split("."):
        row = row.get(k) if isinstance(row, dict) else None
    return row


def _sha(run_dir):
    with open(os.path.join(run_dir, "per_query.jsonl"), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def check(row: dict, root: str) -> list[str]:
    try:
        return _check(row, root)
    except Exception as e:  # one malformed row must not stop the rest being checked
        return [f"error {type(e).__name__}: {e}"]


def _check(row: dict, root: str) -> list[str]:
    bad = []
    path = os.path.join(root, row["file"])
    if not os.path.exists(path) or row["quote"] not in open(path, encoding="utf-8").read():
        bad.append(f"quote {row['quote']!r} not found in {row['file']}")
    names = row["runs"].split(",")
    hashes = row["sha256"].split(",")
    if len(names) != len(hashes):
        return bad + [f"{len(names)} runs but {len(hashes)} sha256 values"]
    runs = []
    for name, h in zip(names, hashes):
        d = os.path.join(root, "results", name)
        run = check_runs.load(d)
        if run is None:
            bad.append(f"run {name} missing on disk (needs config.json and per_query.jsonl)")
            continue
        runs.append(run)
        if _sha(d) != h:
            bad.append(f"{name}: sha256 of per_query.jsonl differs from the row")
        if str(run["cfg"].get("n_questions")) != row["n"]:
            bad.append(f"{name}: n is {run['cfg'].get('n_questions')}, row says {row['n']}")
        bad += [f"{name}: inadmissible, failed: {lab}"
                for ok, lab in check_runs.admissibility(run) if not ok]
    if len(runs) != len(names) or row["stat"] == "manual":
        return bad
    stat, per_run = row["stat"], []
    for run in runs:
        rows = [r for r in run["rows"] if r.get("system") == row["system"]]
        vals = [_get(r, row["metric"]) for r in rows]
        if stat == "count":
            per_run.append(sum(1 for v in vals if v))
            continue
        vals = [v for v in vals if v is not None]
        if not vals:
            return bad + [f"{run['name']}: no values for {row['system']} {row['metric']}"]
        per_run.append(st.median(vals) if stat == "median" else sum(vals) / len(vals))
    if stat == "delta":
        if len(runs) != 2:
            return bad + ["delta needs exactly two runs"]
        if runs[0]["cfg"]["corpus"].get("dir") != runs[1]["cfg"]["corpus"].get("dir"):
            bad.append("delta across different corpus.dir")
        if runs[0]["cfg"].get("dataset_hash") != runs[1]["cfg"].get("dataset_hash"):
            bad.append("delta across different dataset_hash")
        got = per_run[0] - per_run[1]
    elif stat in ("mean", "median", "count") and len(runs) == 1:
        got = per_run[0]
    else:
        return bad + [f"unknown stat {stat!r} or wrong run count"]
    d = len(row["value"].split(".")[1]) if "." in row["value"] else 0
    try:
        want = float(row["value"])
    except ValueError:
        return bad + [f"value {row['value']!r} is not a number"]
    if round(got, d) != want:
        bad.append(f"value {row['value']} does not re-derive (got {got:.6g})")
    return bad


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--claims", default="paper/claims.tsv")
    ap.add_argument("--hash")
    a = ap.parse_args(argv)
    if a.hash:
        print(_sha(a.hash))
        return 0
    n = failed = manual = 0
    with open(os.path.join(a.root, a.claims), encoding="utf-8") as f:
        lines = f.read().splitlines()
    # ponytail: no quoting; a tab inside a quote cell breaks the row
    header = "\t".join(COLS)
    first = 2
    if lines[:1] == [header]:
        pass
    else:  # a bad header is a failure, and the line is then checked as data
        n += 1
        failed += 1
        first = 1
        print(f"line 1: header must be {header}")
    for i, line in enumerate(lines[first - 1:], start=first):
        if not line.strip() or line.startswith("#"):
            continue
        n += 1
        cells = line.split("\t")
        if len(cells) != len(COLS):
            failed += 1
            print(f"line {i}: expected {len(COLS)} columns, got {len(cells)}")
            continue
        row = dict(zip(COLS, cells))
        manual += row["stat"] == "manual"
        bad = check(row, a.root)
        failed += bool(bad)
        for b in bad:
            print(f"line {i}: {b}")
    print(f"checked {n}, failed {failed}, not re-derived {manual}")
    print("numbers without a row in claims.tsv are not checked")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
