"""Reasons an eval run cannot carry a research claim (the run gate)."""

import fcntl
import json
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import corpus_snapshot

# One eval per host, not per checkout: every worktree shares this file.
LOCK_PATH = os.path.expanduser("~/.marag_eval.lock")


class Busy(Exception):
    def __init__(self, pid: str):
        super().__init__(f"another eval is running (pid {pid})")
        self.pid = pid


def hold_lock(path: str):
    """Take the host lock; the caller keeps the returned file open. Stale files don't block."""
    f = open(path, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.seek(0)
        pid = f.read().strip() or "unknown"
        f.close()
        raise Busy(pid) from None
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    return f


def split_of(dataset_path: str) -> str:
    """"split" from <dataset>.manifest.json; "dev" if the file or key is missing."""
    base = dataset_path
    for ext in (".jsonl", ".json"):
        if base.endswith(ext):
            base = base[:-len(ext)]
            break
    try:
        with open(base + ".manifest.json") as f:
            return json.load(f).get("split") or "dev"
    except (OSError, ValueError, AttributeError):
        return "dev"


def git_state(root: str) -> tuple[str, bool]:
    """(sha, dirty); dirty = tracked files changed outside results/. Not a repo -> ("unknown", True).

    results/ is excluded because the harness itself rewrites the tracked
    results/qrels_cache.json after every question.
    """
    def run(*a):
        return subprocess.run(["git", *a], cwd=root, capture_output=True,
                              text=True, check=True).stdout
    try:
        return (run("rev-parse", "HEAD").strip(),
                bool(run("status", "--porcelain", "--untracked-files=no",
                         "--", ".", ":(exclude)results").strip()))
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True


def refusals(corpus: str, prediction: str, git_dirty: bool) -> list[str]:
    out = []
    corpus = (corpus or "").strip()
    mode, _, d = corpus.partition(":")
    mode, d = mode.strip().lower(), d.strip()
    if not corpus:
        out.append("live-corpus: no MARAG_CORPUS snapshot, so sources can move between arms")
    elif mode == "replay":
        out.append("lenient-replay: replay serves live on a miss; use strict:<dir>")
    elif mode == "record" and os.path.exists(os.path.join(d, corpus_snapshot.REPLAYED)):
        out.append("record-into-replayed: this snapshot was replayed; recording into it mutates a frozen corpus")
    if git_dirty:
        out.append("dirty-tree: tracked files differ from HEAD, so the run is not reproducible")
    if not (prediction or "").strip():
        out.append("no-prediction: state the prediction before the run")
    return out


def merge_gate(prior: dict | None, cur: dict, has_rows: bool) -> dict:
    """The gate record for a run dir: this invocation's `cur`, merged into the
    run's original `prior` (its gate.json) when resuming.

    A resume keeps the original prediction, git_sha and corpus spec, unions the
    refusals, and adds `resumed-across-change` when sha or corpus moved, or when
    rows exist with no gate record at all (a pre-gate run). Once diagnostic,
    always diagnostic.
    """
    if prior is None:
        g = dict(cur, preflight_refusals=list(cur["preflight_refusals"]))
        if has_rows:
            g["preflight_refusals"].append("resumed-across-change: no gate record for this run")
    else:
        g = dict(prior)
        refs = list(prior.get("preflight_refusals") or [])
        refs += [r for r in cur["preflight_refusals"] if r not in refs]
        moved = [f"{k} {prior.get(k)!r} -> {cur[k]!r}" for k in ("git_sha", "corpus")
                 if prior.get(k) != cur[k]]
        if moved:
            refs.append("resumed-across-change: " + "; ".join(moved))
        g["preflight_refusals"] = refs
        g["git_dirty"] = bool(prior.get("git_dirty")) or cur["git_dirty"]
    g["diagnostic"] = (bool(g["preflight_refusals"]) or bool(cur["diagnostic"])
                       or bool((prior or {}).get("diagnostic")))
    return g
