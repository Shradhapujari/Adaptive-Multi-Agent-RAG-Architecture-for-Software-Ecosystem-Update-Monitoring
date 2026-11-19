"""Held-out split: only questions after the freeze date that no public file holds."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_heldout as B  # noqa: E402

PUBLIC = [{"id": "1", "query": "Is Firefox 140 safe?", "reddit_id": "aaa"}]


def test_drops_old_and_public_questions():
    recs = [
        {"id": "x1", "query": "Old question", "reddit_id": "b", "date": "2026-11-01"},
        {"id": "x2", "query": "  is firefox 140 SAFE? ", "reddit_id": "c", "date": "2026-12-01"},
        {"id": "x3", "query": "Same post, new title", "reddit_id": "aaa", "date": "2026-12-01"},
        {"id": "x4", "query": "Brand new question", "reddit_id": "d", "date": "2026-12-01"},
        {"id": "x5", "query": "Undated", "reddit_id": "e"},
    ]
    assert [r["id"] for r in B.fresh(recs, PUBLIC, after="2026-11-20")] == ["x4"]


def test_output_dir_is_gitignored():
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run(["git", "check-ignore", "data/heldout/decision_heldout.jsonl"],
                         cwd=root, capture_output=True, text=True)
    assert out.returncode == 0


def test_public_set_is_repo_anchored(monkeypatch, tmp_path):
    """I7: run from another directory, the public set must still be found."""
    monkeypatch.chdir(tmp_path)
    assert len(B.public_questions()) > 0
    assert B.OUT.startswith(B.ROOT)


def test_nested_heldout_dir_is_ignored():
    import subprocess
    out = subprocess.run(["git", "check-ignore", "scripts/data/heldout/x.jsonl"], cwd=B.ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 0
