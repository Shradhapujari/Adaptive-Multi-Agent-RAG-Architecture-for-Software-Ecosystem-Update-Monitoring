"""A judge that returns nothing parseable scores None, not 0.0.

Until 2026-10 `score_answer` fell through to 0.0 on every axis when the model
answered in prose, truncated its JSON or raised. Those rows were scored as
fully hallucinated, off-topic answers and were indistinguishable from real
zeros. None is skipped by the aggregator; the Judge counts the failures so a
run can report its parse-failure rate next to the means.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from eval_harness.judge import Judge, _clamp01
from eval_harness.providers import LLMError
from eval_harness import report


class _Client:
    def __init__(self, reply=None, raise_=False):
        self.reply, self.raise_ = reply, raise_

    def generate(self, prompt, **kw):
        if self.raise_:
            raise LLMError("ollama: timed out")
        return self.reply


def _judge(reply=None, raise_=False):
    j = Judge.__new__(Judge)          # no provider, no network
    j.client = _Client(reply, raise_)
    return j


def test_prose_reply_scores_none_on_every_axis():
    j = _judge("The answer looks faithful and relevant.")
    out = j.score_answer("q", "a", ["ctx"], ground_truth="gt")
    assert out == {"faithfulness": None, "answer_relevance": None, "correctness": None}
    assert (j.answer_calls, j.answer_parse_failures) == (1, 1)


def test_transport_error_is_a_failure_not_a_zero():
    j = _judge(raise_=True)
    out = j.score_answer("q", "a", ["ctx"])
    assert out["faithfulness"] is None
    assert j.answer_parse_failures == 1


def test_good_reply_is_clamped_and_counted_as_success():
    j = _judge('{"faithfulness": 1.4, "answer_relevance": 0.9, "correctness": 0.7}')
    out = j.score_answer("q", "a", ["ctx"], ground_truth="gt")
    assert out == {"faithfulness": 1.0, "answer_relevance": 0.9, "correctness": 0.7}
    assert (j.answer_calls, j.answer_parse_failures) == (1, 0)


def test_missing_axis_is_none_not_zero():
    j = _judge('{"faithfulness": 0.8}')
    out = j.score_answer("q", "a", ["ctx"])
    assert out["faithfulness"] == 0.8
    assert out["answer_relevance"] is None
    assert _clamp01("n/a") is None and _clamp01(None) is None


def test_none_scores_are_excluded_from_the_mean():
    rows = [
        {"system": "s", "ir": {}, "answer_scores": {"faithfulness": 0.5}},
        {"system": "s", "ir": {}, "answer_scores": {"faithfulness": None}},
    ]
    agg = report.aggregate(rows, ks=[3])
    mean, _ci, n = agg["systems"]["s"]["faithfulness"]
    assert (mean, n) == (0.5, 1), "a None judgment must not drag the mean toward 0"
