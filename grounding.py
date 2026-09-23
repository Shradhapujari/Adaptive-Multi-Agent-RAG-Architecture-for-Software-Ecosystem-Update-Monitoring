"""
The shared pre-retrieval layer.
===============================
Temporal grounding, vendor detection, intent classification and stopword
removal all run *before* retrieval and none of them is the multi-agent
treatment. They are question understanding, and a single-agent baseline can
run every one of them without becoming multi-agent.

That distinction is the whole point of this module. The evaluation compares a
coordination layer -- union fetch, orchestrator retry, template rendering --
against its own ablation. If the grounding steps were reachable only from the
multi-agent pipeline, then every measured gap would be the sum of "coordination
helps" and "understanding the question helps", and the paper could not claim
the first. Adding capabilities to only one arm is how a comparison stops being
a comparison.

So the grounding lives here, in one function both arms call, and the ladder's
rungs stay single-factor:

    ground(question) -> GroundedQuestion
                         .retrieval_phrasings   what to fetch on
                         .rewritten             what to show a human
                         .intent                which pools may be cited
                         .vendors               which products are in scope

The advisor's worked example, end to end:

    in    "What is the latest Linux version?"
    out   rewritten          "What is the latest Linux kernel version on
                              Sep 1, 2026 (2026-09-01)?"
          vendors            ["linux"]
          intent             release  (so CVE rows are not citable)
          retrieval phrasings ["linux", "latest Linux version", ...]

Every step is rule-based and clock-injected, so the whole layer is
reproducible offline and a replayed evaluation run grounds a question exactly
as the original run did.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence

import intent as _intent
import keywords as _keywords
import vendor as _vendor
from temporal import TemporalResolution, resolve_temporal
from temporal import now as _clock

__all__ = ["GroundedQuestion", "ground", "AS_OF_WORDS"]

# "What is the latest X?" carries a time reference with no time word in it: the
# answer is only true as of a date, and a reader who sees the answer later
# cannot tell which date it was true on. `temporal` deliberately does not
# resolve these -- pinning "latest" to a single day narrows the retrieval query
# to nothing, which was measured -- so the as-of date is added to the
# human-facing rewrite only, never to a phrasing that gets fetched on.
AS_OF_WORDS = ("latest", "newest", "current", "currently", "right now",
               "at the moment", "as of now", "up to date", "most recent")

_AS_OF_RE = re.compile("|".join(rf"\b{re.escape(w)}\b" for w in AS_OF_WORDS), re.I)


@dataclass
class GroundedQuestion:
    """A question with everything the retrievers need decided up front."""

    original: str
    rewritten: str
    temporal: TemporalResolution
    vendors: List[_vendor.VendorMatch] = field(default_factory=list)
    intent: Optional[_intent.Intent] = None
    terms: List[str] = field(default_factory=list)

    @property
    def vendor_names(self) -> List[str]:
        return [v.name for v in self.vendors]

    @property
    def retrieval_phrasings(self) -> List[str]:
        """What to send to a keyword endpoint, best first.

        Vendor terms lead because `/api/v/` matches `q` against product names
        and nothing else: measured 2026-09-01, `q=linux` returns 606 rows and
        `q="linux version"` returns 0. The stopword-stripped phrasing and the
        date-grounded phrasing follow, because the Reddit endpoints do take
        free text and a scorer downstream can use the date.
        """
        out: List[str] = []
        for phrase in (self.vendor_names
                       + [_keywords.strip_stopwords(self.temporal.stripped or self.original,
                                                    keep=self.vendor_names)]
                       + self.temporal.fetch_phrasings):
            phrase = (phrase or "").strip()
            if phrase and phrase.lower() not in [o.lower() for o in out]:
                out.append(phrase)
        return out

    @property
    def retrieval_query(self) -> str:
        """The single phrasing to send to a general keyword retriever.

        Distinct from `retrieval_phrasings`, and the distinction is the point.
        That list leads with the bare product name because `/api/v/` matches
        `q` against product names and nothing else -- "linux" returns 606 rows
        where "linux version" returns 0. A general retriever scoring over mixed
        text has the opposite need: the discriminating token is usually the one
        the product name does not carry.

        Measured on benchmark question 29, "Is Mozilla Firefox v148.0.0 the
        latest release, or is there a newer one?", retrieving on the bare
        "firefox" scored recall@5 0.00 against 1.00 for the unmodified
        question, because "v148.0.0" is what identifies the answer and the
        product name alone does not narrow 606 Firefox rows to it. Question 4
        lost the same way on "Tahoe 26.3.1".

        So this keeps the product *and* the content terms: stopwords removed,
        products first, version strings and other content words retained.
        """
        return _keywords.keyword_query(
            self.temporal.stripped or self.original, self.vendor_names)

    @property
    def citable_kinds(self) -> Sequence[str]:
        return _intent.citable_kinds(self.intent) if self.intent else \
            ("release", "cve", "community")

    @property
    def pool_weights(self) -> Dict[str, float]:
        return _intent.pool_weights(self.intent) if self.intent else \
            {"release": 1.0, "cve": 1.0, "community": 1.0}

    @property
    def needs_clarification(self) -> bool:
        """Whether the question was too thin to route.

        True when no product was named and no intent cue fired. The honest
        response is to say so and ask, not to answer from whatever the feeds
        happened to return -- which is what produced the answers that read as
        hallucinations.
        """
        return not self.vendors and not (self.intent and self.intent.confident)

    def describe(self) -> List[str]:
        """Trace lines for the UI, one per grounding step."""
        lines = [f"temporal: {self.temporal.describe()}"]
        lines.append("vendors: " + (", ".join(
            f"{v.matched} → {v.name}" for v in self.vendors) or "none detected"))
        lines.append("intent: " + (self.intent.describe() if self.intent else "not classified"))
        lines.append("terms: " + (" ".join(self.terms) or "none"))
        return lines


def _as_of(question: str, today: date) -> str:
    """Append the as-of date to a "latest ...?" question, keeping punctuation.

    Same date forms `temporal` uses -- human and ISO -- so the rewritten
    question reads naturally and still carries the string the feeds publish.
    """
    stamp = f"on {today.strftime('%b %d, %Y').replace(' 0', ' ')} ({today.isoformat()})"
    body = question.rstrip()
    trailing = ""
    while body and body[-1] in "?!.":
        trailing = body[-1] + trailing
        body = body[:-1]
    return f"{body.rstrip()} {stamp}{trailing}"


def ground(question: str, now: Optional[date] = None,
           catalog: Optional[Sequence[str]] = None) -> GroundedQuestion:
    """Run every pre-retrieval step over `question`.

    `now` and `catalog` are injected for the same reason: a grounding step that
    reads the wall clock or re-downloads a changing product list would make a
    replayed evaluation run disagree with the original.

    Order matters. Temporal grounding runs first because it rewrites the
    question text that the later steps read; vendor detection runs on the
    *stripped* phrasing so a resolved date cannot be mistaken for a version
    number; intent is classified on the original wording, which is where the
    user's cues actually are.
    """
    temporal = resolve_temporal(question, now=now)
    base = temporal.stripped or question

    vendors = _vendor.detect_vendors(base, catalog)
    label = _intent.classify(question)

    # Disambiguate first, then ground the date, so the human-facing rewrite
    # reads as one sentence: "the latest Linux kernel version on Sep 1, 2026".
    rewritten = _vendor.disambiguate(question, vendors)
    if temporal.changed:
        rewritten = _vendor.disambiguate(temporal.query, vendors)
    elif _AS_OF_RE.search(question):
        # `temporal` is this function's TemporalResolution, not the module, so
        # the clock has to be reached through the import alias.
        rewritten = _as_of(rewritten, now or _clock().date())

    return GroundedQuestion(
        original=question,
        rewritten=rewritten,
        temporal=temporal,
        vendors=vendors,
        intent=label,
        terms=_keywords.content_terms(base, keep=[v.name for v in vendors]),
    )
