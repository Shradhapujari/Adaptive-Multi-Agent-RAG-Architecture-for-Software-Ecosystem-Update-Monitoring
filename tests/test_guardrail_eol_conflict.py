"""An answer may not call a release cycle supported when its source says support ended.

Live sweep (2026-11-25): "Is Python 3.9 still supported?" got "Python 3.9 is
still supported, with the latest version being 3.9.25 [endoflife.date -
python 3.9]" over a source reading "Python 3.9: support ended 2025-10-31 (1
year ago, as of 2026-11-25)". Every version and the citation were real, so
nothing caught it.
"""
import pytest

import guardrail
from answer_agent import Evidence

ENDED = "Python 3.9: support ended 2025-10-31 (1 year ago, as of 2026-11-25), latest 3.9.25."
EV = [Evidence(label="endoflife.date - python 3.9", kind="community",
               title="python end of life", detail=ENDED)]
MIXED = [Evidence(label="endoflife.date - python", kind="community", title="python end of life",
                  detail="Python 3.14: supported until 2030-10-31 (3 years left, as of 2026-11-25), "
                         "latest 3.14.2; " + ENDED)]
CITE = " [endoflife.date - python 3.9]"


def codes(answer, ev=EV, q="Is Python 3.9 still supported?"):
    return [v.code for v in guardrail.check(answer, ev, q).violations]


@pytest.mark.parametrize("answer", [
    "Python 3.9 is still supported, with the latest version being 3.9.25." + CITE,
    "Yes, Python 3.9 remains supported." + CITE,
    "Python 3.9 is supported until further notice." + CITE,
])
def test_supported_claim_over_ended_source_fails(answer):
    assert "eol_conflict" in codes(answer)


@pytest.mark.parametrize("answer,ev", [
    ("Python 3.9 is no longer supported; support ended on 2025-10-31." + CITE, EV),
    ("Python 3.9 is not supported anymore." + CITE, EV),
    ("Python 3.9 is unsupported since 2025-10-31." + CITE, EV),
    # Another cycle in the same source is still supported, and saying so is right.
    ("Python 3.14 is still supported until 2030-10-31 [endoflife.date - python].", MIXED),
    # 3.9.25 is a point release, not the 3.9 cycle being called supported.
    ("Python 3.14 is still supported; 3.9.25 was the last 3.9 release [endoflife.date - python].", MIXED),
])
def test_correct_answers_are_not_flagged(answer, ev):
    assert "eol_conflict" not in codes(answer, ev)
