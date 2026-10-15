"""parse_ranking must reject anything short of a full, exact permutation --
a near-miss response is a failed run, not something to silently coerce --
and the two correlation stats must agree with their textbook extremes
(identical orders -> 1.0, fully reversed -> -1.0) before either goes in a paper.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import pytest

from rank_components_llm import kendall_tau, parse_ranking, spearman_rho

COMPONENTS = ["linux", "chrome", "firefox", "wordpress"]


def test_parse_ranking_happy_path_is_case_insensitive():
    text = '["Chrome", "LINUX", "firefox", "WordPress"]'
    assert parse_ranking(text, COMPONENTS) == ["chrome", "linux", "firefox", "wordpress"]


def test_parse_ranking_strips_code_fence():
    text = '```json\n["linux", "chrome", "firefox", "wordpress"]\n```'
    assert parse_ranking(text, COMPONENTS) == ["linux", "chrome", "firefox", "wordpress"]


def test_parse_ranking_rejects_unknown_component():
    with pytest.raises(ValueError):
        parse_ranking('["linux", "chrome", "firefox", "edge"]', COMPONENTS)


def test_parse_ranking_rejects_short_list():
    with pytest.raises(ValueError):
        parse_ranking('["linux", "chrome", "firefox"]', COMPONENTS)


def test_parse_ranking_rejects_non_array():
    with pytest.raises(ValueError):
        parse_ranking('{"order": ["linux"]}', COMPONENTS)


def test_correlation_extremes():
    identical = {c: i + 1 for i, c in enumerate(COMPONENTS)}
    reversed_ = {c: len(COMPONENTS) - i for i, c in enumerate(COMPONENTS)}
    assert spearman_rho(identical, identical, COMPONENTS) == pytest.approx(1.0)
    assert kendall_tau(identical, identical, COMPONENTS) == pytest.approx(1.0)
    assert spearman_rho(identical, reversed_, COMPONENTS) == pytest.approx(-1.0)
    assert kendall_tau(identical, reversed_, COMPONENTS) == pytest.approx(-1.0)
