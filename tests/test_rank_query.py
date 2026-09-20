"""
Tests for `resolve_rank_query` — which phrasing the reranker scores against.

This is a separate ablation dimension from *which* scoring function ranks, and
keeping them separate is what makes the previously published configuration
measurable. The published pipeline paired the `none` scoring function with the
*rewritten* query; running `none` on the original question is already a partial
fix, so an ablation that cannot express the original pairing cannot honestly
label a row "as published".

Offline: the helper is pure, so none of this touches the network.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import multiagent_rag_v3 as marag  # noqa: E402

ORIG = "G6 Bullet unstable?"
REWRITTEN = "Unstable behavior in G6 Bullet software: known issues or updates"


def test_default_ranks_on_the_original_question():
    assert marag.resolve_rank_query(ORIG, REWRITTEN, rank_on="original") == ORIG


def test_rewritten_reproduces_the_published_pairing():
    assert marag.resolve_rank_query(ORIG, REWRITTEN, rank_on="rewritten") == REWRITTEN


def test_missing_original_falls_back_to_the_rewrite():
    """The single-agent baseline's case: it passes one string for both."""
    assert marag.resolve_rank_query("", REWRITTEN, rank_on="original") == REWRITTEN
    assert marag.resolve_rank_query(None, REWRITTEN, rank_on="original") == REWRITTEN
    assert marag.resolve_rank_query("   ", REWRITTEN, rank_on="original") == REWRITTEN


def test_value_is_read_case_insensitively_and_trimmed():
    assert marag.resolve_rank_query(ORIG, REWRITTEN, rank_on=" REWRITTEN ") == REWRITTEN


@pytest.mark.parametrize("bad", ["rewrite", "orig", "both", "", "none"])
def test_unrecognised_value_raises_rather_than_defaulting(bad):
    """A typo in a sweep must fail, not quietly measure the default arm."""
    with pytest.raises(ValueError):
        marag.resolve_rank_query(ORIG, REWRITTEN, rank_on=bad)


def test_environment_variable_drives_the_choice(monkeypatch):
    monkeypatch.setenv("MARAG_RANK_QUERY", "rewritten")
    assert marag.resolve_rank_query(ORIG, REWRITTEN) == REWRITTEN
    monkeypatch.setenv("MARAG_RANK_QUERY", "original")
    assert marag.resolve_rank_query(ORIG, REWRITTEN) == ORIG


def test_unset_environment_variable_defaults_to_original(monkeypatch):
    monkeypatch.delenv("MARAG_RANK_QUERY", raising=False)
    assert marag.resolve_rank_query(ORIG, REWRITTEN) == ORIG


def test_bad_environment_variable_raises(monkeypatch):
    monkeypatch.setenv("MARAG_RANK_QUERY", "nonsense")
    with pytest.raises(ValueError):
        marag.resolve_rank_query(ORIG, REWRITTEN)


def test_choices_are_exactly_the_two_documented_arms():
    assert marag.RANK_QUERY_CHOICES == ("original", "rewritten")


# ---- resolve_rank_tiers: whether the verified-before-community prior ranks --

def test_rank_tiers_default_is_the_historical_tiered_order(monkeypatch):
    monkeypatch.delenv("MARAG_RANK_TIERS", raising=False)
    assert marag.resolve_rank_tiers() == "tiered"


def test_rank_tiers_flat_from_env_or_argument(monkeypatch):
    monkeypatch.setenv("MARAG_RANK_TIERS", "FLAT")
    assert marag.resolve_rank_tiers() == "flat"
    assert marag.resolve_rank_tiers("flat") == "flat"


def test_rank_tiers_rejects_typos():
    with pytest.raises(ValueError):
        marag.resolve_rank_tiers("flatt")
