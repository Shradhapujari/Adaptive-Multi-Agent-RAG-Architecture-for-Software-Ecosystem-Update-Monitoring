"""The graph's invariants, as pytest sees them; graph._demo() is the long form."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import graph  # noqa: E402


def test_self_check_passes():
    graph._demo()


def test_absent_on_healthy_fetch_never_retries():
    rw = lambda q, tried: q
    s = graph.run("latest Fedora version?", rw, lambda q: ([], False), max_rounds=5)
    assert s.evidence is graph.Evidence.ABSENT
    assert len(s.tried) == 1 and s.trace[-1].node == "abstain"


def test_trace_is_emitted_as_jsonl_when_asked(tmp_path, monkeypatch):
    p = tmp_path / "t.jsonl"
    monkeypatch.setenv(graph.tokens.TRACE_ENV, str(p))
    graph.run("latest Fedora version?", lambda q, t: q, lambda q: ([], False))
    lines = p.read_text().splitlines()
    assert [__import__("json").loads(l)["node"] for l in lines] == ["rewrite", "retrieve", "classify"]
    assert all(k in __import__("json").loads(lines[0]) for k in
               ("edge_taken", "reason", "tokens", "contract_ok", "state_hash_in", "state_hash_out"))
