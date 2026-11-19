"""Reasons an eval run cannot carry a research claim (the run gate)."""

import os
import subprocess


def git_state(root: str) -> tuple[str, bool]:
    """(sha, dirty); dirty = tracked files changed. Not a repo -> ("unknown", True)."""
    def run(*a):
        return subprocess.run(["git", *a], cwd=root, capture_output=True,
                              text=True, check=True).stdout
    try:
        return (run("rev-parse", "HEAD").strip(),
                bool(run("status", "--porcelain", "--untracked-files=no").strip()))
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
    elif mode == "record" and os.path.exists(os.path.join(d, ".replayed")):
        out.append("record-into-replayed: this snapshot was replayed; recording into it mutates a frozen corpus")
    if git_dirty:
        out.append("dirty-tree: tracked files differ from HEAD, so the run is not reproducible")
    if not (prediction or "").strip():
        out.append("no-prediction: state the prediction before the run")
    return out
