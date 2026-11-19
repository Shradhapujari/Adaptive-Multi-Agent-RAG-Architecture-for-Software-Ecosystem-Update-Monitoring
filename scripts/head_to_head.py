"""Head-to-head: our verdict against competitors on one labelled decision sheet.

    python scripts/head_to_head.py data/decision_benchmark_200.jsonl

Gold is the verdict both annotators gave; rows they disagree on, or left
empty, have no gold and are skipped (and counted). Every system answers each
gold row with one label -- act / hold / insufficient_evidence -- or None when
its reply carried no clean label. The lead number is the false-green rate:
of the questions whose answer is "hold", the share a system said "act" on.
"""
from __future__ import annotations

import json
import re

LABELS = ("act", "hold", "insufficient_evidence")
_VERDICT = re.compile(r"^\s*verdict:\s*(act|hold|insufficient_evidence)\b",
                      re.IGNORECASE | re.MULTILINE)


def load_gold(path: str) -> list[dict]:
    """Rows both annotators labelled the same way, each with a `gold` key."""
    rows = []
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            v1 = (r.get("a1") or {}).get("verdict")
            v2 = (r.get("a2") or {}).get("verdict")
            if v1 and v1 == v2:
                rows.append(r | {"gold": v1})
    return rows


def parse_verdict(text: str) -> str | None:
    """The label on a `VERDICT:` line; the last one wins. None if there is none."""
    found = _VERDICT.findall(text or "")
    return found[-1].lower() if found else None


def score(gold: list[str], pred: list[str | None]) -> dict:
    n = len(gold)
    holds = [p for g, p in zip(gold, pred) if g == "hold"]
    return {
        "n": n,
        "accuracy": sum(g == p for g, p in zip(gold, pred)) / n if n else None,
        "n_hold": len(holds),
        "false_green": sum(p == "act" for p in holds) / len(holds) if holds else None,
        "abstain": sum(p == "insufficient_evidence" for p in pred) / n if n else None,
        "unparsed": sum(p is None for p in pred),
    }
