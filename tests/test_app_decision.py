"""The demo's decision pool, in the shape the verdict rule reads.

`decide.decide` keys its source classes off a document's `source` field, and
the demo's own rows do not have one -- it is the pool they came back in that
says what they are. Two of those mappings are load-bearing:

  * /api/v/ returns NVD advisory records mixed in with releases (449 of 606
    rows for q=linux, measured 2026-09-01), and those are advisory-tier
    evidence, not release notes;
  * /api/reddit/query/cve is Reddit, not an advisory feed -- `is_security_post`
    exists because the rows it returns are posts. Classing them as advisories
    would hand `patch_urgently`, the highest-precedence verdict, to an upvoted
    comment thread.

And the text: community rows keep theirs in `body`, release rows in `notes`.
`eval_harness.generators.normalize_doc` reads neither, so a problem report
would reach the rule as a bare title and no community verdict would ever fire.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_1
import decide
import vendor


def _pool(**pools) -> list:
    return app_1._decide_pool({"community": [], "releases": [], "cve": [],
                               **pools})


def test_an_advisory_record_from_the_release_feed_is_advisory_tier():
    pool = _pool(releases=[{"title": "Linux v6.17 — CVE-2026-1234",
                            "notes": "CVE-2026-1234", "url": "r1",
                            "is_cve": True}])
    assert [d["source"] for d in pool] == ["nvd"]
    assert decide.decide(pool, "any critical Linux updates?",
                         vendors=["Linux"]).verdict == "patch_urgently"


def test_a_shipped_release_is_a_release_note():
    pool = _pool(releases=[{"title": "Linux v6.17", "notes": "stable",
                            "url": "r2"}])
    assert [d["source"] for d in pool] == ["vendor_releases"]
    assert decide.decide(pool, "latest Linux?", vendors=["Linux"]).verdict == "safe"


def test_a_post_from_the_cve_feed_cannot_order_an_urgent_patch():
    """The feed's name is not evidence of what its rows are."""
    pool = _pool(cve=[{"title": "Linux CVE-2026-1234 discussion", "url": "c1"},
                      {"title": "Linux CVE-2026-1234 thread two", "url": "c2"}])
    assert {d["source"] for d in pool} == {"reddit_live"}
    assert decide.decide(pool, "any critical Linux updates?",
                         vendors=["Linux"]).verdict != "patch_urgently"


def test_a_rows_own_source_wins_over_the_pool_default():
    """Terminal-shared documents arrive already classed; keep their class."""
    pool = _pool(cve=[{"title": "Linux under active exploitation",
                       "detail": "CVE-2026-1234", "source": "cisa_kev",
                       "url": "k1"}])
    assert [d["source"] for d in pool] == ["cisa_kev"]
    assert decide.decide(pool, "any critical Linux updates?",
                         vendors=["Linux"]).verdict == "patch_urgently"


def test_the_community_report_body_reaches_the_rule():
    """Titles alone say "update", not "broke"; the problem is in the body."""
    rows = [{"title": "Fedora 44 update", "body": "grub is broken after it",
             "url": "u1", "date": "2026-10-01"},
            {"title": "Fedora 44 update", "body": "boot loop here too, crashes",
             "url": "u2", "date": "2026-10-02"}]
    pool = _pool(community=rows)
    assert all(d["text"] for d in pool)
    assert decide.decide(pool, "is Fedora 44 safe to update?",
                         vendors=["Fedora"]).verdict == "hold"
    titles_only = app_1._decide_pool(
        {"community": [{k: v for k, v in r.items() if k != "body"} for r in rows]})
    assert decide.decide(titles_only, "is Fedora 44 safe to update?",
                         vendors=["Fedora"]).verdict != "hold"


class _Grounding:
    """Only what `_decide_pool` reads off a GroundedQuestion."""

    def __init__(self, *kinds):
        self.citable_kinds = kinds


def test_a_safety_question_still_sees_advisories_when_its_intent_excludes_cve():
    """The false green of 2026-10-14. "Is it safe to update Firefox right now?"
    matched intent.py's old opinion cue `is it (good|bad|safe|stable|worth)`, and
    `_CITABLE["opinion"]` is ("community", "release") -- so every advisory was
    filtered out of the pool before the rule ran, and the verdict came back
    `safe`, rationale "no advisory", while 11 Firefox advisories sat in the
    feed and one was 8 days old.

    `citable_kinds` governs what the *paragraph* may cite. A verdict is a
    safety judgement, and withholding advisory evidence from it is asymmetric:
    it can only ever manufacture a false green, never a false red."""
    results = {
        "community": [], "cve": [{"title": "Firefox use-after-free",
                                  "detail": "CVE-2026-5555", "source": "cisa_kev",
                                  "url": "k9"}],
        "releases": [{"title": "firefox v157.0.1", "notes": "stable", "url": "r9"}],
        "grounding": _Grounding("community", "release"),   # opinion intent
    }
    pool = app_1._decide_pool(results)
    assert "cisa_kev" in [d["source"] for d in pool]
    assert decide.decide(pool, "Is it safe to update Firefox right now?",
                         vendors=["firefox"]).verdict == "patch_urgently"


def test_advisories_step_4b_excluded_from_display_still_reach_the_verdict():
    """Step 4b strips NVD rows out of the release pool when `cve` is not
    citable, because an NVD row's versionNumber is an affected-version string
    and would be reported as the latest shipped version. That exclusion is
    right for display and wrong for the verdict, so 4b parks them in
    `decision_advisories` instead of dropping them.

    Without this the 2026-10-14 false green survives every downstream fix: the
    advisory is already gone before the decision pool is built, which is why
    that run showed "0 CVE" and still said "no advisory"."""
    results = {
        "community": [], "cve": [],
        "releases": [{"title": "firefox v157.0.1", "notes": "stable", "url": "r1"}],
        "decision_advisories": [
            {"title": "firefox 157.0.1",
             "notes": "Mitigation bypass in the File Handling component. "
                      "CVE-2026-5555", "is_cve": True, "url": "a1"}],
        "grounding": _Grounding("community", "release"),
    }
    pool = app_1._decide_pool(results)
    assert "nvd" in [d["source"] for d in pool]
    assert decide.decide(pool, "Is it safe to update Firefox right now?",
                         vendors=["firefox"]).verdict == "patch_urgently"


def test_citable_kinds_still_gates_community_and_release_rows():
    """`citable_kinds` governs the non-advisory kinds, which is what keeps a
    verdict from being decided out of a pool the question excluded from
    display. Advisories are the documented exception (see the test above);
    everything else still obeys the ruling.

    Reversed on 2026-10-14. This previously asserted that a `release`
    question's verdict could not reach the advisory catalogue at all -- which
    is what made "Is it safe to update Firefox right now?" return `safe` on a
    product with 11 live advisories."""
    results = {
        "community": [{"title": "linux 7.0 broke my boot", "body": "crashes",
                       "url": "u1"}],
        "cve": [],
        "releases": [{"title": "linux v7.0.0", "notes": "stable", "url": "r1"}],
        "grounding": _Grounding("release"),      # community not citable
    }
    assert [d["source"] for d in app_1._decide_pool(results)] == ["vendor_releases"]


def test_an_advisory_reaches_the_verdict_even_for_a_release_question():
    """"Is the latest Linux kernel safe to update?" classifies `release`, whose
    citable kinds exclude `cve`. The advisory still has to reach the verdict:
    the question asks about safety, and a CISA KEV row is the evidence that
    answers it."""
    results = {
        "community": [], "cve": [{"title": "[CISA KEV] Linux Kernel RCE",
                                  "detail": "CVE-2026-1234", "source": "cisa_kev",
                                  "url": "k1"}],
        "releases": [{"title": "linux v7.0.0", "notes": "stable", "url": "r1"}],
        "grounding": _Grounding("release", "community"),
    }
    assert decide.decide(app_1._decide_pool(results),
                         "is the latest Linux kernel safe to update?",
                         vendors=["Linux"]).verdict == "patch_urgently"


def test_an_advisory_record_restored_into_the_release_pool_is_still_a_cve():
    """Step 4b's filter puts advisory rows back when dropping them would empty
    the pool, so `is_cve` rows reach here even for a question that cannot cite
    them. The pool a row arrived in does not decide its kind -- and since
    2026-10-14 an advisory is admitted to the verdict whatever the citable
    kinds say, so the class it is given here is what the rule acts on."""
    results = {
        "community": [], "cve": [],
        "releases": [{"title": "fedora v2366.521436.0 — In the Linux kernel, a vulnerability",
                      "notes": "CVE-2026-9999", "is_cve": True, "url": "a1"}],
        "grounding": _Grounding("release", "community"),
    }
    assert [d["source"] for d in app_1._decide_pool(results)] == ["nvd"]


def test_no_decision_renders_nothing():
    """A degraded fetch leaves no verdict, which is not a verdict of
    insufficient evidence -- the block has to stay silent rather than invent
    one."""
    assert app_1._decision_block({"decision": None}, details=True) is None


# --- the headline sentence under a verdict --------------------------------

_PATCH_NOW = {"verdict": "patch_urgently", "verdict3": "act",
              "evidence_doc_ids": [], "obligations": {},
              "stop_reason": "obligations_met", "probes_wanted": [],
              "confidence": 1.0, "rationale": "1 advisory document(s) with a CVE id"}


def test_the_headline_drops_a_lead_the_verdict_block_already_showed():
    """`answer_agent.verdict_lead` puts the verdict at the front of the
    paragraph, and `_decision_block` renders the same sentence directly above
    -- so the compact view printed it twice and painted "Patch now" green."""
    lead = "Patch now: 1 advisory document(s) with a CVE id."
    line = app_1._answer_line({"decision": _PATCH_NOW},
                              f"{lead} Firefox 157.0.1 shipped on October 6.")
    assert "Patch now" not in line
    assert "157.0.1" in line


def test_the_headline_is_untouched_without_a_verdict():
    line = app_1._answer_line({}, "Firefox 157.0.1 shipped on October 6.")
    assert line == "Firefox 157.0.1 shipped on October 6."


def test_a_paragraph_that_is_only_its_lead_shows_nothing():
    """Nothing left to add once the lead is removed: the verdict block above
    is the whole answer, so a second box would repeat it."""
    lead = "Patch now: 1 advisory document(s) with a CVE id."
    assert app_1._answer_line({"decision": _PATCH_NOW}, lead) == ""


def test_the_apps_own_cve_flag_is_read_by_the_record_classifier():
    """`app_1` normalises a releasetrain row's `isCve` to `is_cve`, and
    `vendor.classify_record` only ever looked for the camelCase spelling -- so
    every advisory arriving through the app classified as a *release*.

    That is the whole 2026-10-14 contradiction in one field name. The verdict
    was right because `_decide_pool` tests `is_cve` itself; the paragraph was
    wrong because `collect_evidence` asks `classify_record`, got "release",
    and read a CVE description as a release note. Step 4b asks the same
    question, so it never set anything aside either."""
    row = {"product": "Firefox", "version": "157.0.1", "is_cve": True,
           "notes": "Mitigation bypass in the File Handling component.",
           "url": "https://www.mozilla.org/en-US/firefox/157.0.1/releasenotes/"}
    assert vendor.classify_record(row) == "advisory"
    assert not vendor.is_release_record(row)
