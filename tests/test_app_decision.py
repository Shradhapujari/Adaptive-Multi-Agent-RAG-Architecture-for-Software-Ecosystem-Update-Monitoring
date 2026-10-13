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


def test_a_release_question_does_not_decide_out_of_the_advisory_catalogue():
    """The bug this pins, measured on the local store: "Is the latest Linux
    kernel safe to update?" is a `release` question, whose citable kinds
    exclude `cve`. The pipeline had already dropped 49 advisory rows from the
    pool it shows -- and the verdict still came back `patch_urgently`, cited
    to two CISA KEV rows that reached it through the CVE pool. A verdict is an
    answer, so it obeys the same ruling the paragraph does."""
    results = {
        "community": [], "cve": [{"title": "[CISA KEV] Linux Kernel RCE",
                                  "detail": "CVE-2026-1234", "source": "cisa_kev",
                                  "url": "k1"}],
        "releases": [{"title": "linux v7.0.0", "notes": "stable", "url": "r1"}],
        "grounding": _Grounding("release", "community"),
    }
    pool = app_1._decide_pool(results)
    assert [d["source"] for d in pool] == ["vendor_releases"]
    assert decide.decide(pool, "is the latest Linux kernel safe to update?",
                         vendors=["Linux"]).verdict != "patch_urgently"
    # Same documents, a question whose intent does admit advisories.
    results["grounding"] = _Grounding("release", "cve", "community")
    assert decide.decide(app_1._decide_pool(results),
                         "any critical Linux vulnerabilities?",
                         vendors=["Linux"]).verdict == "patch_urgently"


def test_an_advisory_record_restored_into_the_release_pool_is_still_a_cve():
    """Step 4b's filter puts advisory rows back when dropping them would empty
    the pool, so `is_cve` rows reach here even for a question that cannot cite
    them. The pool a row arrived in does not decide its kind."""
    results = {
        "community": [], "cve": [],
        "releases": [{"title": "fedora v2366.521436.0 — In the Linux kernel, a vulnerability",
                      "notes": "CVE-2026-9999", "is_cve": True, "url": "a1"}],
        "grounding": _Grounding("release", "community"),
    }
    assert app_1._decide_pool(results) == []


def test_no_decision_renders_nothing():
    """A degraded fetch leaves no verdict, which is not a verdict of
    insufficient evidence -- the block has to stay silent rather than invent
    one."""
    assert app_1._decision_block({"decision": None}, details=True) is None
