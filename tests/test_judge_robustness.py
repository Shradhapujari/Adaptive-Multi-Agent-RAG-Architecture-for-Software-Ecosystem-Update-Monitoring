"""
Tests for judge_robustness.py — does a finding survive a second judge?

The verdict logic is the part that must not flatter the result. A conclusion
that holds only under the judge that produced it is a judge effect, and these
tests pin each case: survives, weakens, flips, and never-significant.
"""

import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "judge_robustness", os.path.join(ROOT, "judge_robustness.py"))
J = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(J)


def _res(orig, second, arms=("x", "y")):
    """Build the structure rejudge() returns, from per-arm score lists."""
    qids = list(range(len(orig[arms[0]])))
    original = {q: {a: {"query": f"q{q}", "answer": "a",
                        "answer_scores": {"faithfulness": orig[a][q]}}
                    for a in arms} for q in qids}
    rej = {q: {a: {"faithfulness": second[a][q]} for a in arms} for q in qids}
    return {"qids": qids, "original": original, "rejudged": rej}


ARMS = ["x", "y"]


# ── verdicts ─────────────────────────────────────────────────────────────

def test_finding_that_holds_under_both_judges_survives():
    res = _res({"x": [0.9] * 10, "y": [0.5] * 10},
               {"x": [0.8] * 10, "y": [0.4] * 10})
    o = J.paired_under(res, ARMS, "faithfulness", "original")
    s = J.paired_under(res, ARMS, "faithfulness", "second")
    assert J.verdict(o, s).startswith("SURVIVES")


def test_finding_that_reverses_is_called_a_judge_effect():
    res = _res({"x": [0.9] * 10, "y": [0.5] * 10},
               {"x": [0.4] * 10, "y": [0.8] * 10})
    o = J.paired_under(res, ARMS, "faithfulness", "original")
    s = J.paired_under(res, ARMS, "faithfulness", "second")
    assert J.verdict(o, s).startswith("FLIPS")


def test_finding_significant_only_under_the_original_judge_weakens():
    second_x = [0.5, 0.9, 0.2, 0.8, 0.4, 0.95, 0.1, 0.7, 0.55, 0.85]
    second_y = [0.9, 0.2, 0.7, 0.1, 0.8, 0.15, 0.6, 0.25, 0.75, 0.3]
    res = _res({"x": [0.9] * 10, "y": [0.5] * 10},
               {"x": second_x, "y": second_y})
    o = J.paired_under(res, ARMS, "faithfulness", "original")
    s = J.paired_under(res, ARMS, "faithfulness", "second")
    v = J.verdict(o, s)
    assert v.startswith("WEAKENS") or v.startswith("same direction")


def test_too_few_observations_is_reported_not_asserted():
    assert "not enough" in J.verdict({"n": 0}, {"n": 0})


# ── paired difference ────────────────────────────────────────────────────

def test_paired_difference_matches_the_arm_order_requested():
    res = _res({"x": [0.9] * 6, "y": [0.5] * 6}, {"x": [0.9] * 6, "y": [0.5] * 6})
    d = J.paired_under(res, ARMS, "faithfulness", "original")
    assert d["delta"] == pytest.approx(0.4)
    assert d["wins"] == 6 and d["losses"] == 0


def test_questions_missing_a_score_are_skipped_not_zero_filled():
    res = _res({"x": [0.9, 0.9], "y": [0.5, 0.5]}, {"x": [0.8, 0.8], "y": [0.4, 0.4]})
    res["rejudged"][1]["x"] = {}                      # second judge returned nothing
    d = J.paired_under(res, ARMS, "faithfulness", "second")
    assert d["n"] == 1


# ── agreement ────────────────────────────────────────────────────────────

def test_agreement_separates_calibration_offset_from_disagreement():
    """A constant offset is harmless to a paired comparison; say so in numbers."""
    res = _res({"x": [0.9, 0.8, 0.7], "y": [0.5, 0.4, 0.3]},
               {"x": [0.8, 0.7, 0.6], "y": [0.4, 0.3, 0.2]})
    ag = J.agreement(res, ARMS, "faithfulness")
    assert ag["n"] == 6
    assert ag["mean_signed_diff"] == pytest.approx(-0.1)
    assert ag["mean_abs_diff"] == pytest.approx(0.1)
    assert ag["exact_agreement"] == 0.0
    assert ag["within_0.1"] == 1.0


def test_identical_judges_agree_exactly():
    res = _res({"x": [0.9, 0.5], "y": [0.5, 0.9]}, {"x": [0.9, 0.5], "y": [0.5, 0.9]})
    ag = J.agreement(res, ARMS, "faithfulness")
    assert ag["exact_agreement"] == 1.0 and ag["mean_abs_diff"] == 0.0


def test_agreement_on_an_absent_metric_reports_nothing():
    res = _res({"x": [0.9], "y": [0.5]}, {"x": [0.9], "y": [0.5]})
    assert J.agreement(res, ARMS, "correctness") == {"n": 0}


# ── context reconstruction ───────────────────────────────────────────────

def test_contexts_prefer_stored_docs_then_the_index_and_never_fake_text():
    assert J.contexts_of({"docs": [{"title": "T", "text": "X"}]}) == ["T: X"]
    # An id is not evidence: the second judge must read what the first read.
    assert J.contexts_of({"doc_ids": ["abc"]}) is None
    idx = {"abc": {"title": "T", "text": "X"}}
    assert J.contexts_of({"doc_ids": ["abc"]}, idx) == ["T: X"]
    assert J.contexts_of({"doc_ids": ["abc", "zzz"]}, idx) is None
