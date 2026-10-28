"""
Intent classification: what kind of question was asked.
=======================================================
The pipeline runs three retrieval agents -- release notes, CVE feed, community
posts -- and, until now, ran all three at full weight on every question. That
is why "What is the latest Linux version?" came back led by security advisories:
the CVE pool is far larger than the release pool (449 vs 157 rows for `q=Linux`,
measured 2026-09-01), so an unweighted union is a security answer whatever was
asked.

Three intents, because they are the three the corpus actually distinguishes and
each one routes differently:

    security   "Any critical CVEs in Chrome?"        -> advisories are evidence
    release    "What is the latest Linux version?"   -> only shipped releases
    opinion    "Is anyone else hating the new UI?"   -> community posts are
                                                        evidence, releases are
                                                        context

The distinction matters beyond ranking. For a `release` question a CVE record
is not weak evidence, it is *wrong* evidence -- its `versionNumber` is an
affected-version string, not a version that shipped (see `vendor.classify_record`).
For an `opinion` question the honest answer cites what people said, and a
release note is not a person's opinion. So intent decides which pools may be
cited at all, not merely what to put first.

Rule-based and clock-free, for the reasons `temporal` and `vendor` are: it runs
where no model is reachable and has to be testable offline. `classify` returns
the scores alongside the label so a caller can see how close the runner-up was
and a weak call can be surfaced as "needs clarification" rather than guessed at.

Ground truth for the accuracy claim is upstream's own labelling: the
`/api/reddit/query/questions` endpoint carries `isAboutCve` per post over 5,189
real user questions. `scripts/eval_intent.py` scores this classifier against it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = [
    "Intent",
    "INTENTS",
    "classify",
    "classify_label",
    "pool_weights",
    "citable_kinds",
]

INTENTS = ("security", "release", "opinion")

# Weighted cues. A cue is worth 2 when it can only belong to one intent
# ("cve", "vulnerability") and 1 when it merely leans ("patch" appears in both
# security and release questions). Weights are small integers on purpose: the
# classifier has to stay readable and hand-correctable, and a fitted model over
# 5,189 posts would be a second research contribution rather than a filter.
_CUES: Dict[str, List[Tuple[str, int]]] = {
    "security": [
        (r"\bcves?\b", 3), (r"\bcve-\d{4}-\d+", 3),
        (r"\bvulnerab\w*", 3), (r"\bexploit\w*", 3), (r"\bzero[- ]day\b", 3),
        (r"\bmalware\b", 3), (r"\bransomware\b", 3), (r"\brce\b", 3),
        (r"\bsecurity\b", 2), (r"\bcompromis\w*", 2), (r"\bbreach\w*", 2),
        (r"\battack\w*", 2), (r"\bpatched?\b", 1), (r"\bcritical\b", 2),
        (r"\badvisor(?:y|ies)\b", 2), (r"\bhard(?:en|ening)\b", 1),
        (r"\bunsafe\b", 1), (r"\binsecure\b", 2),
        # "Is it safe to update X?" is the security question a user actually
        # asks. It was an opinion cue, and opinion cannot cite `cve`, so the
        # answer was built from a pool with every advisory filtered out -- the
        # false green of 2026-10-14. Question shapes only: a bare "safe" also
        # fires on "type-safe", "safe mode" and "safe to delete".
        (r"\b(?:how safe|stay safe|is (?:it|this|that)(?: now| still| actually)? safe"
         r"|safe to (?:update|upgrade|install|patch|run|use)"
         r"|(?:update|upgrade|install)\w* safe)\b", 3),
    ],
    "release": [
        (r"\blatest\b", 2), (r"\bnewest\b", 2), (r"\bcurrent\b", 1),
        (r"\bversion\b", 2), (r"\brelease(?:d|s)?\b", 2),
        (r"\bchangelog\b", 3), (r"\brelease notes?\b", 3),
        (r"\bupdates?\b", 1), (r"\bupgrad\w*", 1), (r"\bship(?:ped|s)?\b", 1),
        (r"\bwhat(?:'s| is) new\b", 2), (r"\brolled? out\b", 2),
        (r"\bwhen (?:will|is|does|was)\b", 1), (r"\bstable\b", 1),
        (r"\bLTS\b", 2), (r"\brc\d*\b", 1), (r"\bbeta\b", 1),
        (r"\bwhat changed\b", 3), (r"\brelease channel\b", 3),
        # "What bugs were fixed in Chrome recently?" is a changelog question:
        # it asks what a release contained, not whether anything is exploitable.
        (r"\bwhat bugs\b", 2), (r"\bbugs? (?:were |was |got )?fixed\b", 2),
        (r"\bfixed in\b", 2), (r"\bbug ?fix(?:es|ed)?\b", 2),
        # Naming a concrete version is itself the strongest release cue in the
        # benchmark: 41 of the 100 questions do it, and a question that quotes
        # a version number is asking about that version, not about opinion.
        (r"\bv?\d+\.\d+(?:\.\d+)*\b", 1),
    ],
    "opinion": [
        (r"\bshould i\b", 3), (r"\bworth it\b", 3), (r"\bany good\b", 3),
        (r"\bthoughts?\b", 2), (r"\bopinions?\b", 3), (r"\bprefer\w*", 2),
        (r"\brecommend\w*", 2), (r"\bbetter than\b", 2), (r"\bvs\.?\b", 2),
        (r"\banyone else\b", 3), (r"\bam i the only\b", 3),
        (r"\bhate[sd]?\b", 2), (r"\blove[sd]?\b", 2), (r"\bannoying\b", 2),
        (r"\bfrustrat\w*", 2), (r"\bexperience\w*", 1), (r"\bfeel(?:s|ing)?\b", 1),
        (r"\bis it (?:good|bad|stable|worth)\b", 3),
        (r"\bwhy (?:do|does|is) everyone\b", 2), (r"\bdisappoint\w*", 2),
        (r"\breaction\b", 2), (r"\bbacklash\b", 3), (r"\bcomplain\w*", 2),
        (r"\bsentiment\b", 2), (r"\bnegative\b", 2), (r"\bpositive\b", 1),
        (r"\bcommunity\b", 1), (r"\breviews?\b", 2), (r"\bregret\w*", 2),
    ],
}

_COMPILED: Dict[str, List[Tuple[re.Pattern, int]]] = {
    label: [(re.compile(p, re.I), w) for p, w in cues]
    for label, cues in _CUES.items()
}

# Below this the top score is not a call. The pipeline treats it as
# "needs clarification" and falls back to searching every pool, which is the
# old behaviour -- an unsure classifier should not narrow retrieval.
CONFIDENCE_FLOOR = 2

# Which document kinds may be cited for each intent. A CVE advisory is excluded
# from a release answer because its version field does not mean what a release
# answer needs it to mean; community posts stay available everywhere because a
# person reporting a broken update is evidence for any of the three.
_CITABLE: Dict[str, Tuple[str, ...]] = {
    "security": ("cve", "release", "community"),
    "release":  ("release", "community"),
    "opinion":  ("community", "release"),
}

# Retrieval weights per intent, used to order the merged pool. Same pools are
# fetched either way -- weighting decides rank, not membership, so a
# misclassification costs position and never costs a document.
_WEIGHTS: Dict[str, Dict[str, float]] = {
    "security": {"cve": 1.0, "release": 0.7, "community": 0.4},
    "release":  {"release": 1.0, "community": 0.4, "cve": 0.1},
    "opinion":  {"community": 1.0, "release": 0.4, "cve": 0.2},
    "unknown":  {"release": 1.0, "cve": 1.0, "community": 1.0},
}


@dataclass
class Intent:
    """A classified question."""

    label: str                                   # security | release | opinion
    confident: bool
    scores: Dict[str, int] = field(default_factory=dict)
    hits: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def runner_up(self) -> Optional[str]:
        ranked = sorted(self.scores.items(), key=lambda kv: -kv[1])
        return ranked[1][0] if len(ranked) > 1 and ranked[1][1] > 0 else None

    @property
    def margin(self) -> int:
        ranked = sorted(self.scores.values(), reverse=True)
        return (ranked[0] - ranked[1]) if len(ranked) > 1 else ranked[0]

    def describe(self) -> str:
        """One line for the UI / trace."""
        if not self.confident:
            top = ", ".join(f"{k} {v}" for k, v in
                            sorted(self.scores.items(), key=lambda kv: -kv[1]))
            return f"no clear intent ({top}) — searching every source"
        cues = ", ".join(self.hits.get(self.label, [])[:4])
        return f"{self.label} question (cues: {cues})" if cues else f"{self.label} question"


def classify(query: str) -> Intent:
    """Label `query` as a security, release or opinion question.

    Ties resolve toward `security`, then `release`: under-reporting a security
    question is the costlier error for a user monitoring their ecosystem, and a
    tie is by definition a question carrying both kinds of cue.
    """
    scores: Dict[str, int] = {}
    hits: Dict[str, List[str]] = {}
    for label, cues in _COMPILED.items():
        total, matched = 0, []
        for pattern, weight in cues:
            m = pattern.search(query)
            if m:
                total += weight
                matched.append(m.group(0).lower())
        scores[label] = total
        hits[label] = matched

    best = max(INTENTS, key=lambda l: (scores[l], -INTENTS.index(l)))
    confident = scores[best] >= CONFIDENCE_FLOOR
    return Intent(label=best if confident else "unknown",
                  confident=confident, scores=scores, hits=hits)


def classify_label(query: str) -> str:
    """Just the label, for callers that do not need the trace."""
    return classify(query).label


def pool_weights(intent: Intent) -> Dict[str, float]:
    """Per-source ranking weights for a classified question."""
    return dict(_WEIGHTS.get(intent.label, _WEIGHTS["unknown"]))


def citable_kinds(intent: Intent) -> Tuple[str, ...]:
    """Which document kinds the answer may cite for this intent.

    An unconfident call cites everything: the classifier declining to choose
    must not make the answer narrower than it was before the classifier existed.
    """
    return _CITABLE.get(intent.label, ("release", "cve", "community"))
