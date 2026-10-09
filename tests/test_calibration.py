"""Sampler fills cells round-robin and blind; kappa behaves at the edges."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from build_calibration_set import select  # noqa: E402
from compute_kappa import kappa, obligation_errors  # noqa: E402


def _pair(q, a, t, did="d"):
    return {"query_id": q, "query": "q", "asks": a, "tier": t, "judge": 1,
            "doc": {"doc_id": f"{did}{q}", "source": "x"}}


def test_select_round_robins_cells_and_one_pair_per_question_per_cell():
    pairs = [_pair(1, "version", "tier1"), _pair(1, "version", "tier1", "e"),
             _pair(2, "version", "tier1"), _pair(3, "stance", "community"),
             _pair(4, "cve", "news"), _pair(5, "other", "tier1")]
    out = select(pairs, n=4)
    assert [(p["asks"], p["tier"]) for p in out] == [
        ("version", "tier1"), ("stance", "community"), ("cve", "news"), ("version", "tier1")]
    assert {p["query_id"] for p in out} == {1, 2, 3, 4}        # no "other", no second doc for q1


def test_kappa_edges():
    assert kappa([0, 1, 2, 0], [0, 1, 2, 0]) == 1.0
    assert abs(kappa([0, 0, 1, 1], [0, 1, 0, 1])) < 1e-9        # chance
    assert kappa([0, 2, 0, 2], [0, 2, 0, 2], weighted=True) == 1.0
    assert kappa([0, 1, 2, 1], [1, 2, 0, 2], weighted=True) > kappa([0, 1, 2, 1], [2, 2, 0, 0], weighted=True)
    assert kappa([], []) is None


def test_obligation_errors_name_the_row_and_annotator():
    rows = [{"id": 7, "evidence": [{"doc_id": "a"}],
             "a1": {"verdict": "act", "evidence_doc_ids": []},
             "a2": {"verdict": "insufficient_evidence", "evidence_doc_ids": ["zz"]}}]
    errs = obligation_errors(rows, "verdict")
    assert any("row 7 a1: act cites no evidence" in e for e in errs)
    assert any("row 7 a2" in e and "zz" in e for e in errs)
    assert len(errs) == 3
