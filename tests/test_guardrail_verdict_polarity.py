"""Under "Patch now" the answer may not tell the reader not to update.

Live sweeps (2026-11-21) passed "It is not safe to update Firefox right now
[CVE...]" and "It is not safe to update Edge." under a Patch-now lead: the
advisories are fixed *by* updating, so the answer points the wrong way.
"""
import pytest

import guardrail
from answer_agent import Evidence

EV = [Evidence(label="Security Advisory - CVE-2026-1", kind="advisory",
               title="CVE-2026-1", detail="Sandbox escape fixed in Firefox 160.")]
LEAD = "Patch now: 1 advisory document(s) with a CVE id name this product."
CITE = " [Security Advisory - CVE-2026-1]"


def codes(answer, lead=LEAD):
    return [v.code for v in guardrail.check(answer, EV, "Is it safe to update Firefox?", lead=lead).violations]


@pytest.mark.parametrize("answer", [
    "It is not safe to update Firefox." + CITE,
    "It isn't safe to upgrade Firefox yet." + CITE,
    "You should not update Firefox." + CITE,
    "Do not install Firefox 160." + CITE,
])
def test_do_not_update_under_patch_now_fails(answer):
    assert "verdict_conflict" in codes(answer)


@pytest.mark.parametrize("answer,lead", [
    ("Update Firefox: a sandbox escape was fixed in 160." + CITE, LEAD),
    ("It is not safe to stay on Firefox 159." + CITE, LEAD),
    ("It is not safe to update Firefox." + CITE, "Hold off on this update: 3 community reports."),
])
def test_other_answers_are_not_flagged(answer, lead):
    assert "verdict_conflict" not in codes(answer, lead)
