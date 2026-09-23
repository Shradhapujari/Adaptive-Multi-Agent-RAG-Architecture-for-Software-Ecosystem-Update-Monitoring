"""
Temporal grounding for retrieval queries.
=========================================
Dense retrieval scores similarity against document text, and a document
almost never contains the word "today" -- it contains a date. So a question
like "Any critical Linux updates today?" carries its most restrictive
constraint in a token that cannot match anything, and the retriever answers
the untimed question instead.

The fix is to resolve the deictic term *before* retrieval: rewrite it to the
absolute date it denotes, in both a human form and the ISO form the release
feeds actually use ("Aug 31, 2026 (2026-08-31)"), so lexical and embedding
scorers both have something to match.

This module is deliberately rule-based and pure, not an LLM call:

  * the mapping from "yesterday" to a date is arithmetic, and an LLM answers
    it wrong whenever its idea of the current date differs from the host's;
  * it must run on a host with no reachable model (the deployed Streamlit app
    has no Ollama), where the LLM rewriter degrades to its fallback;
  * being pure and clock-injected, it is testable without a network.

It runs *ahead* of the LLM query rewriter, so the rewriter also sees the
absolute date rather than the deictic word.

    >>> from datetime import date
    >>> resolve_temporal("Any critical Linux updates today?", now=date(2026, 8, 31)).query
    'Any critical Linux updates on Aug 31, 2026 (2026-08-31)?'
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
import os
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

__all__ = [
    "TemporalResolution",
    "resolve_temporal",
    "matches_window",
    "TEMPORAL_HINT_WORDS",
]

# Words that make a query time-relative. Exposed so a caller (or an eval
# stratifier) can label a question as temporal without running the rewrite.
TEMPORAL_HINT_WORDS = (
    "today", "yesterday", "tomorrow", "this week", "last week", "past week",
    "this month", "last month", "this year", "last year", "recently",
    "lately", "currently", "right now", "as of now", "at the moment",
    "past few days", "last few days",
)

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "couple": 2, "few": 3, "several": 3,
}


def _human(d: date) -> str:
    """'Aug 5, 2026' -- no zero padding, since feeds and prose both write it that way."""
    return d.strftime("%b %d, %Y").replace(" 0", " ")


def _point(d: date) -> str:
    return f"on {_human(d)} ({d.isoformat()})"


def _span(a: date, b: date) -> str:
    return f"between {_human(a)} and {_human(b)} ({a.isoformat()} to {b.isoformat()})"


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _prev_month(d: date) -> Tuple[date, date]:
    last_day_prev = _month_start(d) - timedelta(days=1)
    return _month_start(last_day_prev), last_day_prev


# ── Rules ────────────────────────────────────────────────────────────────
# (regex, handler) in match order: longest / most specific phrasing first, so
# "in the past 7 days" is consumed whole and never partially matched by a
# later, shorter rule.

def _rule_n_units(m: "re.Match", today: date):
    raw = m.group("n").lower()
    n = _NUMBER_WORDS.get(raw, None)
    if n is None:
        try:
            n = int(raw)
        except ValueError:
            return None
    if n <= 0:
        return None
    unit = m.group("unit").lower().rstrip("s")
    days = {"day": 1, "week": 7, "month": 30, "year": 365}[unit]
    start = today - timedelta(days=n * days)
    return _span(start, today), start, today


def _rule_this(m, today: date):
    unit = m.group(1).lower()
    if unit == "week":
        start = today - timedelta(days=today.weekday())  # Monday of this week
    elif unit == "month":
        start = _month_start(today)
    else:
        start = today.replace(month=1, day=1)
    # "this <unit>" is bounded by today, not by the unit's end: the future
    # half of the current week has no releases in it to find.
    return _span(start, today), start, today


def _rule_last(m, today: date):
    unit = m.group(1).lower()
    if unit == "week":
        this_monday = today - timedelta(days=today.weekday())
        start, end = this_monday - timedelta(days=7), this_monday - timedelta(days=1)
    elif unit == "month":
        start, end = _prev_month(today)
    else:
        y = today.year - 1
        start, end = date(y, 1, 1), date(y, 12, 31)
    return _span(start, end), start, end


def _rule_offset_day(days: int):
    def handler(m, today: date):
        d = today + timedelta(days=days)
        return _point(d), d, d
    return handler


# A point date is rendered "on Aug 31, 2026 (...)", which reads wrong after a
# preposition the question already supplied ("from yesterday" -> "from on
# Aug 30"). Drop the inserted "on" in that position.
_TRAILING_PREP = re.compile(
    r"\b(?:on|from|since|before|after|by|until|till|through|during|at|of|"
    r"between|about|around|per)\s+$", re.I)


def _rule_recent(m, today: date):
    start = today - timedelta(days=7)
    return _span(start, today), start, today


_RULES: List[Tuple[re.Pattern, object]] = [
    # "in the past 7 days", "over the last two weeks", "in the last 3 months"
    (re.compile(
        r"\b(?:in|over|during|within|from)?\s*(?:the\s+)?"
        r"(?:past|last|previous|preceding)\s+"
        r"(?P<n>\d+|a|an|one|two|three|four|five|six|seven|couple(?:\s+of)?|few|several)\s+"
        r"(?P<unit>days?|weeks?|months?|years?)\b", re.I), _rule_n_units),
    # "this week" / "this month" / "this year"
    (re.compile(r"\bthis\s+(week|month|year)\b", re.I), _rule_this),
    # "last week" / "past month" / "previous year"
    (re.compile(r"\b(?:last|past|previous)\s+(week|month|year)\b", re.I), _rule_last),
    (re.compile(r"\btoday\b", re.I), _rule_offset_day(0)),
    (re.compile(r"\byesterday\b", re.I), _rule_offset_day(-1)),
    (re.compile(r"\btomorrow\b", re.I), _rule_offset_day(1)),
    (re.compile(r"\b(?:right\s+now|as\s+of\s+now|at\s+the\s+moment|currently|"
                r"nowadays|at\s+present)\b", re.I), _rule_offset_day(0)),
    (re.compile(r"\b(?:recently|lately|in\s+recent\s+days)\b", re.I), _rule_recent),
]

# NOTE what is deliberately absent: "latest", "newest", "current version".
# Those are ordinal over versions, not deictic over dates -- "Latest Django
# release notes" wants the newest release whenever it shipped, and pinning it
# to today's date would narrow the query to nothing.


@dataclass
class TemporalResolution:
    """Result of grounding a query's relative time words."""

    original: str
    query: str
    stripped: str = ""
    terms: List[Tuple[str, str]] = field(default_factory=list)  # (matched, replacement)
    start: Optional[date] = None
    end: Optional[date] = None

    @property
    def changed(self) -> bool:
        return bool(self.terms)

    @property
    def fetch_phrasings(self) -> List[str]:
        """The phrasings a keyword fetch should be run against, in order.

        Two, not one, and for a measured reason: the release endpoint matches
        `q` against note text, where an absolute date almost never appears, so
        fetching on the grounded phrasing alone drops recall to zero on exactly
        the questions this module was added to help ("Any critical Linux
        updates today?" went 5 releases -> 0). Fetching both and unioning keeps
        the grounded phrasing available to any scorer that can use a date while
        the stripped phrasing still finds the documents; the window then
        filters and ranks what came back. Same shape as RetrieverAgent's
        two-phrasing union fetch.
        """
        if not self.changed:
            return [self.original]
        return [self.stripped or self.original, self.query]

    @property
    def window(self) -> Optional[Tuple[date, date]]:
        if self.start is None or self.end is None:
            return None
        return self.start, self.end

    def describe(self) -> str:
        """One line for the UI / trace: what was resolved to what."""
        if not self.changed:
            return "no relative time expression found"
        return "; ".join(f'"{a}" → {b}' for a, b in self.terms)


def now(default: Optional[datetime] = None) -> datetime:
    """The clock this process should treat as the present.

    Retrieval reads the clock: a question carrying "latest" or "last week"
    resolves to a date filter, and that filter decides which documents are
    fetched and kept. A corpus snapshot freezes the HTTP responses but not the
    clock, so the same snapshot replayed on two different days produced
    different candidate pools -- measured at 20.1 documents per question on the
    day of recording against 16.8 a day later, which is large enough to move
    every retrieval metric and to confound any comparison whose arms ran on
    different days.

    `MARAG_NOW` pins it. A replay sets it from the snapshot's own recording
    date (`corpus_snapshot`), so a frozen corpus is frozen in time as well as
    in content, and an explicit setting always wins.
    """
    raw = os.environ.get("MARAG_NOW", "").strip()
    if not raw:
        return default or datetime.now()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError(
            f"MARAG_NOW={raw!r} is not an ISO date or datetime "
            f"(e.g. 2026-09-21 or 2026-09-21T14:30:00)")


def resolve_temporal(query: str, now: Optional[date] = None) -> TemporalResolution:
    """Rewrite relative time expressions in `query` to absolute dates.

    `now` is injected rather than read from the clock inside the rules so a
    test (and a replayable evaluation run) is not date-dependent. Accepts a
    `date` or a `datetime`.
    """
    if isinstance(now, datetime):
        today = now.date()
    elif now is None:
        today = globals()["now"]().date()
    else:
        today = now

    out = query
    terms: List[Tuple[str, str]] = []
    starts: List[date] = []
    ends: List[date] = []

    for pattern, handler in _RULES:
        # Rewrite left to right, re-scanning from the end of each replacement
        # so an inserted date string is never itself re-matched.
        pos = 0
        while True:
            m = pattern.search(out, pos)
            if not m:
                break
            resolved = handler(m, today)
            if resolved is None:          # e.g. "past 0 days" -- leave it alone
                pos = m.end()
                continue
            text, start, end = resolved
            if text.startswith("on ") and _TRAILING_PREP.search(out[:m.start()]):
                text = text[3:]
            matched = m.group(0).strip()
            out = out[:m.start()] + text + out[m.end():]
            pos = m.start() + len(text)
            terms.append((matched, text))
            starts.append(start)
            ends.append(end)

    return TemporalResolution(
        original=query,
        query=re.sub(r"\s{2,}", " ", out).strip(),
        stripped=_strip(query, today),
        terms=terms,
        start=min(starts) if starts else None,
        end=max(ends) if ends else None,
    )


def _strip(query: str, today: date) -> str:
    """The query with its time expressions removed rather than resolved.

    Used for the keyword fetch: "updates since yesterday" retrieves as
    "updates", which matches documents; as "updates since Aug 30, 2026
    (2026-08-30)" it matches almost nothing.
    """
    out = query
    for pattern, handler in _RULES:
        pos = 0
        while True:
            m = pattern.search(out, pos)
            if not m:
                break
            if handler(m, today) is None:      # left alone by resolve too
                pos = m.end()
                continue
            out = out[:m.start()] + " " + out[m.end():]
            pos = m.start()
    # A dangling preposition or connective left by the removal reads as noise
    # to a keyword scorer: "updates since ?" -> "updates?"
    out = re.sub(r"\b(?:on|from|since|before|after|by|until|till|through|during|"
                 r"at|in|of|between|and)\s+(?=[?.!,]|$)", "", out, flags=re.I)
    out = re.sub(r"\s+([?.!,])", r"\1", out)
    return re.sub(r"\s{2,}", " ", out).strip()


# The release feed does not publish one date format: `versionReleaseDate`
# arrives as "20260828" while Reddit's `created_utc` arrives as
# "2026-08-31T04:00:00Z". Parsing only the ISO form silently reported every
# release as undated, which showed up as "0 of 5 in window" on a query whose
# releases were sitting right there.
_DATE_FORMATS = ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y", "%m/%d/%Y", "%b %d, %Y")


def _parse_date(value: str) -> Optional[date]:
    text = value.strip()
    for fmt in _DATE_FORMATS:
        width = 10 if "-" in fmt or "/" in fmt else (8 if fmt == "%Y%m%d" else len(text))
        try:
            return datetime.strptime(text[:width], fmt).date()
        except ValueError:
            continue
    return None


def matches_window(date_str: str, res: TemporalResolution) -> Optional[bool]:
    """Is an ISO-ish `date_str` inside the resolution's window?

    Returns None when there is no window or the string is not parseable, so a
    caller can tell "outside the window" from "cannot tell" -- an unparseable
    date must not be silently reported as a miss.
    """
    win = res.window
    if not win or not date_str:
        return None
    d = _parse_date(str(date_str))
    if d is None:
        return None
    return win[0] <= d <= win[1]
