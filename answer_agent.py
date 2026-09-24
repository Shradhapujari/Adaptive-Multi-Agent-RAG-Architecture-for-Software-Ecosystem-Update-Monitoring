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

`build_synthesis_prompt` in the harness carries the agent rules only when
`MARAG_RULES=on` asks for them: the published answer-quality numbers were
produced without any, so moving that prompt by default would silently
invalidate them.

No model reachable (the deployed Streamlit host has no Ollama and may hold no
API key) degrades to `deterministic_paragraph`, which composes the same prose
shape from the documents by rule. That path never invents a sentence the
documents do not support, so an offline demo is still grounded — just blunter.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
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
    "_one_sentence",
    "present_answer",
    "CITATION_RULE",
    "TOP_COMMENT_FLOOR",
]

# How many upvotes a thread's top comment needs before the answer is written
# off it. Reddit gives every comment 1 point the moment it is posted -- the
# commenter's own -- so a 1-point "top comment" is the *only* comment, or the
# one nobody voted on either way, and it is not a community answer. 2 means at
# least one other reader agreed with it.
#
# Measured against the case that prompted this: r/Fedora "fedora update", whose
# top comment is the single word "What?" at 1 point, led the presenter to state
# that the update deleted people's kernels -- while the stance tally under it
# read No (4 users). Below the floor the comment is still shown in the details
# panel, with its score; it just does not get to be the answer.
TOP_COMMENT_FLOOR = 2

def cite_tag(i: int) -> str:
    """The short handle source `i` is cited by in the prompt."""
    return f"S{i + 1}"


# A citation the model wrote: one tag, several, or a range. llama3.1 emits all
# three -- "[S1]", "[S2, S3, S4]", "[S1-S3]" -- and a form that does not expand
# reaches the guardrail as an unknown citation, which throws the answer away.
_TAG_BLOCK_RE = re.compile(
    r"\[\s*(S\s*\d{1,3}(?:\s*(?:,|;|/|&|and|-|–|—|to)\s*S?\s*\d{1,3})*)\s*\]", re.I)
_TAG_ITEM_RE = re.compile(
    r"S\s*(\d{1,3})\s*(?:(?:-|–|—|to)\s*S?\s*(\d{1,3}))?", re.I)


def _tag_indices(inner: str):
    """The 1-based source numbers a bracket block names, ranges expanded."""
    out = []
    for m in _TAG_ITEM_RE.finditer(inner):
        a = int(m.group(1))
        b = m.group(2)
        out.extend(range(a, int(b) + 1) if b else [a])
    return out


def expand_tags(text: str, evidence) -> str:
    """Put the full label back wherever the model cited a short tag.

    The model is asked for [S1] because it can copy that reliably; every reader
    downstream -- the guardrail, the UI, the stored run -- wants the label it
    stands for. A block naming a source that does not exist is left exactly as
    written, so it is caught as an unknown citation rather than silently
    dropped.
    """
    ev = list(evidence or ())

    def sub(m):
        idx = _tag_indices(m.group(1))
        if not idx or any(not (1 <= i <= len(ev)) for i in idx):
            return m.group(0)
        seen, labels = set(), []
        for i in idx:
            if i not in seen:
                seen.add(i)
                labels.append(f"[{ev[i - 1].label}]")
        return " ".join(labels)
    return _TAG_BLOCK_RE.sub(sub, text or "")


CITATION_RULE = (
    "Answer in ONE sentence of plain English \u2014 no more. If a [Top comment \u2026] "
    "source is listed, it is the Reddit community's own highest-upvoted answer "
    "to this question: base the sentence on what it says and cite it. "
    "Otherwise use the highest-upvoted community post, or the release notes "
    "when no community answer is listed. Cite the source it came from by "
    "its short tag in square brackets, e.g. [S1] or [S3] \u2014 copy the tag "
    "exactly and put nothing else inside the brackets. Cite only tags that "
    "appear in the list. "
    "Do not invent versions, dates or CVE numbers. If the sources do not "
    "answer the question, say so plainly in that one sentence.\n"
    "The sources were retrieved for this question and each carries its own "
    "date and, where applicable, a SECURITY marker: a dated source inside the "
    "time frame IS an answer to a question about that time frame, so report it "
    "rather than saying nothing was found.\n"
    "Output the one sentence only \u2014 no preamble, no heading, no surrounding "
    "quotation marks, no closing advice about checking elsewhere."
)


# A sentence ends where punctuation is followed by a capitalised new start;
# "v6.18.21" and "2026-08-28]" do not qualify, so a cited version or date in
# mid-sentence is not mistaken for the end of one.
#
# "[" is deliberately NOT a sentence opener. llama3.1 puts the citation after
# the closing period -- "...after the latest Windows 11 update. [Top comment -
# r/sysadmin, 1 upvote]" -- and cutting there threw the only citation away, so
# the guardrail rejected the answer as uncited and the rule-based paragraph
# replaced a perfectly good model sentence.
_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[\"\u201c\'(]?[A-Z])")


def _one_sentence(text: str) -> str:
    """The first sentence, citations intact. The rule says one; models drift."""
    return _SENT_END.split((text or "").strip(), 1)[0].strip()


@dataclass
class Evidence:
    """One retrieved item, in the shape the presenter cites it by."""

    label: str            # what appears inside the brackets
    kind: str             # answer | release | advisory | community | cve
    title: str
    detail: str = ""
    url: str = ""
    date: str = ""
    security: bool = False
    sentiment: str = ""

    def line(self, tag: str = "") -> str:
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
            # Not "positive sentiment": the app's community agent reads
            # /api/reddit/query/positive and thresholds that feed's own
            # positiveScore, so this is the source's label for the post, not an
            # analysis of it. Titles like "Lots of problems since updating"
            # arrive marked Positive.
            facts.append(f"{self.sentiment.lower()} per the source feed")
        meta = f" ({', '.join(facts)})" if facts else ""
        body = f"{self.title}{meta}"
        if self.detail:
            body += f": {self.detail}"
        if tag:
            # Cited by a short tag, named by the full label. Asking an 8B model
            # to reproduce "Release Notes - windows v10.0.28000, 2026-09-08"
            # character for character is where the citations were being lost;
            # `expand_tags` puts the label back before anything sees the answer.
            return f"- [{tag}] {self.label} — {body}"
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

    # The thread's highest-upvoted comment is the community's own answer to the
    # question, chosen by the people who read it. It is cited first so the
    # presenter leads with it rather than with a release row -- but only once
    # somebody other than its author has voted for it (`TOP_COMMENT_FLOOR`).
    tc = results.get("top_comment") or {}
    thread = results.get("thread") or {}
    votes = int(tc.get("score") or 0)
    if (tc.get("body") or "").strip() and votes >= TOP_COMMENT_FLOOR:
        sub = thread.get("subreddit", "")
        ev.append(Evidence(
            # "1 upvotes" is what a model silently corrects to "1 upvote",
            # and the guardrail matches the label verbatim -- so the answer
            # came back uncited over a plural.
            label=("Top comment" + (f" - r/{sub}" if sub else "")
                   + f", {votes} upvote" + ("" if votes == 1 else "s")),
            kind="answer",
            title=_clean(thread.get("title", ""), 120) or "Reddit thread",
            detail=_clean(tc.get("body", ""), 400),
            url=thread.get("url", ""), date=_iso(thread.get("created_utc", "")),
        ))

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

    # Upvotes are the community's ranking of its own posts; the feed's order
    # is not. Highest first, so `per_kind` keeps the posts people agreed with.
    community = sorted(results.get("community") or [],
                       key=lambda p: int(p.get("score") or 0), reverse=True)
    for p in community[:per_kind]:
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
    ctx = "\n".join(e.line(cite_tag(i)) for i, e in enumerate(evidence)) \
        or "No documents retrieved."
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

    top = next((e for e in evidence if e.kind == "answer"), None)
    if top:
        return (f"The top-voted Reddit answer to this question says "
                f"\u201c{_clean(top.detail, 300)}\u201d [{top.label}].")

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
        # Nothing on the empty branch: the app fetches the positive feed, so
        # "with no negative reaction reported" was a claim about the endpoint
        # dressed up as a finding about the community.
        mood = " with negative reaction reported" if neg else ""
        parts.append(f"Community coverage adds {len(com)} post(s){mood}, "
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


# Worded around "no matching vendor", which is already a strong abstention
# marker: what is substituted has to read as a declined answer, not a claim.
VENDOR_ABSTENTION = (
    "No matching vendor for {terms} in the product catalog. Rather than answer "
    "from sources that are about something else, I am declining: check the "
    "spelling, or name the vendor alongside the product."
)


# "Blorptastic 9", "Blorptastic v9.2" — a capitalised word carrying a version
# is the evidence that the word names a product. Capitalisation alone is not:
# see the docstring below.
_VERSIONED = r"\b{}\s+v?\d"


def unresolved_products(query: str, results: Dict) -> List[str]:
    """Product-shaped words in `query` that the vendor catalog does not know.

    Four conditions, and all four are needed to avoid declining questions
    that are perfectly answerable:

    * the grounding step ran and resolved no vendor at all — without it there
      is nothing to say the question was about a product;
    * the catalog in use is the real one, not the offline fallback;
    * the leftover word is not one of the products `fetch_union` knows by
      name, because a known product the catalog missed is a catalog problem,
      not an unresolvable vendor;
    * the word carries a version number.

    That last one is what keeps this from declining ordinary questions.
    `product_terms` is a *fetch* heuristic: its fallback rule takes any
    capitalised non-initial word as a product name, which is right when the
    cost of being wrong is one extra search phrasing. Refusing to answer
    inverts that cost, and the rule is wrong often enough to matter —
    "Did anything break after the Tuesday patch?" yielded "Tuesday",
    "What broke in September?" yielded "September", and both were declined
    outright. Weekdays, months and ordinary proper nouns do not appear with a
    version number after them; unrecognised products, which is the case this
    gate exists for, almost always do.

    So "Is Blorptastic 9 out?" still declines and "Is Blorptastic out?" no
    longer does. That is the intended direction: answering a question about an
    unknown product from whatever the sources returned is a smaller failure
    than refusing a question the system can answer.

    A question that names no product — "what are the 3 latest updates?" —
    yields nothing here either. Naming nothing and naming something
    unrecognisable are different failures; only the second declines.
    """
    g = results.get("grounding")
    if g is None or getattr(g, "vendors", None):
        return []
    if not vendor.catalog_is_full():
        return []
    from fetch_union import _KNOWN_PRODUCTS, product_terms
    return [t for t in product_terms(query)
            if t.lower() not in _KNOWN_PRODUCTS
            and re.search(_VERSIONED.format(re.escape(t)), query, re.I)]


def present_answer(query: str, results: Dict, model_spec: Optional[str] = None,
                   window_note: str = "", per_kind: int = 4) -> PresentedAnswer:
    """`_present`, with a vendor gate before it and a leak scan after it.

    The scan is here and not inside `_present` because it has to cover the
    rule-based fallback too. `check()` cannot do this job: a credential that
    was in a retrieved row is *supported by the sources*, which is exactly what
    check() is asking, so it passes — and the fallback paragraph is composed
    from those same rows by code, so falling back leaks just as readily.
    """
    unknown = unresolved_products(query, results)
    if unknown:
        terms = _join([f"\u201c{t}\u201d" for t in unknown])
        return PresentedAnswer(VENDOR_ABSTENTION.format(terms=terms),
                               "rule-based", note="vendor unresolved",
                               evidence=collect_evidence(results, per_kind=per_kind))

    out = _present(query, results, model_spec, window_note, per_kind)
    text, hits = guardrail.scrub(out.text)
    if not hits:
        return out
    note = "leak scan: " + ", ".join(hits)
    return replace(out, text=text,
                   note=f"{out.note}; {note}" if out.note else note)


def _present(query: str, results: Dict, model_spec: Optional[str] = None,
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
                    # 150 truncated long enumerations mid-citation: the
                    # unclosed "[" never parses as a citation, so a real answer
                    # came back "uncited" (stored run #50).
                    temperature=0.0, max_tokens=400)
                text = expand_tags(_one_sentence(_strip_preamble(text)), evidence)
                if text:
                    # The model was given these sources and nothing else, so
                    # anything it states outside them is invented. Failing the
                    # check falls back to the rule-composed paragraph -- built
                    # from the same evidence by code, so it cannot fail -- and
                    # not to a refusal, which would throw away a real answer
                    # over one bad span.
                    verdict = guardrail.check(text, evidence, query)
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
