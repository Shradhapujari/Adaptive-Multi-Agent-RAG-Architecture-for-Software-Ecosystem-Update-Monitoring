"""Egress: a CVE id in the answer must come from Tier-1 evidence -- a release
note, an advisory, or the vendor's own page. A forum post, an open-web
snippet or the question itself cannot vouch for one."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import guardrail
from answer_agent import Evidence

Q = "Is it safe to update Node.js?"


def _codes(answer, ev, q=Q):
    return [v.code for v in guardrail.check(answer, ev, q).violations]


def test_cve_only_in_a_forum_post_is_unsupported():
    ev = [Evidence(label="C1", kind="community", title="node broke",
                   detail="heard CVE-2026-9999 is exploited")]
    assert "unsupported_cve" in _codes("Node.js is affected by CVE-2026-9999 [C1].", ev)


def test_cve_only_in_an_open_web_snippet_is_unsupported():
    ev = [Evidence(label="Web - example.com", kind="web", title="blog",
                   detail="CVE-2026-9999 hits node")]
    assert "unsupported_cve" in _codes(
        "Node.js is affected by CVE-2026-9999 [Web - example.com].", ev)


def test_cve_in_an_advisory_is_supported():
    ev = [Evidence(label="A1", kind="advisory", title="CVE-2026-4444",
                   detail="Node.js request smuggling")]
    assert "unsupported_cve" not in _codes("Node.js is affected by CVE-2026-4444 [A1].", ev)


def test_cve_in_a_release_note_is_supported():
    ev = [Evidence(label="R1", kind="release", title="Node.js v24.9.1",
                   detail="fixes CVE-2026-4444")]
    assert "unsupported_cve" not in _codes("Node.js 24.9.1 fixes CVE-2026-4444 [R1].", ev)


def test_cve_on_the_vendors_own_page_is_supported():
    ev = [Evidence(label="Vendor page - nodejs.org", kind="web", title="Security releases",
                   detail="fixes CVE-2026-4444")]
    assert "unsupported_cve" not in _codes(
        "The October release fixes CVE-2026-4444 [Vendor page - nodejs.org].", ev)


def test_question_cannot_vouch_for_an_asserted_cve():
    ev = [Evidence(label="R1", kind="release", title="Node.js v24.9.1", detail="bug fixes")]
    q = "Is CVE-2026-8888 fixed in Node.js?"
    assert "unsupported_cve" in _codes("Yes, CVE-2026-8888 is fixed in Node.js 24.9.1 [R1].", ev, q)


def test_a_refusal_may_name_the_asked_cve():
    ev = [Evidence(label="R1", kind="release", title="Node.js v24.9.1", detail="bug fixes")]
    q = "Is CVE-2026-8888 fixed in Node.js?"
    v = guardrail.check("I cannot determine from the sources retrieved whether "
                        "CVE-2026-8888 is fixed, so I am not going to state it.", ev, q)
    assert "unsupported_cve" not in [x.code for x in v.violations]
