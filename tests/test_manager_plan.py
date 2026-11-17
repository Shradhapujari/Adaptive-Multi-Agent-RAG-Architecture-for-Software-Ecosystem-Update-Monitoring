"""
Tests for the Manager's structured plan (plan_query).

Offline: call_llama is stubbed, so nothing here calls Ollama or an endpoint.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import multiagent_rag_v3 as marag  # noqa: E402


def test_llm_plan_keeps_exact_wording_and_drops_unknown_sources(monkeypatch):
    reply = ('Sure, here is the plan:\n{"thinking": "existing release", '
             '"detected_vendor": "Apple", "temporal_anchor": "none", '
             '"search_strategy": "iOS 26.4, Siri offline bug", '
             '"expected_sources": ["community_discussions", "blogs"]}')
    monkeypatch.setattr(marag, "call_llama", lambda p: reply)
    q = "Siri fail to execute tasks when offline after iOS 26.4 update"
    plan = marag.plan_query(q)
    assert plan["planner"] == "llama3.1"
    assert plan["search_strategy"][0] == q
    assert "Siri offline bug" in plan["search_strategy"]
    assert plan["expected_sources"] == ["community_discussions"]


def test_fallback_anchors_time_by_rule_and_survives_braces(monkeypatch):
    monkeypatch.setattr(marag, "call_llama", lambda p: None)
    monkeypatch.setenv("MARAG_NOW", "2026-08-31")
    q = "Any critical {Linux} updates today?"
    plan = marag.plan_query(q)
    assert plan["planner"] == "rule-based fallback"
    assert "2026-08-31" in plan["temporal_anchor"]
    assert plan["search_strategy"] == [q]
    assert plan["expected_sources"]
    assert set(plan["expected_sources"]) <= set(marag.PLAN_SOURCES)


def test_rule_time_anchor_overrides_the_llm(monkeypatch):
    monkeypatch.setattr(marag, "call_llama",
                        lambda p: '{"temporal_anchor": "2024-01-01"}')
    monkeypatch.setenv("MARAG_NOW", "2026-08-31")
    plan = marag.plan_query("Linux CVEs this week")
    assert "2024-01-01" not in plan["temporal_anchor"]
