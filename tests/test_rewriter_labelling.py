"""
The rewriter must say which path produced its output.

`answer_agent` already reports whether a paragraph was written by a model or
composed by rule, and the deployment notes promise that "rule-based prose is
never presented as model output". The rewriter returned a bare string, so a
rule-based keyword expansion was rendered under the heading "Query Rewriter
Agent — Llama 3.1 local" with nothing to distinguish it from a model rewrite.

On a host with no reachable Ollama -- Streamlit Community Cloud, where the
demo is deployed -- that is every run. Reported from the live app: the rewrite
"linux software update release changelog" appeared in 0.0s under the Llama
heading, which is the fallback's dictionary substitution, not a model.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")
import app_1  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def read(self):
        import json
        return json.dumps(self._p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _model(monkeypatch, payload=None, exc=None):
    def urlopen(*a, **k):
        if exc is not None:
            raise exc
        return _Resp(payload)
    monkeypatch.setattr(app_1.urllib.request, "urlopen", urlopen)
    # A new transport is a new model: drop rewrites cached from the last one.
    app_1._llama_rewrite.cache_clear()


def test_a_model_rewrite_is_labelled_as_one(monkeypatch):
    _model(monkeypatch, {"response": "linux kernel security patch notes"})
    rw = app_1.rewrite_query("linux update")
    assert rw.mode == "llm"
    assert rw.model == "llama3.1"
    assert rw.query == "linux kernel security patch notes"
    assert rw.note == ""


def test_wrapping_quotes_are_stripped_from_a_model_rewrite(monkeypatch):
    _model(monkeypatch, {"response": '"linux kernel security patch notes"'})
    assert app_1.rewrite_query("linux update").query == "linux kernel security patch notes"


def test_an_unreachable_model_is_labelled_rule_based(monkeypatch):
    _model(monkeypatch, exc=OSError("connection refused"))
    rw = app_1.rewrite_query("linux update")
    assert rw.mode == "rule-based"
    assert rw.model == ""
    assert "not reachable" in rw.note
    # Still returns a usable query -- degrading, not failing.
    assert rw.query.strip()


def test_an_empty_model_rewrite_falls_back_and_says_so(monkeypatch):
    _model(monkeypatch, {"response": "   "})
    rw = app_1.rewrite_query("linux update")
    assert rw.mode == "rule-based"
    assert "empty" in rw.note
    assert rw.query.strip()


def test_the_fallback_is_the_keyword_expansion_seen_in_the_demo(monkeypatch):
    # The exact string the live app showed under the Llama heading.
    _model(monkeypatch, exc=OSError("no ollama"))
    assert app_1.rewrite_query("linux update").query == "linux software update release changelog"


def test_rule_based_output_is_never_reported_as_a_model(monkeypatch):
    _model(monkeypatch, exc=OSError("no ollama"))
    rw = app_1.rewrite_query("anything at all")
    assert rw.mode != "llm" and not rw.model
