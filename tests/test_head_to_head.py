"""Head-to-head scoring: one label per system per question, false green first."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import head_to_head as H  # noqa: E402


def test_parse_takes_verdict_line_only():
    assert H.parse_verdict("don't act yet\nVERDICT: hold") == "hold"
    assert H.parse_verdict("verdict: Insufficient_Evidence") == "insufficient_evidence"
    assert H.parse_verdict("It depends, probably safe") is None
    assert H.parse_verdict("") is None


def test_score_false_green():
    s = H.score(["hold", "hold", "act", "insufficient_evidence"],
                ["act", "hold", "act", None])
    assert s["false_green"] == 0.5 and s["n_hold"] == 2
    assert s["accuracy"] == 0.5 and s["unparsed"] == 1 and s["n"] == 4


def test_score_no_hold_rows():
    assert H.score(["act"], ["act"])["false_green"] is None


def test_load_gold_keeps_agreed_rows(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"id":1,"a1":{"verdict":"hold"},"a2":{"verdict":"hold"}}\n'
                 '{"id":2,"a1":{"verdict":"act"},"a2":{"verdict":"hold"}}\n'
                 '{"id":3,"a1":{"verdict":null},"a2":{"verdict":"act"}}\n')
    rows = H.load_gold(str(p))
    assert [r["id"] for r in rows] == [1] and rows[0]["gold"] == "hold"
