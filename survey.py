"""
User priorities from the 2024 software-update survey (n=52).

The evaluator scores retrieval quality by counting how many documents came
back and how well their words overlap the question. Nothing in that score
knows what people actually want out of an update notice. The survey does: 52
respondents were asked what motivates them to install an update, what makes
them delay one, and what would make them install sooner.

Three of its columns are multi-select and therefore countable, and the
free-text columns say the same things in prose. This module folds both into
weights over a handful of priorities, and scores a run's retrieved documents
by how much of that weight they actually address.

The weights are read from the CSV at load, never hardcoded -- re-run the
survey with more respondents, drop the new export in, and the numbers move.
What *is* hand-written is the mapping from a survey option to the vocabulary
documents use for it ("Size" -> "download", "MB"), because no amount of survey
data supplies that; it is listed per priority below so it can be argued with.

Advisory by design: this ranks nothing and drops nothing. It reports which of
the users' stated priorities a set of results speaks to, and the app blends
that into the quality score only while the toggle is on.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Sequence

__all__ = ["priorities", "alignment", "respondents", "SURVEY_CSV"]

SURVEY_CSV = Path(__file__).with_name("data") / "SoftwareUpdateSurvey.csv"

# label            : shown in the UI
# options          : exact multi-select answers that vote for this priority
# cues             : free-text words that count a respondent as raising it
# doc_terms        : how the same concern shows up in a release note or post
PRIORITIES: Dict[str, dict] = {
    "security": {
        "label": "Security & urgency",
        "options": ["Safety", "Urgency"],
        "cues": ["security", "safety", "secure", "vulnerab", "hack", "malware",
                 "virus", "privacy", "critical", "urgent"],
        "doc_terms": ["security", "vulnerability", "cve", "exploit", "patch",
                      "advisory", "critical", "urgent", "zero-day", "breach"],
    },
    "stability": {
        "label": "Stability & bug fixes",
        "options": ["Improved stability"],
        "cues": ["crash", "bug", "unstable", "break", "broke", "broken", "glitch",
                 "freeze", "error", "fail", "data loss", "compatib"],
        "doc_terms": ["fix", "fixed", "bug", "crash", "regression", "stability",
                      "stable", "hotfix", "patch", "freeze", "revert", "broken"],
    },
    "performance": {
        "label": "Performance",
        "options": ["Performances", "Performance"],
        "cues": ["performance", "slow", "speed", "faster", "lag", "battery",
                 "memory", "sluggish"],
        "doc_terms": ["performance", "speed", "faster", "slow", "latency",
                      "memory", "cpu", "battery", "optimiz", "regression"],
    },
    "features": {
        "label": "New features",
        "options": ["Features"],
        "cues": ["feature", "functionality", "new tool", "improvement"],
        "doc_terms": ["feature", "new", "added", "adds", "support", "introduc",
                      "improved", "redesign", "ui", "ux"],
    },
    "cost": {
        "label": "Update size & install time",
        "options": ["Size", "Smaller update size:", "Faster installation",
                    "Flexible scheduling"],
        "cues": ["size", "space", "storage", "download", "takes time", "long time",
                 "slow to install", "reboot", "restart", "inconvenient"],
        "doc_terms": ["size", "download", "mb", "gb", "install", "reboot",
                      "restart", "footprint", "incremental", "delta"],
    },
    "changelog": {
        "label": "Knowing what changed",
        "options": ["Change log", "Recommendation"],
        "cues": ["what's gonna change", "what changed", "not sure what", "change log",
                 "changelog", "release notes", "don't know what", "unclear"],
        "doc_terms": ["changelog", "release note", "what's new", "changes",
                      "documented", "notes", "announcement"],
    },
}

# Columns the options are voted in, and the columns people wrote prose in.
_OPTION_COLS = (
    "What motivates you to install software updates when they become available?",
    "What factors influence your decision to update or delay updating?",
    "What improvements would make you more likely to install updates promptly?",
)
_TEXT_COLS = (
    "What concerns or hesitations do you have about installing software updates?",
    "Have you ever experienced problems after updating software? If so, please describe.",
    "How important is automatic updating to you? Why?",
)


@lru_cache(maxsize=4)
def _rows(path: str = "") -> tuple:
    p = Path(path) if path else SURVEY_CSV
    with open(p, newline="", encoding="utf-8") as fh:
        return tuple(csv.DictReader(fh))


def respondents(path: str = "") -> int:
    return len(_rows(path))


@lru_cache(maxsize=4)
def priorities(path: str = "") -> tuple:
    """Each priority with the number of respondents who raised it, and a quote.

    A respondent counts once per priority however many ways they said it --
    ticking "Safety" and also writing about viruses is one person worried about
    security, not two.
    """
    rows = _rows(path)
    out = []
    for key, spec in PRIORITIES.items():
        wanted = {o.lower() for o in spec["options"]}
        n = 0
        quote = ""
        for r in rows:
            hit = False
            for col in _OPTION_COLS:
                picks = {p.strip().lower() for p in (r.get(col) or "").split(",")}
                if picks & wanted:
                    hit = True
            for col in _TEXT_COLS:
                txt = (r.get(col) or "").strip()
                if len(txt) > 12 and any(c in txt.lower() for c in spec["cues"]):
                    hit = True
                    # Longest verbatim wins: the point of showing one is that it
                    # says something a count cannot.
                    if len(txt) > len(quote):
                        quote = txt
            n += hit
        out.append({"key": key, "label": spec["label"], "respondents": n,
                    "share": round(n / max(len(rows), 1), 2), "quote": quote})
    return tuple(sorted(out, key=lambda p: -p["respondents"]))


def _doc_text(docs: Sequence[dict]) -> str:
    """Everything the user would read across a run's results, lowercased."""
    parts: List[str] = []
    for d in docs or []:
        for field in ("title", "detail", "notes", "product", "text",
                      "top_comment", "subreddit", "channel"):
            v = d.get(field)
            if isinstance(v, str) and v:
                parts.append(v)
        for field in ("security", "breaking", "tags"):
            v = d.get(field)
            if isinstance(v, list):
                parts.extend(str(x) for x in v)
    return re.sub(r"\s+", " ", " ".join(parts)).lower()


def alignment(docs: Sequence[dict], path: str = "") -> dict:
    """How much of what users said they care about these results speak to.

    The score is respondent-weighted, not an unweighted fraction of six
    buckets: a set of results that answers the two priorities 40+ people raised
    is more use than one that answers four nobody asked about.
    """
    text = _doc_text(docs)
    covered, missing = [], []
    hit_weight = total_weight = 0
    for p in priorities(path):
        w = p["respondents"]
        total_weight += w
        terms = [t for t in PRIORITIES[p["key"]]["doc_terms"] if t in text]
        if terms:
            hit_weight += w
            covered.append({**p, "matched": terms[:4]})
        else:
            missing.append(p)
    score = round(hit_weight / total_weight, 2) if total_weight else 0.0
    return {"score": score, "covered": covered, "missing": missing,
            "n": respondents(path)}


def _demo() -> None:
    ps = priorities()
    assert respondents() == 52, respondents()
    assert {p["key"] for p in ps} == set(PRIORITIES)
    # Every priority is raised by someone, and none by more than everyone.
    assert all(0 < p["respondents"] <= 52 for p in ps), ps
    assert ps[0]["respondents"] >= ps[-1]["respondents"]      # sorted desc

    sec_release = [{"title": "linux v7.2.0", "notes": "security fix for a critical CVE"}]
    a = alignment(sec_release)
    keys = {c["key"] for c in a["covered"]}
    assert "security" in keys and "stability" in keys, keys
    assert "cost" not in keys, keys
    assert 0 < a["score"] < 1, a["score"]
    assert alignment([])["score"] == 0.0
    # Weighted, not a flat fraction of buckets: two of six covered here.
    assert a["score"] != round(2 / 6, 2)
    print(f"ok — n={a['n']}, " + " · ".join(
        f"{p['label']} {p['respondents']}" for p in ps))


if __name__ == "__main__":
    _demo()
