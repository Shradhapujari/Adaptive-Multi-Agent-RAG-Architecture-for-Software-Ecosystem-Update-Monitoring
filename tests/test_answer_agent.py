"""
Tests for the Answer Presenter agent.

Two things matter here and neither needs a model:

  1. the offline path must still cite -- an evidence-free paragraph is the
     failure this agent exists to prevent;
  2. the mode must be reported honestly, so a demo never shows rule-based
     prose while implying a model wrote it.

Offline: no network. The LLM path is exercised with a stub client injected
through the provider factory.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import answer_agent  # noqa: E402
from answer_agent import (  # noqa: E402
    build_cited_prompt, collect_evidence, deterministic_paragraph, present_answer,
)

RESULTS = {
    "releases": [
        {"product": "Linux", "version": "6.18.21", "date": "2026-08-28",
         "notes": "In the Linux kernel, the following vulnerability has been "
                  "resolved:\n\nnet: lwtunnel: Drop skb metadata before LWT "
                  "encapsulation",
         "security": ["SECURITY"], "url": "https://example.invalid/linux"},
        {"product": "Django", "version": "5.2.1", "date": "2026-08-20",
         "notes": "Routine bugfix release.", "security": [], "url": ""},
    ],
    "cve": [{"title": "CVE-2026-1234 discussed in r/netsec", "subreddit": "netsec",
             "date": "2026-08-30", "url": "https://example.invalid/cve"}],
    "community": [{"title": "6.18.21 upgrade went fine", "subreddit": "linux",
                   "date": "2026-08-31", "sentiment": "Positive", "url": ""}],
}


def _no_env(monkeypatch):
    for k in ("PRESENTER_MODEL", "MARAG_LLM"):
        monkeypatch.delenv(k, raising=False)


def _no_model(monkeypatch, spec=None):
    """Stand in for model_select's probe -- these tests do not touch the network."""
    monkeypatch.setattr(answer_agent, "_selected_spec", lambda: spec)


def test_evidence_labels_carry_source_name_and_date():
    ev = collect_evidence(RESULTS)
    labels = [e.label for e in ev]
    # The Linux row in RESULTS is advisory-shaped -- its notes are a kernel CVE
    # description -- so it is now labelled as one. Calling it "Release Notes -
    # Linux v6.18.21" told the reader a version by that name shipped; the
    # number in an advisory row is the *affected* version. Expectation changed
    # deliberately with vendor.classify_record.
    assert "Security Advisory - Linux advisory (affects Linux 6.18.21), 2026-08-28" in labels
    assert "Release Notes - Django v5.2.1, 2026-08-20" in labels
    # Rows from /api/reddit/query/cve are Reddit posts, not advisory records.
    # "CVE Feed" claimed a security feed had reported them; the endpoint
    # returns unfiltered community posts, so it is cited as a discussion.
    assert "Security Discussion - r/netsec, 2026-08-30" in labels
    assert "Community - r/linux, 2026-08-31" in labels


def test_release_notes_newlines_are_collapsed():
    # Raw kernel notes arrive with hard newlines; a citation line broken across
    # lines corrupts the bracketed prose.
    ev = collect_evidence(RESULTS)
    assert "\n" not in ev[0].detail
    assert "net: lwtunnel" in ev[0].detail


def test_deterministic_paragraph_cites_every_kind():
    ev = collect_evidence(RESULTS)
    text = deterministic_paragraph("Any critical Linux updates today?", ev,
                                   window_note="Aug 31, 2026")
    # Four kinds now, each counted on its own: a shipped release, an advisory
    # record, a Reddit security thread, and a community post. One count
    # covering the advisory and the thread overstated how much security
    # reporting existed -- an NVD record and an r/netsec post are not the same
    # kind of evidence.
    assert "[Release Notes - Django v5.2.1, 2026-08-20]" in text
    assert "1 advisory record(s) apply" in text
    assert "[Security Advisory - Linux advisory (affects Linux 6.18.21), 2026-08-28]" in text
    assert "Community security discussion adds 1 post(s)" in text
    assert "[Security Discussion - r/netsec, 2026-08-30]" in text
    assert "[Community - r/linux, 2026-08-31]" in text
    assert "Aug 31, 2026" in text
    # One paragraph, not a bullet template.
    assert "\n" not in text and "•" not in text


def test_empty_results_say_so_without_inventing():
    text = deterministic_paragraph("anything?", [])
    assert "[" not in text
    assert "no grounded answer" in text


def test_offline_mode_is_labelled_rule_based(monkeypatch):
    _no_env(monkeypatch)
    _no_model(monkeypatch)
    out = present_answer("Any critical Linux updates today?", RESULTS)
    assert out.mode == "rule-based"
    assert out.model == ""
    assert out.note == "no presenter model configured or reachable"
    assert out.evidence


def test_prompt_names_the_bracket_rule_and_only_listed_sources():
    ev = collect_evidence(RESULTS)
    prompt = build_cited_prompt("Any critical Linux updates today?", ev,
                                window_note="Aug 31, 2026")
    assert "square brackets" in prompt
    assert "ONLY the sources" in prompt
    assert "Time frame asked about: Aug 31, 2026" in prompt
    assert "[Security Advisory - Linux advisory (affects Linux 6.18.21), 2026-08-28]" in prompt


class _StubClient:
    spec = "stub:model"

    def __init__(self, text="", ok=True):
        self.text = text
        self.ok = ok
        self.prompt = None

    def available(self):
        return self.ok

    def generate(self, prompt, **kw):
        self.prompt = prompt
        if self.text == "boom":
            raise RuntimeError("transport failed")
        return self.text


def _patch_client(monkeypatch, client):
    import eval_harness.providers as providers
    monkeypatch.setattr(providers, "make_client", lambda spec: client)


def test_llm_path_used_when_a_model_is_available(monkeypatch):
    _no_env(monkeypatch)
    stub = _StubClient("Linux shipped a kernel security fix [Release Notes - Django v5.2.1, 2026-08-20].")
    _patch_client(monkeypatch, stub)
    out = present_answer("Any critical Linux updates today?", RESULTS,
                         model_spec="stub:model")
    assert out.mode == "llm"
    assert out.model == "stub:model"
    assert "[Release Notes" in out.text
    assert "Sources:" in stub.prompt


def test_unavailable_model_falls_back_and_names_the_reason(monkeypatch):
    _no_env(monkeypatch)
    _patch_client(monkeypatch, _StubClient("unused", ok=False))
    out = present_answer("q", RESULTS, model_spec="stub:model")
    assert out.mode == "rule-based"
    assert "not reachable" in out.note
    # Django is the only genuine release row in RESULTS; the Linux row is an
    # advisory and is cited as one.
    assert "[Release Notes - Django v5.2.1, 2026-08-20]" in out.text


def test_transport_failure_falls_back(monkeypatch):
    _no_env(monkeypatch)
    _patch_client(monkeypatch, _StubClient("boom"))
    out = present_answer("q", RESULTS, model_spec="stub:model")
    assert out.mode == "rule-based"
    assert "unavailable" in out.note


def test_empty_model_output_falls_back(monkeypatch):
    _no_env(monkeypatch)
    _patch_client(monkeypatch, _StubClient("   "))
    out = present_answer("q", RESULTS, model_spec="stub:model")
    assert out.mode == "rule-based"
    assert out.note == "model returned an empty answer"


def test_unsupported_model_output_is_refused_and_falls_back(monkeypatch):
    # Django 5.2.1 is in the pool; 5.9.9 is not, and neither is the label. The
    # answer reads fine, which is the point -- this is the failure a reader
    # cannot catch without the sources next to it.
    _no_env(monkeypatch)
    _patch_client(monkeypatch, _StubClient("Django 5.9.9 shipped [Release Notes - Django v5.9.9]."))
    out = present_answer("q", RESULTS, model_spec="stub:model")
    assert out.mode == "rule-based"
    assert "guardrail" in out.note
    assert "unsupported_version" in out.note and "unknown_citation" in out.note
    assert "5.9.9" not in out.text
    assert "[Release Notes - Django v5.2.1, 2026-08-20]" in out.text


def test_grounded_model_output_passes_the_guardrail(monkeypatch):
    # The check must not cost the LLM path: every fact here is in the pool.
    _no_env(monkeypatch)
    _patch_client(monkeypatch, _StubClient(
        "Django 5.2.1 is a routine bugfix release [Release Notes - Django v5.2.1, 2026-08-20]."))
    out = present_answer("q", RESULTS, model_spec="stub:model")
    assert out.mode == "llm" and out.note == ""


def test_env_supplies_the_spec_when_caller_does_not(monkeypatch):
    monkeypatch.setenv("PRESENTER_MODEL", "stub:model")
    _patch_client(monkeypatch, _StubClient("prose [Community - r/linux, 2026-08-31]"))
    out = present_answer("q", RESULTS)
    assert out.mode == "llm"


def test_model_selection_supplies_the_spec_when_nothing_else_does(monkeypatch):
    # No caller argument and no env var is the deployed default; the presenter
    # now asks model_select what is reachable rather than going offline.
    _no_env(monkeypatch)
    _no_model(monkeypatch, "stub:model")
    _patch_client(monkeypatch, _StubClient("prose [Community - r/linux, 2026-08-31]"))
    out = present_answer("q", RESULTS)
    assert out.mode == "llm" and out.model == "stub:model"


def test_env_beats_model_selection(monkeypatch):
    # An operator who names a model gets that model, reachable or not -- the
    # probe is a fallback, not an override.
    monkeypatch.setenv("PRESENTER_MODEL", "env:model")
    _no_model(monkeypatch, "stub:model")
    assert answer_agent._resolve_spec(None) == "env:model"
    assert answer_agent._resolve_spec("caller:model") == "caller:model"


def test_harness_synthesis_prompt_is_reused_not_rewritten():
    # The published answer numbers were produced with this exact instruction;
    # the presenter extends it, so a change there must be deliberate.
    from eval_harness.generators import SYNTHESIS_INSTRUCTION
    prompt = build_cited_prompt("q", collect_evidence(RESULTS))
    assert SYNTHESIS_INSTRUCTION in prompt


def test_compact_feed_dates_are_normalised_in_citations():
    # `versionReleaseDate` arrives as "20260828"; a citation reading
    # "Linux v6.13.0, 20260828" is harder to check than "2026-08-28".
    ev = collect_evidence({"releases": [
        {"product": "Linux", "version": "6.13.0", "date": "20260828",
         "notes": "n", "security": ["SECURITY"]}]})
    assert ev[0].label == "Release Notes - Linux v6.13.0, 2026-08-28"


def test_per_kind_controls_how_many_items_are_citable():
    results = {"releases": [{"product": "P", "version": str(i), "date": "20260828",
                             "notes": "", "security": []} for i in range(6)]}
    assert len(collect_evidence(results, per_kind=2)) == 2
    assert len(collect_evidence(results, per_kind=6)) == 6


def test_source_lines_repeat_the_date_and_security_marker():
    # llama3.1 answered "no critical Linux updates in the past 7 days" with
    # three in-window SECURITY releases listed above it: the facts have to be
    # in the body, not only inside the citation label.
    line = collect_evidence(RESULTS)[0].line()
    assert "dated 2026-08-28" in line and "SECURITY" in line


def test_prompt_tells_the_model_an_in_window_source_is_an_answer():
    prompt = build_cited_prompt("q", collect_evidence(RESULTS))
    assert "inside the time frame IS an answer" in prompt
    assert "no preamble" in prompt


# The label below is the advisory one, not "Release Notes - Linux v6.18.21":
# the guardrail rejects a citation that was never in the prompt, so a stub that
# cites a label collect_evidence no longer emits now falls back to rule-based.
@pytest.mark.parametrize("raw,expected_start", [
    ('Here is a flowing paragraph:\n\n"Linux shipped a fix [Security Advisory - Linux advisory (affects Linux 6.18.21), 2026-08-28]."',
     "Linux shipped a fix"),
    ('Answer: Linux shipped a fix [Security Advisory - Linux advisory (affects Linux 6.18.21), 2026-08-28].',
     "Linux shipped a fix"),
    ('Linux shipped a fix [Security Advisory - Linux advisory (affects Linux 6.18.21), 2026-08-28].',
     "Linux shipped a fix"),
])
def test_model_preamble_and_wrapping_quotes_are_stripped(monkeypatch, raw, expected_start):
    _no_env(monkeypatch)
    _patch_client(monkeypatch, _StubClient(raw))
    out = present_answer("q", RESULTS, model_spec="stub:model")
    assert out.mode == "llm"
    assert out.text.startswith(expected_start)
    assert not out.text.startswith('"')


def test_advisories_and_reddit_threads_are_counted_separately():
    # The demo reported "9 CVE discussion(s)" for a pool of 4 NVD advisories
    # and 5 unrelated Reddit posts. One number over both kinds is a claim
    # neither set supports.
    ev = collect_evidence(RESULTS)
    kinds = {e.kind for e in ev}
    assert "advisory" in kinds and "cve" in kinds
    text = deterministic_paragraph("q", ev)
    assert "1 advisory record(s)" in text
    assert "1 post(s)" in text


def test_a_reddit_row_is_never_labelled_as_an_advisory_feed():
    ev = collect_evidence({"cve": [{"title": "Password managers",
                                    "subreddit": "linuxquestions",
                                    "date": "2026-08-25", "url": ""}]})
    assert ev[0].label.startswith("Security Discussion")
    assert "CVE Feed" not in ev[0].label
