"""Two threads storing the same key leave one complete entry, never a mix.

The b1500 pilot snapshot (2026-11-21) had two entries that failed their gzip
CRC: the parallel fetch threads wrote the same key in place at once.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import corpus_snapshot  # noqa: E402


def test_concurrent_stores_of_one_key_leave_a_readable_entry(tmp_path):
    snap = corpus_snapshot.Snapshot("record", str(tmp_path / "snap"))
    bodies = [os.urandom(200_000) for _ in range(16)]
    start = threading.Barrier(len(bodies))

    def store(body):
        start.wait()
        for _ in range(20):
            snap._store("GET https://releasetrain.io/api/v/?q=rust", 200, body, {}, "u")

    threads = [threading.Thread(target=store, args=(b,)) for b in bodies]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rec = snap._load("GET https://releasetrain.io/api/v/?q=rust")
    assert rec is not None, "entry is corrupt"
    assert snap._body(rec) in bodies
    assert not [f for f in os.listdir(snap.dir) if f.endswith(".tmp")]


def test_a_write_that_dies_midway_keeps_the_previous_entry(tmp_path, monkeypatch):
    snap = corpus_snapshot.Snapshot("record", str(tmp_path / "snap"))
    key = "GET https://releasetrain.io/api/v/?q=linux"
    snap._store(key, 200, b"first", {}, "u")

    def dies(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(corpus_snapshot.json, "dump", dies)
    try:
        snap._store(key, 200, b"second", {}, "u")
    except KeyboardInterrupt:
        pass
    monkeypatch.undo()

    rec = snap._load(key)
    assert rec is not None and snap._body(rec) == b"first"
    assert not [f for f in os.listdir(snap.dir) if f.endswith(".tmp")]
