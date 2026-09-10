"""
"Show pipeline steps" is a display switch, not a pipeline switch.

The rewrite and all three fetches lived inside `if show_steps:`, so unchecking
the box in the sidebar did not hide the narration -- it skipped the work. The
run crashed on the unbound `rewritten` before it could get as far as answering
from an empty pool, which is the failure that would have been left if the crash
were patched by initialising the variable.

No network here: `union_fetch` and the rewriter are stubbed, and what is
asserted is that the pipeline still calls them with the box unchecked.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

import app_1  # noqa: E402
from app_1 import Rewrite  # noqa: E402

RELEASE = {"product": "Chrome", "version": "155.0.8049", "date": "20260909",
           "notes": "stability fixes", "security": [], "url": ""}


@pytest.fixture
def stubbed(monkeypatch):
    calls = []

    def fake_union(fetch_fn, phrasings, limit, tr=None):
        calls.append(getattr(fetch_fn, "__name__", "fn"))
        return [dict(RELEASE)]

    monkeypatch.setattr(app_1, "union_fetch", fake_union)
    monkeypatch.setattr(app_1, "rewrite_query",
                        lambda q: Rewrite("chrome bug fixes", "rule-based"))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    return calls


@pytest.mark.parametrize("show_steps", [True, False])
def test_the_pipeline_runs_whether_or_not_steps_are_shown(stubbed, show_steps):
    results = app_1.run_pipeline("What bugs were fixed in Chrome recently?",
                                 show_steps=show_steps, limit=5)
    assert results["rewritten_query"] == "chrome bug fixes"
    assert len(stubbed) == 3                      # community, releases, cve
    assert results["releases"], "release pool is empty with steps hidden"


def test_hiding_the_steps_changes_nothing_but_the_narration(stubbed):
    shown = app_1.run_pipeline("What bugs were fixed in Chrome recently?",
                               show_steps=True, limit=5)
    stubbed.clear()
    hidden = app_1.run_pipeline("What bugs were fixed in Chrome recently?",
                                show_steps=False, limit=5)
    for field in ("releases", "community", "cve", "rewritten_query",
                  "grounded_query", "fetch_phrasings"):
        assert shown[field] == hidden[field], field
