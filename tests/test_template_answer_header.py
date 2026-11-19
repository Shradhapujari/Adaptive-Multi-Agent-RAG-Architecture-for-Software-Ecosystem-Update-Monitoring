"""
The single-agent template answer opens with a Query/Verified/Confidence/Retrieved
block. The compact view must headline the answer, not echo the question back.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

from app_1 import _one_line, _strip_template_header  # noqa: E402

TEMPLATE = (
    "Query: latest Chrome version?\n"
    "Verified: yes\n"
    "Confidence: 0.8\n"
    "Retrieved: 3\n"
    "\n"
    "✅ ANSWER (synthesized by ollama:llama3.1):\n"
    "Chrome v156.0.8060 shipped on 2026-10-01 [R1]."
)


def test_header_is_stripped_and_answer_is_the_headline():
    assert _one_line(TEMPLATE) == "Chrome v156.0.8060 shipped on 2026-10-01."


def test_prose_answers_are_untouched():
    prose = "Chrome v156.0.8060 shipped on 2026-10-01 [R1]."
    assert _strip_template_header(prose) == prose
