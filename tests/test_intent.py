"""
Tests for the intent filter.

Every case is a question the demo can actually be asked -- the sidebar
examples, the benchmark's phrasings, and the advisor's worked example. The
classifier is rule-based, so these double as its specification: a cue change
that breaks one of them changed the routing of a real question.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intent import (  # noqa: E402
    CONFIDENCE_FLOOR,
    citable_kinds,
    classify,
    classify_label,
    pool_weights,
)


# ── The three labels ─────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "Any CVEs in OpenSSL?",
    "Any security vulnerabilities in Python?",
    "Is there a zero-day being exploited in Chrome?",
    "Any critical Linux updates today?",
])
def test_security_questions(query):
    assert classify_label(query) == "security"


@pytest.mark.parametrize("query", [
    "What is the latest Linux version?",
    "Latest Django release notes",
    "What changed in CentOS v1020260105.0.0?",
    "When was Google Chrome v145.0.7611 released and on which channel?",
])
def test_release_questions(query):
    assert classify_label(query) == "release"


@pytest.mark.parametrize("query", [
    "Should I upgrade to Debian v13.3.0?",
    "Is anyone else hating the new Chrome UI?",
    "MacOS updates with negative community reaction",
    "Is the new Firefox any good?",
])
def test_opinion_questions(query):
    assert classify_label(query) == "opinion"


def test_plural_cve_is_a_security_cue():
    # `\bcve\b` does not match "CVEs"; the plural is how people actually write
    # it, and missing it sent security questions down the release route.
    assert classify_label("Any CVEs in OpenSSL?") == "security"
    assert classify("Any CVEs in OpenSSL?").scores["security"] >= 3


def test_naming_a_version_is_a_release_cue():
    assert classify("What changed in CentOS v1020260105.0.0?").scores["release"] > 0


# ── Declining to guess ───────────────────────────────────────────────────

def test_cueless_question_is_unknown_not_guessed():
    r = classify("Emulating Mac OS 9.2.2, how much power do I need?")
    assert r.label == "unknown"
    assert not r.confident


def test_unknown_searches_every_pool():
    # An unsure classifier must not narrow retrieval below what it was before
    # the classifier existed.
    r = classify("hello")
    assert set(citable_kinds(r)) == {"release", "cve", "community"}
    assert set(pool_weights(r).values()) == {1.0}


def test_confidence_floor_is_what_separates_them():
    r = classify("Any critical Linux updates today?")
    assert r.scores[r.label] >= CONFIDENCE_FLOOR


# ── Routing ──────────────────────────────────────────────────────────────

def test_release_answer_may_not_cite_an_advisory():
    # The core of the record-type repair: for a "latest version" question a CVE
    # row is not weak evidence, it is wrong evidence.
    assert "cve" not in citable_kinds(classify("What is the latest Linux version?"))


def test_security_answer_may_cite_advisories():
    assert "cve" in citable_kinds(classify("Any CVEs in OpenSSL?"))


def test_opinion_answer_leads_with_community():
    w = pool_weights(classify("Is anyone else hating the new Chrome UI?"))
    assert w["community"] > w["release"] and w["community"] > w["cve"]


@pytest.mark.parametrize("query", [
    "Is it safe to update Firefox right now?",
    "Is it safe to install iOS 26.1?",
    "Is it now safe to upgrade from 25.10 to 26.04?",
    "Is Ubuntu 24.04 safe to upgrade to?",
    "Synology DSM 7.2.2 upgrade safe?",
])
def test_a_safety_question_may_cite_advisories(query):
    # The false green of 2026-10-14: "is it safe" was an opinion cue, and
    # opinion cannot cite `cve`, so the answer to "is it safe to update?" was
    # built from a pool the advisories had been filtered out of.
    r = classify(query)
    assert r.label == "security"
    assert "cve" in citable_kinds(r)


@pytest.mark.parametrize("query", [
    "How to safely delete the another desktop environment from my system?",
    "Laptop only boots into safe mode after the update",
    "Generating type-safe Postgres client code from .sql files",
    "GPU Offload in Rust: Portable, Safe, and Fast",
    "Duplicate docker images, are they safe to delete?",
    "Is it stable enough to update Ubuntu 24.04?",
])
def test_safe_as_a_word_is_not_a_security_question(query):
    assert classify_label(query) != "security"


def test_security_answer_leads_with_advisories():
    w = pool_weights(classify("Any CVEs in OpenSSL?"))
    assert w["cve"] >= w["release"] and w["cve"] > w["community"]


def test_ties_resolve_toward_security():
    # Under-reporting a security question is the costlier error for someone
    # monitoring their own ecosystem.
    r = classify("security release")
    assert r.scores["security"] == r.scores["release"] > 0
    assert r.label == "security"


# ── Trace ────────────────────────────────────────────────────────────────

def test_describe_names_the_cues_it_fired_on():
    text = classify("Any CVEs in OpenSSL?").describe()
    assert "security" in text and "cve" in text.lower()


def test_describe_says_so_when_it_declines():
    assert "no clear intent" in classify("hello").describe()
