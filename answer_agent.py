"""
Answer Presenter Agent — prose with bracketed evidence.
=======================================================
The pipeline's final answer has always been `EvaluatorAgent`'s assembled
template: headers, bullet lists, truncated note fragments. It is faithful but
it does not read as an answer, and (see eval_harness/FINDINGS.md) the template
rendering is itself a measured confound in the faithfulness scores.

This module adds the presentation step the demo was missing: one agent that
takes the documents the retrieval agents already returned and writes a short
human-readable paragraph, with every claim carrying its source in brackets.

It reuses the existing layers rather than adding a parallel stack:

  * `eval_harness.providers.make_client` — the same provider-agnostic LLM
    client the harness uses, so the presenter swaps models with no code change;
  * `eval_harness.generators.SYNTHESIS_INSTRUCTION` — the shared grounding
    instruction, extended here with a citation rule rather than rewritten.

`build_synthesis_prompt` in the harness is deliberately NOT modified: the
published answer-quality numbers were produced with that exact prompt, and
changing it would silently invalidate them.

No model reachable (the deployed Streamlit host has no Ollama and may hold no
API key) degrades to `deterministic_paragraph`, which composes the same prose
shape from the documents by rule. That path never invents a sentence the
documents do not support, so an offline demo is still grounded — just blunter.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional

import guardrail
import model_select
import vendor
from agent_rules import rules_block

__all__ = [
    "Evidence",
    "collect_evidence",
    "build_cited_prompt",
    "deterministic_paragraph",
    "present_answer",
    "CITATION_RULE",
]

CITATION_RULE = (
    "Write ONE flowing paragraph of plain English (3-6 sentences) that a "
    "developer could read aloud. After every factual claim, cite the source it "
    "came from in square brackets exactly as it is labelled below, e.g. "
    "[Release Notes - Linux v6.18.21, 2026-08-28]. Cite only from the list. "
    "Do not invent versions, dates or CVE numbers. If the sources do not "
    "answer the question, say so plainly in one sentence.\n"
    "The sources were retrieved for this question and each carries its own "
    "date and, where applicable, a SECURITY marker: a dated source inside the "
    "time frame IS an answer to a question about that time frame, so report it "
    "rather than saying nothing was found.\n"
    "Output the paragraph only — no preamble, no heading, no surrounding "
    "quotation marks, no closing advice about checking elsewhere."
)


@dataclass
class Evidence:
    """One retrieved item, in the shape the presenter cites it by."""

    label: str            # what appears inside the brackets
    kind: str             # release | community | cve
    title: str
    detail: str = ""
    url: str = ""
    date: str = ""
    security: bool = False
    sentiment: str = ""

    def line(self) -> str:
        """One source line for the prompt: the citation label, then the facts.

        The date and the SECURITY marker are repeated in the body because a
        small model reads the label as a name and skips over what is inside
        it -- llama3.1 answered "no critical Linux updates in the past 7 days"
        with three in-window SECURITY releases listed above it.
        """
        facts = []
        if self.date:
            facts.append(f"dated {self.date}")
        if self.security:
            facts.append("SECURITY")
        if self.sentiment:
            facts.append(self.sentiment.lower() + " sentiment")
        meta = f" ({', '.join(facts)})" if facts else ""
        body = f"{self.title}{meta}"
        if self.detail:
            body += f": {self.detail}"
        return f"- [{self.label}] {body}"


def _iso(value: str) -> str:
    """Normalise a feed date for display in a citation.

    `versionReleaseDate` arrives compact ("20260828") and `created_utc`
    arrives ISO; a citation that reads "Linux v6.13.0, 20260828" is harder to
    check against the source than one that reads "2026-08-28".
    """
    from temporal import _parse_date
    d = _parse_date(str(value or ""))
    return d.isoformat() if d else str(value or "")[:10]


def _clean(text: str, limit: int = 220) -> str:
    """Collapse the whitespace release notes arrive with, then clip on a word."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def collect_evidence(results: Dict, per_kind: int = 4) -> List[Evidence]:
    """Flatten a pipeline result dict into citable evidence.

    Accepts the structure `run_pipeline` already returns (`releases`,
    `community`, `cve` lists), so nothing upstream has to change.
    """
    ev: List[Evidence] = []

    for r in (results.get("releases") or [])[:per_kind]:
        # An advisory row is named by its CVE id, not by its versionNumber:
        # that field holds the *affected* version, and citing
        # "Linux v25.642087.0" as a release invites the reader to believe a
        # version by that name shipped. `vendor.describe_record` decides which
        # naming a row gets, from the row itself.
        advisory = vendor.classify_record(r) == "advisory"
        name = vendor.describe_record(r) or (r.get("product", "") or "release")
        date = _iso(r.get("date"))
        prefix = "Security Advisory" if advisory else "Release Notes"
        label = f"{prefix} - {name}" + (f", {date}" if date else "")
        ev.append(Evidence(
            label=label, kind="advisory" if advisory else "release", title=name,
            detail=_clean(r.get("notes", "")), url=r.get("url", ""), date=date,
            security=advisory or "SECURITY" in (r.get("security") or []),
        ))

    for c in (results.get("cve") or [])[:per_kind]:
        # These come from /api/reddit/query/cve -- Reddit posts, not advisory
        # records. Labelling them "CVE Feed" told the reader a security feed
        # had reported them, which is a claim the row cannot support: the
        # endpoint returns unfiltered community posts. They are cited as what
        # they are, and counted apart from real advisories.
        date = _iso(c.get("date"))
        sub = c.get("subreddit", "")
        label = "Security Discussion" + (f" - r/{sub}" if sub else "") + (f", {date}" if date else "")
        ev.append(Evidence(
            label=label, kind="cve", title=_clean(c.get("title", ""), 160),
            url=c.get("url", ""), date=date, security=True,
        ))

    for p in (results.get("community") or [])[:per_kind]:
        date = _iso(p.get("date"))
        sub = p.get("subreddit", "")
        label = "Community" + (f" - r/{sub}" if sub else "") + (f", {date}" if date else "")
        ev.append(Evidence(
            label=label, kind="community", title=_clean(p.get("title", ""), 160),
            url=p.get("url", ""), date=date, sentiment=p.get("sentiment", ""),
        ))

    return ev


def build_cited_prompt(query: str, evidence: List[Evidence],
                       window_note: str = "") -> str:
    """The presenter's prompt: shared grounding instruction + citation rule."""
    try:
        from eval_harness.generators import SYNTHESIS_INSTRUCTION as base
    except Exception:  # harness not importable (bare demo deploy)
        base = ("You are a software-update assistant. Answer the question "
                "using ONLY the sources below.")
    ctx = "\n".join(e.line() for e in evidence) or "No documents retrieved."
    dated = f"\n\nTime frame asked about: {window_note}" if window_note else ""
    return (f"{rules_block()}{base}\n{CITATION_RULE}\n\nQuestion: {query}{dated}\n\n"
            f"Sources:\n{ctx}\n\nAnswer:")


_PREAMBLE = re.compile(
    r"^\s*(?:here (?:is|'s)[^\n:]*:|answer\s*:|paragraph\s*:)\s*", re.I)


def _strip_preamble(text: str) -> str:
    """Drop the meta line and wrapping quotes small models like to add."""
    out = text.strip()
    # A model that announces the paragraph usually puts it in the block below.
    parts = [p.strip() for p in out.split("\n\n") if p.strip()]
    parts = [p for p in parts if not _PREAMBLE.fullmatch(p + " ")] or parts
    if len(parts) > 1:
        keep = [p for p in parts if not _PREAMBLE.match(p)]
        # Prefer the longest cited block; a preface rarely carries a citation.
        cited = [p for p in keep if "[" in p]
        out = max(cited or keep, key=len)
    else:
        out = parts[0] if parts else out
    out = _PREAMBLE.sub("", out).strip()
    return out.strip('"“”\'').strip()


# ── Offline path ─────────────────────────────────────────────────────────

def _join(items: List[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def deterministic_paragraph(query: str, evidence: List[Evidence],
                            window_note: str = "") -> str:
    """Rule-composed prose with the same bracketed citations, no model needed."""
    if not evidence:
        return ("Nothing in the release feeds, the CVE feed or the community "
                "feed matched this question, so there is no grounded answer to "
                "give — try naming a specific product or version.")

    rel = [e for e in evidence if e.kind == "release"]
    sec = [e for e in rel if e.security]
    adv = [e for e in evidence if e.kind == "advisory"]
    cve = [e for e in evidence if e.kind == "cve"]
    com = [e for e in evidence if e.kind == "community"]

    scope = f" for {window_note}" if window_note else ""
    parts: List[str] = []

    if sec:
        head = _join([f"{e.title} [{e.label}]" for e in sec[:3]])
        parts.append(
            f"{len(sec)} of the {len(rel)} releases matching this question"
            f"{scope} are classified as security fixes: {head}.")
        lead = sec[0]
        if lead.detail:
            parts.append(f"The most relevant of them reports “{_clean(lead.detail, 160)}” "
                         f"[{lead.label}].")
    elif rel:
        head = _join([f"{e.title} [{e.label}]" for e in rel[:3]])
        parts.append(f"The release feed returned {len(rel)} matching "
                     f"release(s){scope}: {head}.")
        if rel[0].detail:
            parts.append(f"The top result notes “{_clean(rel[0].detail, 160)}” "
                         f"[{rel[0].label}].")
    else:
        parts.append(f"No release notes matched this question{scope}.")

    if adv:
        parts.append(f"On the security side, {len(adv)} advisory record(s) "
                     f"apply, led by “{adv[0].title}” [{adv[0].label}].")

    if cve:
        # Deliberately a separate sentence and a separate count: a Reddit
        # thread and an NVD record are not the same kind of evidence, and one
        # number covering both overstates how much security reporting there is.
        parts.append(f"Community security discussion adds {len(cve)} post(s), "
                     f"including “{cve[0].title}” [{cve[0].label}].")

    if com:
        neg = [e for e in com if e.sentiment == "Negative"]
        mood = ("with negative reaction reported" if neg
                else "with no negative reaction reported")
        parts.append(f"Community coverage adds {len(com)} post(s) {mood}, "
                     f"including “{com[0].title}” [{com[0].label}].")

    parts.append("Every statement above is drawn from the bracketed sources; "
                 "nothing outside them was used.")
    return " ".join(parts)


# ── Entry point ──────────────────────────────────────────────────────────

@dataclass
class PresentedAnswer:
    text: str
    mode: str                       # "llm" or "rule-based"
    model: str = ""
    note: str = ""
    evidence: List[Evidence] = field(default_factory=list)


@lru_cache(maxsize=1)
def _selected_spec() -> Optional[str]:
    """Ask model_select what is reachable, once per process.

    The probe is a network round trip and it is paid on the host that has no
    model at all -- the one where it always fails -- so it is cached rather
    than repeated per question. A restart is what picks up a model that came
    up later, which is the same thing the env vars already require.
    """
    return model_select.select("present").spec


def _resolve_spec(explicit: Optional[str]) -> Optional[str]:
    """Which model to present with: caller > env > whatever is reachable."""
    if explicit:
        return explicit
    return (os.getenv("PRESENTER_MODEL") or os.getenv("MARAG_LLM")
            or _selected_spec())


def present_answer(query: str, results: Dict, model_spec: Optional[str] = None,
                   window_note: str = "", per_kind: int = 4) -> PresentedAnswer:
    """Turn a pipeline result into a readable, cited paragraph.

    Tries the LLM presenter first; falls back to the rule-based paragraph on
    an unavailable or failing model, and says which path produced the text so
    a demo never passes rule-based prose off as model output.
    """
    evidence = collect_evidence(results, per_kind=per_kind)
    spec = _resolve_spec(model_spec)

    if spec:
        try:
            from eval_harness.providers import make_client, LLMError
            client = make_client(spec)
            if client.available():
                text = client.generate(
                    build_cited_prompt(query, evidence, window_note),
                    temperature=0.0, max_tokens=400)
                text = _strip_preamble(text)
                if text:
                    # The model was given these sources and nothing else, so
                    # anything it states outside them is invented. Failing the
                    # check falls back to the rule-composed paragraph -- built
                    # from the same evidence by code, so it cannot fail -- and
                    # not to a refusal, which would throw away a real answer
                    # over one bad span.
                    verdict = guardrail.check(text, evidence)
                    if verdict.ok:
                        return PresentedAnswer(text, "llm", client.spec,
                                               evidence=evidence)
                    note = ("model output failed the guardrail — "
                            + "; ".join(str(v) for v in verdict.violations))
                else:
                    note = "model returned an empty answer"
            else:
                note = f"{client.spec} not reachable"
        except Exception as e:  # noqa: BLE001 — any import/transport failure
            note = f"presenter model unavailable ({e})"
    else:
        note = "no presenter model configured or reachable"

    return PresentedAnswer(
        deterministic_paragraph(query, evidence, window_note),
        "rule-based", note=note, evidence=evidence)
