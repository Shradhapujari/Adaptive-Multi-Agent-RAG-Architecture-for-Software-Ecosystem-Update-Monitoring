"""Adaptive orchestrator: pick the answering arm for a query.

The project's claim is adaptivity -- that the system can decide *per question*
whether the multi-agent pipeline is worth its cost, instead of the user picking
a mode by hand. The decision reuses `intent.classify` (the same rule-based
classifier the pipeline already uses to weight pools), so routing and ranking
never disagree and the "why" the UI shows is the classifier's own trace.

Policy: a release/version lookup ("what is the latest Linux version?") is a fact
one retrieval + one synthesis answers well, so it goes to the single agent.
Everything else -- security, opinion, and anything the classifier is not
confident enough to label -- gets the multi-agent pipeline, where CVE
separation, the community tally and the decision gate earn their cost. Routing
toward multi on an unclear call matches `intent.classify`'s own bias: an unsure
classifier widens the search rather than narrowing it.
"""
from __future__ import annotations

import intent

__all__ = ["route_arm", "route_reason"]


def route_arm(query: str) -> str:
    """Return the arm for `query`: "single" or "multi"."""
    return "single" if intent.classify(query).label == "release" else "multi"


def route_reason(query: str) -> str:
    """A one-line, human-readable reason for the route, for the UI/trace."""
    return intent.classify(query).describe()


if __name__ == "__main__":
    # The required router self-check: release lookup -> single, everything else
    # -> multi. Run with `python orchestrator.py`.
    cases = {
        "what is the latest linux version?": "single",
        "is it safe to update firefox?": "multi",
        "any critical CVEs in chrome?": "multi",   # security -> multi
        "asdf": "multi",                           # unclear -> multi (widen)
    }
    for q, want in cases.items():
        got = route_arm(q)
        assert got == want, f"{q!r}: expected {want}, got {got}"
    print("orchestrator self-check OK:", len(cases), "cases")
