"""A version question naming no recognised product gets "Which product?", not
an answer composed from an unscoped pool.

Sweep 2026-11-25, "Latest Nodej.s version?": grounding found no product, the
headline correctly read "Which product? Did you mean Node.js?", but the Read
more tab and the source tables under it cited CVEs for rest, backdrop and
hustoj -- whatever the unscoped search returned.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

import app_1  # noqa: E402


def _ask(monkeypatch, q, vendors=()):
    results = {"original_query": q, "grounding": SimpleNamespace(vendors=list(vendors)),
               "suggestion": "node.js" if not vendors else None}
    monkeypatch.setattr(app_1.graph, "route_query", lambda q: ("full", "test"))
    monkeypatch.setattr(app_1, "run_pipeline", lambda q, **kw: dict(results))
    composed = []
    monkeypatch.setattr(app_1, "_present_answer",
                        lambda *a, **k: composed.append(a) or SimpleNamespace(text="composed", evidence=[]))
    _, presented = app_1.ask(q)
    return presented, composed


def test_version_question_without_a_product_is_not_composed(monkeypatch):
    presented, composed = _ask(monkeypatch, "Latest Nodej.s version?")
    assert composed == []
    assert presented.evidence == []
    assert "Node.js" in presented.text and "Latest Node.js version?" in presented.text


def test_a_named_product_is_still_answered(monkeypatch):
    presented, composed = _ask(monkeypatch, "Latest Node.js version?", vendors=["node.js"])
    assert composed and presented.text == "composed"


def test_a_stance_question_without_a_product_is_still_answered(monkeypatch):
    # Only version/date questions have nothing to say without a product; the
    # UI shows a stance answer under a "Did you mean" caption.
    presented, composed = _ask(monkeypatch, "Is it safe to update Nodej.s?")
    assert composed
