"""The judgment cache must survive two evaluations sharing a results dir.

A `--resume` arm running beside the next pass of a sweep is the normal case in
this repo, not an exotic one. An in-place write lets the second writer land
inside the first one's output; `_load_qrels_cache` then swallows the parse error
and returns {}, so every judgment is silently made again -- hours of work, and
judgments taken under a different model state can shift results mid-sweep.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import tempfile

import pytest

from eval_harness.run_eval import (QRELS_CACHE, _load_qrels_cache,
                                   _save_qrels_cache, qrels_key)


def _writer(args):
    d, n, tag = args
    cache = {qrels_key(f"question {i}", f"{tag}{i:011x}"): (i % 3) for i in range(n)}
    for _ in range(12):
        _save_qrels_cache(d, cache)
    return True


class TestAtomicSave:
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            cache = {qrels_key("q", "a" * 12): 2}
            _save_qrels_cache(d, cache)
            assert _load_qrels_cache(d) == cache

    def test_no_temp_files_left_behind(self):
        with tempfile.TemporaryDirectory() as d:
            _save_qrels_cache(d, {qrels_key("q", "b" * 12): 1})
            leftovers = [f for f in os.listdir(d)
                         if f not in (QRELS_CACHE, f"{QRELS_CACHE}.lock")]
            assert leftovers == [], f"temp files not cleaned up: {leftovers}"

    def test_concurrent_writers_never_leave_torn_json(self):
        """The regression this file exists for."""
        with tempfile.TemporaryDirectory() as d:
            with mp.Pool(4) as pool:
                pool.map(_writer, [(d, 400, "a"), (d, 400, "b"),
                                   (d, 400, "c"), (d, 400, "e")])
            # Must parse. Before the fix this raised JSONDecodeError, which the
            # loader would have swallowed into a silent full re-judge.
            with open(os.path.join(d, QRELS_CACHE)) as f:
                loaded = json.load(f)
            # Every writer unions the file before replacing it, so no writer's
            # labels are lost to another's: four disjoint sets of 400 survive.
            assert len(loaded) == 1600
            assert _load_qrels_cache(d) == loaded

    def test_save_unions_with_what_is_on_disk(self):
        """A stale in-memory dict must not drop labels others added since."""
        with tempfile.TemporaryDirectory() as d:
            _save_qrels_cache(d, {qrels_key(f"q{i}", "c" * 12): 1 for i in range(50)})
            mine = {qrels_key("q0", "c" * 12): 2,      # conflicts: ours wins
                    qrels_key("q0", "d" * 12): 2}      # new
            _save_qrels_cache(d, mine)
            on_disk = _load_qrels_cache(d)
            assert len(on_disk) == 51
            assert on_disk[qrels_key("q0", "c" * 12)] == 2
            assert mine == on_disk                     # caller's dict sees the union

    def test_corrupt_file_still_degrades_to_empty(self):
        """Unchanged behaviour: a damaged cache must not crash a run."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, QRELS_CACHE), "w") as f:
                f.write('{"broken": ')
            assert _load_qrels_cache(d) == {}
