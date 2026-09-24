"""
The clock a run reads is part of its corpus.

Retrieval turns "latest" and "last week" into date filters, so the wall clock
decides which documents are fetched and kept. A snapshot that freezes only the
HTTP responses still drifts when it is replayed on a later day. These tests
pin the two halves of the fix: `temporal.now()` honours `MARAG_NOW`, and a
snapshot stamps its recording date and sets `MARAG_NOW` from it on replay.

Offline: no network, no model.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import corpus_snapshot
import temporal


class ClockPin(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("MARAG_NOW", None)

    def tearDown(self):
        os.environ.pop("MARAG_NOW", None)
        if self._saved is not None:
            os.environ["MARAG_NOW"] = self._saved

    def test_unset_reads_the_wall_clock(self):
        self.assertAlmostEqual(temporal.now().timestamp(),
                               datetime.now().timestamp(), delta=5)

    def test_pinned_date_is_used(self):
        os.environ["MARAG_NOW"] = "2026-09-21"
        self.assertEqual(temporal.now().date().isoformat(), "2026-09-21")

    def test_pin_reaches_the_query_rewrite(self):
        os.environ["MARAG_NOW"] = "2026-09-21"
        a = temporal.resolve_temporal("Any Linux updates yesterday?").query
        os.environ["MARAG_NOW"] = "2026-09-15"
        b = temporal.resolve_temporal("Any Linux updates yesterday?").query
        self.assertIn("2026-09-20", a)
        self.assertIn("2026-09-14", b)

    def test_a_bad_pin_fails_loudly(self):
        os.environ["MARAG_NOW"] = "last tuesday"
        with self.assertRaises(ValueError):
            temporal.now()


class SnapshotStamp(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("MARAG_NOW", None)
        self.dir = tempfile.mkdtemp(prefix="snap_clock_")

    def tearDown(self):
        os.environ.pop("MARAG_NOW", None)
        if self._saved is not None:
            os.environ["MARAG_NOW"] = self._saved

    def test_record_stamps_and_replay_pins(self):
        rec = corpus_snapshot.Snapshot("record", self.dir)
        self.assertIsNotNone(rec.recorded_at)
        os.environ.pop("MARAG_NOW", None)

        rep = corpus_snapshot.Snapshot("replay", self.dir).start()
        try:
            self.assertEqual(rep.recorded_at, rec.recorded_at)
            self.assertEqual(os.environ.get("MARAG_NOW"), rec.recorded_at)
            self.assertEqual(rep.stats()["now"], rec.recorded_at)
        finally:
            rep.stop()

    def test_the_pin_is_released_with_the_patch(self):
        """The pin is a process-wide mutation, so it lives exactly as long as
        the thing that justifies it. Held past `stop()`, it followed the
        process into whatever ran next."""
        snap = corpus_snapshot.Snapshot("record", self.dir).start()
        self.assertEqual(os.environ.get("MARAG_NOW"), snap.recorded_at)
        snap.stop()
        self.assertNotIn("MARAG_NOW", os.environ)

    def test_a_second_snapshot_replays_on_its_own_clock(self):
        """The first snapshot a process opened used to own the clock for the
        rest of it: the second found MARAG_NOW set, read it as an operator's
        explicit pin, and replayed its documents against the first recording's
        date -- silently, while `recorded_at` reported the right one."""
        other = tempfile.mkdtemp(prefix="snap_clock_b_")
        json.dump({"recorded_at": "2026-09-01T10:00:00"},
                  open(os.path.join(self.dir, corpus_snapshot.Snapshot.META), "w"))
        json.dump({"recorded_at": "2026-09-20T10:00:00"},
                  open(os.path.join(other, corpus_snapshot.Snapshot.META), "w"))

        first = corpus_snapshot.Snapshot("replay", self.dir).start()
        first.stop()
        second = corpus_snapshot.Snapshot("replay", other).start()
        try:
            self.assertEqual(os.environ.get("MARAG_NOW"), "2026-09-20T10:00:00")
            self.assertEqual(temporal.now().date().isoformat(), "2026-09-20")
        finally:
            second.stop()

    def test_re_recording_keeps_the_original_stamp(self):
        first = corpus_snapshot.Snapshot("record", self.dir).recorded_at
        os.environ.pop("MARAG_NOW", None)
        self.assertEqual(corpus_snapshot.Snapshot("record", self.dir).recorded_at,
                         first)

    def test_an_explicit_pin_wins(self):
        corpus_snapshot.Snapshot("record", self.dir)
        os.environ["MARAG_NOW"] = "2001-01-01"
        snap = corpus_snapshot.Snapshot("strict", self.dir).start()
        try:
            self.assertEqual(os.environ["MARAG_NOW"], "2001-01-01")
        finally:
            snap.stop()
        # ...and is still the operator's after the snapshot lets go.
        self.assertEqual(os.environ["MARAG_NOW"], "2001-01-01")

    def test_an_unstamped_snapshot_says_so(self):
        d = tempfile.mkdtemp(prefix="snap_nostamp_")
        snap = corpus_snapshot.Snapshot("replay", d).start()
        try:
            self.assertIsNone(snap.recorded_at)
            self.assertIsNone(snap.stats()["recorded_at"])
            self.assertNotIn("MARAG_NOW", os.environ)
        finally:
            snap.stop()


if __name__ == "__main__":
    unittest.main()
