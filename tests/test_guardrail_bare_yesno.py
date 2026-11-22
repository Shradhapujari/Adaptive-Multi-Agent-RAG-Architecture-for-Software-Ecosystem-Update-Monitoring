"""An answer that is only "Yes" or "No" reports nothing and fails the guardrail.

"Should I upgrade to Arch v2026.01.01?" was answered "Yes. [Community - r/arch]"
under an insufficient-evidence verdict in the 2026-11-21 demo sweep.
"""
import pytest

import guardrail
from answer_agent import Evidence

EV = [Evidence(label="Community - r/arch", kind="community",
               title="Arch 2026.01.01 ISO is out", detail="Installed fine here.")]
Q = "Should I upgrade to Arch v2026.01.01?"


@pytest.mark.parametrize("answer", [
    "Yes. [Community - r/arch]",
    "No [Community - r/arch].",
    "Yes.",
])
def test_bare_yes_or_no_fails(answer):
    codes = [v.code for v in guardrail.check(answer, EV, Q).violations]
    assert "bare_yesno" in codes


@pytest.mark.parametrize("answer", [
    "Yes: one user reports the 2026.01.01 ISO installed fine [Community - r/arch].",
    "No problems are reported yet; one user says it installed fine [Community - r/arch].",
])
def test_yes_or_no_with_a_finding_is_not_bare(answer):
    codes = [v.code for v in guardrail.check(answer, EV, Q).violations]
    assert "bare_yesno" not in codes
