"""
The sidebar roster must report what happened, not what was configured.

It was a static markdown table: "Query Rewriter | Llama 3.1" whether or not a
model answered, "CVE Security | Live API" whether or not the feed did. On
Streamlit Community Cloud no Ollama is reachable, so the rewriter row was
wrong on every run there, and a timed-out feed still advertised itself as
live -- the same class of claim as the fabricated release row and the Reddit
posts labelled "CVE Feed": the UI asserting something the run does not
support.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")
import app_1  # noqa: E402
from app_1 import Rewrite, _agent_table, _presenter_caption  # noqa: E402


class _Presented:
    def __init__(self, mode, model="", note=""):
        self.mode, self.model, self.note = mode, model, note


def _results(**over):
    base = {
        "temporal": None, "grounding": None, "rewrite": None,
        "community": [], "releases": [], "cve": [], "errors": [],
        "cve_dropped": 0,
    }
    base.update(over)
    return base


def test_idle_roster_says_it_is_idle():
    t = _agent_table()
    assert "Idle" in t
    # It must not assert a model answered before anything has run.
    assert "Rule-based (fallback)" not in t


def test_a_rule_based_rewrite_is_reported_as_the_fallback():
    t = _agent_table(_results(rewrite=Rewrite("x", mode="rule-based",
                                              note="llama3.1 not reachable")))
    assert "Rule-based (fallback)" in t


def test_a_model_rewrite_names_the_model():
    t = _agent_table(_results(rewrite=Rewrite("x", mode="llm", model="llama3.1")))
    assert "llama3.1" in t
    assert "Rule-based (fallback)" not in t


def test_an_unreachable_feed_is_not_advertised_as_live():
    t = _agent_table(_results(errors=[{"agent": "Release Notes",
                                       "error": "TimeoutError: read timed out"}]))
    assert "Unreachable" in t
    assert "Live API" not in t


def test_release_row_separates_advisories_from_shipped_releases():
    rows = [
        {"product": "linux", "version": "7.1.0", "url": "https://github.com/torvalds/linux"},
        {"product": "Linux", "version": "25.642087.0", "is_cve": True,
         "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-80688"},
    ]
    t = _agent_table(_results(releases=rows))
    assert "1 doc(s)" in t and "1 advisory" in t


def test_security_row_reports_what_was_dropped_as_off_topic():
    t = _agent_table(_results(cve=[], cve_dropped=4))
    assert "4 off-topic dropped" in t


def test_presenter_row_distinguishes_model_from_rule():
    assert "Rule-based" in _agent_table(_results(), _Presented("rule-based"))
    assert "gpt-4o" in _agent_table(_results(), _Presented("llm", "gpt-4o"))


def test_roster_is_a_markdown_table():
    t = _agent_table(_results())
    assert t.splitlines()[0].startswith("| Agent")
    assert t.splitlines()[1].startswith("|---")


# The presenter caption used to name a model from a probe taken while the
# sidebar rendered, and that probe is cached for the life of the process: an
# Ollama that stopped answering after the first page load left the caption
# naming llama3.1 above rule-based prose. It now states intent before the run
# and reports what actually answered after it.

def test_caption_before_a_run_names_a_configured_model():
    assert "`ollama:mistral`" in _presenter_caption("ollama:mistral")
    assert "configured" in _presenter_caption("ollama:mistral")


def test_caption_before_a_run_promises_nothing_it_has_not_probed():
    c = _presenter_caption("")
    assert "chosen when you ask" in c
    # No backend is named, because none has been asked yet.
    assert "ollama" not in c and "`" not in c


def test_caption_after_a_run_reports_the_model_that_answered():
    c = _presenter_caption("", _Presented("llm", "ollama:llama3.1"))
    assert "`ollama:llama3.1`" in c and "cheapest reachable" in c
    c = _presenter_caption("env:model", _Presented("llm", "env:model"))
    assert "configured" in c


def test_caption_after_a_rule_based_run_says_why():
    c = _presenter_caption("", _Presented("rule-based", note="no presenter model configured or reachable"))
    assert "rule-based" in c and "no presenter model configured or reachable" in c
