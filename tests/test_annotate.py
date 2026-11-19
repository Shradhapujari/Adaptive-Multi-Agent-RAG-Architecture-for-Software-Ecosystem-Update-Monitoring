"""scripts/annotate.py writes labels compute_kappa.py accepts, saves each row,
resumes where it stopped, and never shows the other annotator's block."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import pytest  # noqa: E402

from annotate import block, run  # noqa: E402
from compute_kappa import obligation_errors  # noqa: E402


def _row(i):
    return {"id": i, "query": f"q{i}", "asks": "version", "ecosystem": "chrome",
            "evidence": [{"doc_id": f"d{i}x", "title": "x"}, {"doc_id": f"d{i}y", "title": "y"}],
            "a1": {"verdict": None, "evidence_doc_ids": [], "note": ""},
            "a2": {"verdict": "hold", "evidence_doc_ids": [f"d{i}y"], "note": "SECRET-A2"}}


def _sheet(tmp_path, n=3):
    p = tmp_path / "s.jsonl"
    p.write_text("".join(json.dumps(_row(i)) + "\n" for i in range(1, n + 1)))
    return str(p)


def _script(answers):
    it = iter(answers)
    return lambda _prompt: next(it)


def test_block_enforces_the_evidence_obligation():
    r = _row(1)
    assert block(r, "act", [2, 2])["evidence_doc_ids"] == ["d1y"]
    assert block(r, "insufficient_evidence", [])["evidence_doc_ids"] == []
    for verdict, picks in (("act", []), ("insufficient_evidence", [1]), ("hold", [3]), ("safe", [1])):
        with pytest.raises(ValueError):
            block(r, verdict, picks)


def test_labels_save_per_row_resume_and_stay_blind(tmp_path):
    path, said = _sheet(tmp_path), []
    # row 1: a bad pick is refused, then act on doc 1; row 2: insufficient; then quit
    n = run(path, "a1", ask=_script(["a", "5", "", "a", "1", "first", "i", "", "q"]),
            say=said.append)
    assert n == 2
    rows = [json.loads(line) for line in open(path)]
    assert rows[0]["a1"] == {"verdict": "act", "evidence_doc_ids": ["d1x"], "note": "first"}
    assert rows[1]["a1"]["verdict"] == "insufficient_evidence"
    assert rows[2]["a1"]["verdict"] is None
    assert rows[0]["a2"]["note"] == "SECRET-A2"              # the other block is untouched
    assert not any("SECRET-A2" in s for s in said)           # never shown to a1
    assert not obligation_errors(rows, "verdict")
    # a second session starts at row 3 only, and --rows limits the scope
    said.clear()
    run(path, "a1", limit=2, ask=_script(["q"]), say=said.append)
    assert said[0].endswith("2 of 2 rows already labelled by a1")
