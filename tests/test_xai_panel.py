"""
The explanation panel under the answer must report the run, not the design.

The expander it replaces listed the evidence and stopped, which answers "what
was cited" and neither of the questions a reader asks of this system: why did
it look at that thread, and which sentence rests on it. A source that was
retrieved and never cited has to say so -- a panel that shows every retrieved
row as if it backed the answer is the same over-claim as the old static agent
roster.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

import xai  # noqa: E402
from answer_agent import Evidence  # noqa: E402
from app_1 import _xai_panel  # noqa: E402

EVIDENCE = [
    Evidence(label="R1", kind="release", title="Fedora 44 released",
             date="2026-09-01", security=True, detail="kernel 6.17.2",
             url="https://example.invalid/f44"),
    Evidence(label="C1", kind="community", title="Anyone else losing grub?",
             date="2026-09-02", sentiment="Negative"),
    Evidence(label="R2", kind="release", title="Debian 13.2 point release",
             date="2026-08-20"),
]
QUERY = "did the fedora 44 update break grub"
ANSWER = ("Fedora 44 shipped on 2026-09-01 with kernel 6.17.2 [R1]. "
          "Users report grub loss after it [C1].")


def _panel(answer=ANSWER, evidence=EVIDENCE):
    return _xai_panel(xai.explain(QUERY, answer, evidence))


def test_every_source_says_why_it_was_retrieved():
    md = _panel()
    assert "matches '44', 'fedora'" in md
    assert "flagged SECURITY" in md
    assert "negative sentiment" in md


def test_a_retrieved_source_the_answer_ignored_is_labelled_as_such():
    md = _panel()
    assert "Debian 13.2 point release" in md
    assert "retrieved, not cited" in md
    assert md.count("— *cited*") == 2


def test_each_sentence_is_joined_to_its_citation():
    md = _panel()
    assert "Fedora 44 shipped on 2026-09-01 with kernel 6.17.2 [R1].\n  - [R1]" in md


def test_a_sentence_with_no_version_or_date_says_only_that():
    # "no factual claim to cite" over-read the check: this module looks at
    # versions and dates, and an assertion of absence is a claim it cannot see.
    md = _panel("Nothing shipped [R1]. There are no critical updates.")
    assert "no version or date stated" in md


def test_a_fact_stated_without_a_citation_is_flagged():
    # Every fact here is in the pool, so the guardrail passes it; the sentence
    # still carries no label, which is what the reader has to be told.
    md = _panel("Fedora 44 shipped with kernel 6.17.2.")
    assert "⚠️ states" in md and "6.17.2" in md


def test_the_url_is_offered_where_the_source_has_one():
    md = _panel()
    assert "[open source](https://example.invalid/f44)" in md


def test_an_empty_pool_says_so_instead_of_rendering_nothing():
    assert "nothing was retrieved" in _panel("I cannot determine that.", [])
