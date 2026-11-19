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
import os
import re
import sys
import urllib.request
from typing import Callable, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from ask_external_models import load_dotenv  # noqa: E402
from decide import COLLAPSE, decide  # noqa: E402
from eval_harness.providers import LLMError, make_client  # noqa: E402

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


# --- systems: each is (row) -> label | None ---------------------------------

PROMPT = """You are deciding whether someone should update software.

Question: {query}
{context}{evidence}
Answer with your reasoning, then a final line that is exactly one of:
VERDICT: act                    (the evidence supports doing something now: install, stay, apply a fix, roll back)
VERDICT: hold                   (the evidence speaks to the question but says wait: conflicting, outdated, or "not yet")
VERDICT: insufficient_evidence  (nothing you know or were given answers this question)
"""


def prompt_for(row: dict, pooled: bool) -> str:
    """Closed: what a user would type. Pooled: plus the same evidence our system sees."""
    context = f"Context: {row['context']}\n" if row.get("context") else ""
    evidence = ""
    if pooled:
        docs = "\n".join(f"- [{d.get('doc_id')}] {d.get('title', '')}: {d.get('text', '')}"
                          for d in row.get("evidence", []))
        evidence = f"Evidence (use only this):\n{docs or '(none)'}\n"
    return PROMPT.format(query=row["query"], context=context, evidence=evidence)


def ours(row: dict) -> Optional[str]:
    d = decide(row.get("evidence", []), row["query"], vendors=[row["vendor"]] if row.get("vendor") else [])
    return COLLAPSE[d.verdict]


def llm_system(spec: str, pooled: bool) -> Optional[Callable[[dict], Optional[str]]]:
    """None when the backend has no key / SDK, so the caller can report it skipped."""
    load_dotenv()
    client = make_client(spec)
    if not client.available():
        return None

    def ask(row: dict) -> Optional[str]:
        try:
            return parse_verdict(client.generate(prompt_for(row, pooled)))
        except LLMError:
            return None
    return ask


# Sheet ecosystem -> OSV ecosystem. Everything else is outside what a scanner sees.
OSV_ECOSYSTEMS = {"npm_node": "npm", "pip_python": "PyPI", "cargo_rust": "crates.io",
                  "debian": "Debian", "ubuntu": "Ubuntu", "android": "Android",
                  "linux_kernel": "Linux"}
_VERSION = re.compile(r"\b\d+\.\d+(?:\.\d+)?\b")


def _osv_query(package: str, ecosystem: str, version: Optional[str]) -> list:
    body = {"package": {"name": package, "ecosystem": ecosystem}}
    if version:
        body["version"] = version
    req = urllib.request.Request("https://api.osv.dev/v1/query", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("vulns", [])


def osv(row: dict) -> Optional[str]:
    """hold if OSV lists a vuln, act if none, None if unmapped or the lookup failed.
    A failed scan must never read as a green light."""
    eco = OSV_ECOSYSTEMS.get(row.get("ecosystem", ""))
    if not eco or not row.get("vendor"):
        return None
    # ponytail: vendor name stands in for the package name; a real scanner reads a manifest.
    m = _VERSION.search(row["query"])
    try:
        vulns = _osv_query(row["vendor"].lower(), eco, m.group(0) if m else None)
    except (OSError, ValueError):
        return None
    return "hold" if vulns else "act"
