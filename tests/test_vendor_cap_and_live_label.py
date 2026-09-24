"""The two-product cap, and the live-vs-local label on an answer.

Both found by running the seminar deck's own example questions through the
pipeline: "Which is more stable, Teams or Zoom?" searched Teams only, and the
Siri answer announced itself as coming from the bundled dataset although every
document had come off a live endpoint seconds earlier.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import multiagent_rag_v3 as marag


# ---- the two-product cap ---------------------------------------------------

def test_a_comparison_question_resolves_both_products(monkeypatch):
    """"Teams or Zoom" searched Teams only: both reached `found`, then the
    return capped at one while RetrieverAgent looped over `vendors[:2]`."""
    monkeypatch.setattr(marag, "_VENDOR_NAMES", ["teams", "zoom"], raising=False)
    monkeypatch.setattr(marag, "_SUBREDDIT_NAMES", [], raising=False)
    monkeypatch.setattr(marag, "load_vendor_lists", lambda *a, **k: None)
    monkeypatch.setattr(marag, "MAX_VENDORS", 2)
    assert sorted(marag.extract_vendor("Which is more stable, Teams or Zoom?")) \
        == ["teams", "zoom"]
    # MARAG_MAX_VENDORS=1 reproduces every run before 2026-09-23.
    monkeypatch.setattr(marag, "MAX_VENDORS", 1)
    assert len(marag.extract_vendor("Which is more stable, Teams or Zoom?")) == 1


# ---- the live/local label --------------------------------------------------

def test_community_only_answers_are_not_labelled_local(monkeypatch):
    """An answer built from live community sources used to announce itself as
    coming from the bundled dataset, because the live list omitted them."""
    monkeypatch.setattr(marag, "pause", lambda *a, **k: None)
    live = [{"source": "vendor_reddit", "title": "Mobile data after iOS 26.4",
             "detail": "", "subreddit": "ios", "sentiment": "Neutral", "url": "u1"}]
    local = [{"title": "bundled", "detail": "", "subreddit": "ios",
              "sentiment": "Neutral", "url": "u2"}]     # no source -> "local"
    assert "live releasetrain.io" in marag.EvaluatorAgent().run(live, "ios 26.4")["answer"]
    assert "local dataset" in marag.EvaluatorAgent().run(local, "ios 26.4")["answer"]
