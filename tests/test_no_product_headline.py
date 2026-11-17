"""A version question is answered with the *asked product's* release, or not
at all. "Latest Nodej.s version?" grounded to no product, the gate abstained,
and the headline still read "linux v7.38.0" -- the newest release anywhere in
an unscoped pool (live, 2026-11-12). And a misspelt product gets a "did you
mean", never a silent substitution."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

import app_1  # noqa: E402
import vendor  # noqa: E402

CATALOG = ["node.js", "linux", "python", "firefox", "chrome", "django"]
LINUX = {"product": "linux", "version": "7.38.0", "date": "20261018", "notes": "merge tag"}
NODE = {"product": "node.js", "version": "26.9.0", "date": "20260916", "notes": "release"}


def _g(*names):
    return SimpleNamespace(vendors=[vendor.VendorMatch(name=n, matched=n) for n in names],
                           vendor_names=list(names))


# ---- A: the headline is the asked product's release, or none -------------

def test_no_product_means_no_release_headline():
    res = {"releases": [LINUX, NODE], "grounding": _g()}
    assert app_1._headline_release(res, "Latest Nodej.s version?") is None


def test_headline_is_the_asked_products_release_not_the_newest():
    res = {"releases": [LINUX, NODE], "grounding": _g("node.js")}
    assert app_1._headline_release(res, "Latest Node.js version?")["product"] == "node.js"


def test_no_release_of_the_asked_product_means_no_headline():
    res = {"releases": [LINUX], "grounding": _g("node.js")}
    assert app_1._headline_release(res, "Latest Node.js version?") is None


def test_fast_path_does_not_answer_with_another_products_release(monkeypatch):
    # The fast path's feed fetch fell back to every row when none matched the
    # product; it must escalate instead of answering from linux.
    monkeypatch.setattr(app_1, "ground", lambda q: SimpleNamespace(
        vendors=[vendor.VendorMatch(name="node.js", matched="node.js")],
        vendor_names=["node.js"], rewritten=q, temporal=None, citable_kinds=("release",)))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    monkeypatch.setattr(app_1, "caching_fetch", lambda *a, **k: (lambda q, limit=5, **kw: [dict(LINUX)]))
    assert app_1.run_fast("Latest Node.js version?") is None


# ---- B: did you mean ------------------------------------------------------

@pytest.mark.parametrize("q,want", [
    ("Latest Nodej.s version?", "node.js"),
    ("Is it safe to update Firefx?", "firefox"),
    ("Latest pyhton release?", "python"),
])
def test_a_misspelt_product_gets_a_suggestion(q, want):
    assert vendor.suggest(q, CATALOG) == want


@pytest.mark.parametrize("q", [
    "What is the capital of Peru?",
    "Latest version?",
    "Is it safe to update?",
])
def test_no_suggestion_without_a_near_product(q):
    assert vendor.suggest(q, CATALOG) is None


@pytest.mark.parametrize("q,want", [
    ("Latest Nodej.s version?", "node.js"), ("Is it safe to update Firefx?", "firefox"),
    ("Latest pyhton release?", "python"), ("Any kernal bugs?", "linux"),
    ("is ubunut 26.04 stable?", "ubuntu"), ("Latest crome version?", "chrome"),
])
def test_typos_of_known_products_with_the_default_list(q, want):
    assert vendor.suggest(q) == want


# Benchmark questions with no product that drew a bogus suggestion: a real
# word inside a product name or alias ("phone" in iphone, "nodes", "window"),
# or a 0.8 near-miss ("home" -> chrome, "clue" -> claude).
@pytest.mark.parametrize("q", [
    "I am I overthinking or does my phone have a virus?",
    "Nodes are not joining after upgrading eks to v1.33",
    "PSA: do not run sudo su inside a tmux window!",
    "Can i change Ventura 13.7.8 on my IMac?",
    "Is iCloud Down Right Now?",
    "How to connect when away from home",
    "Any clue? Screen starts flickering/glitching",
    "pgEdge providing false information",
])
def test_ordinary_words_are_not_misspelt_products(q):
    assert vendor.suggest(q) is None


def test_no_product_note_names_the_suggestion():
    res = {"original_query": "Latest Nodej.s version?", "grounding": _g(),
           "suggestion": "node.js"}
    note = app_1._no_product_note(res)
    assert "Node.js" in note and "Latest Node.js version?" in note


def test_no_product_note_without_a_suggestion_still_says_why():
    note = app_1._no_product_note({"original_query": "Latest version?", "grounding": _g()})
    assert "which product" in note.lower()
