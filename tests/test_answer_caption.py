"""
The caption under the answer must say who wrote it, in both views.

The one-line view -- the default since the details switch -- printed
"2 source(s) · 6.0s" and nothing else. A guardrail rejection, where the model's
paragraph is thrown away and rule-based prose shown in its place, then looked
identical to a clean model answer. The details view had the honest caption all
along; the two are now one function so they cannot drift apart again.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

from answer_agent import Evidence, PresentedAnswer  # noqa: E402
from app_1 import _answer_caption  # noqa: E402

EV = [Evidence(label="R1", kind="release", title="Chrome v156.0.8060"),
      Evidence(label="R2", kind="release", title="Chrome v155.0.8059")]


def test_a_model_answer_names_the_model():
    p = PresentedAnswer("Chrome v156.0.8060 shipped [R1].", "llm",
                        model="ollama:llama3.1", evidence=EV)
    assert _answer_caption(p, 1, 6.0) == \
        "Presented by ollama:llama3.1 · 1 of 2 source(s) cited · 6.0s"


def test_a_guardrail_rejection_is_visible_in_the_caption():
    p = PresentedAnswer("rule-based prose [R1].", "rule-based", evidence=EV,
                        note="model output failed the guardrail — "
                             "unknown_citation: [Release Notes - Fedora 44] was not in the prompt")
    cap = _answer_caption(p, 1, 8.7)
    assert cap.startswith("Presented rule-based (model output failed the guardrail")
    assert "unknown_citation" in cap
    assert "1 of 2 source(s) cited" in cap


def test_cited_is_reported_against_the_pool_not_alone():
    # "2 source(s)" on its own read as "two sources cited"; the honest figure
    # is cited out of retrieved.
    p = PresentedAnswer("x [R1] [R2].", "llm", model="m", evidence=EV)
    assert "2 of 2 source(s) cited" in _answer_caption(p, 2, 1.0)
