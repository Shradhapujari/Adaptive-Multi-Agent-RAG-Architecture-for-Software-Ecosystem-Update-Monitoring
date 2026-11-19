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

# The real shape from multiagent_rag_v3: quoted query, one-line Confidence with
# its Sources, a timestamp, then the indented answer under its label.
TEMPLATE = (
    'Query: "latest Chrome version?"\n'
    "Verified: VERIFIED from live releasetrain.io APIs\n"
    "Confidence: HIGH (quality=0.80) | Sources: releasetrain\n"
    "Retrieved: 2026-11-18 09:00\n"
    "\n"
    "  ✅ ANSWER (synthesized by mistral):\n"
    "\n"
    "  Chrome v156.0.8060 shipped on 2026-10-01 [R1].\n"
    "\n"
    "  ✅ VERIFIED SOURCES (1):\n"
)


def test_header_is_stripped_and_answer_is_the_headline():
    assert _one_line(TEMPLATE) == "Chrome v156.0.8060 shipped on 2026-10-01."


def test_prose_answers_are_untouched():
    prose = "Chrome v156.0.8060 shipped on 2026-10-01 [R1]."
    assert _strip_template_header(prose) == prose
