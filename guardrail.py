"""
Guardrail: refuse an answer the evidence does not carry.

The presenter (answer_agent) hands a small model a list of cited sources and
asks for a paragraph. Small models invent around that list -- a version number
one minor off, a date that is not in any feed row, a citation label that was
never in the prompt. Those are the failures that make a demo unquotable, and
they are all checkable against the same evidence the prompt was built from.

Rule-based on purpose, for the same reason as yesno: the deployed host may have
no model at all, and a checker that needs a model to run is a checker that is
off exactly when the fallback prose is being shown.

Every violation names the offending span, so a rejection can be read back to
the source line that should have supported it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

from eval_harness.benchmarks import extract_dates, extract_versions, is_abstention

__all__ = ["Violation", "Verdict", "check", "guard", "REFUSAL"]

# Worded so that it trips is_abstention() itself: whatever the guardrail
# substitutes has to pass its own check, or the refusal is a new violation.
REFUSAL = ("I cannot determine that from the sources retrieved, so I am not "
           "going to state it.")

# Labels are long here on purpose -- "Release Notes - Django v5.2.1, 2026-08-20"
# is the whole citation, so the span has to hold one.
_CITE_RE = re.compile(r"\[([^\[\]\n]{1,120})\]")
# Dates are checked separately; cut them out before the version pass so a
# dotted date form cannot arrive as a version.
_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# A version claim in prose is a product name followed by a number: "Fedora 45",
# "Chrome v155". A bare number on its own is a count, a year or a day, which is
# why the dotted-only pass above ignores it -- but "Fedora 45" against a source
# that only knows Fedora 44 is exactly the invention this module exists to
# catch, so the pair is checked even when the number is bare.
_NAMED_VERSION_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9+#.-]{1,30})\s+v?(\d+(?:\.\d+)*)\b")


@dataclass
class Violation:
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass
class Verdict:
    ok: bool
    violations: List[Violation] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def _lines(evidence: Sequence) -> Tuple[str, set]:
    """Flatten evidence to (searchable text, citation labels).

    Accepts answer_agent.Evidence or the plain dicts the eval harness stores.
    """
    parts, labels = [], set()
    for e in evidence or ():
        if hasattr(e, "line"):
            parts.append(e.line())
            labels.add(str(getattr(e, "label", "")).strip())
        elif isinstance(e, dict):
            parts.append(" ".join(str(v) for v in e.values()))
            labels.add(str(e.get("label", "")).strip())
        else:
            parts.append(str(e))
    labels.discard("")
    return "\n".join(parts), labels


def _named_versions(text: str) -> List[Tuple[str, str]]:
    """(product, version) pairs as prose states them: "Fedora 45" -> ("fedora", "45")."""
    return [(m.group(1).lower(), m.group(2))
            for m in _NAMED_VERSION_RE.finditer(text or "")]


def check(answer: str, evidence: Sequence) -> Verdict:
    """Check a presented answer against the evidence it was built from."""
    text = (answer or "").strip()
    haystack, labels = _lines(evidence)
    cited = {c.strip() for c in _CITE_RE.findall(text)}
    bad: List[Violation] = []

    if not text:
        return Verdict(False, [Violation("empty", "no answer text")])

    # `strong_only`: the weak markers are "unknown", "not found" and "no
    # information", and a release record in this domain carries a literal
    # UNKNOWN security type. A model that echoes it used to abstain by
    # accident and skip every check below with it.
    abstained = is_abstention(text, strong_only=True)

    if not labels:
        # Nothing retrieved: the only admissible answer is one that says so.
        if not abstained:
            bad.append(Violation("no_evidence", "answer asserts facts with an empty pool"))
        return Verdict(not bad, bad)

    for label in sorted(cited - labels):
        bad.append(Violation("unknown_citation", f"[{label}] was not in the prompt"))
    # Declining excuses the *citation* requirement and nothing else: an answer
    # that says it cannot determine one thing and then states a version, a date
    # or a label anyway is asserting, and the assertion is what gets checked.
    if not cited and not abstained:
        bad.append(Violation("uncited", f"{len(labels)} sources given, none cited"))

    _known: dict = {}
    for product, v in _named_versions(_ISO_RE.sub(" ", haystack)):
        _known.setdefault(product, set()).add(v)

    known_versions = set(extract_versions(_ISO_RE.sub(" ", haystack), multipart_only=True))
    for v in extract_versions(_ISO_RE.sub(" ", text), multipart_only=True):
        if v not in known_versions:
            bad.append(Violation("unsupported_version", f"{v!r} is in no source"))

    for product, claimed in _named_versions(text):
        if "." in claimed:
            continue                      # already checked exactly, above
        known = _known.get(product)
        # Only products the sources themselves version are checked. "returned 5
        # release(s)" and "Sep 8" match the same shape, and "returned" and "Sep"
        # are not products anyone shipped, so they are not version claims.
        if known and not any(k == claimed or k.startswith(claimed + ".")
                             for k in known):
            bad.append(Violation(
                "unsupported_version",
                f"{product} {claimed} is in no source (sources have "
                f"{', '.join(sorted(known))})"))

    known_dates = set(extract_dates(haystack))
    for d in extract_dates(text):
        if d not in known_dates:
            bad.append(Violation("unsupported_date", f"{d} is in no source"))

    return Verdict(not bad, bad)


def guard(answer: str, evidence: Sequence) -> Tuple[str, Verdict]:
    """The answer if it passes, the refusal if it does not, plus the verdict."""
    v = check(answer, evidence)
    return (answer if v.ok else REFUSAL), v


def _demo() -> None:
    from answer_agent import Evidence

    ev = [
        Evidence(label="R1", kind="release", title="Fedora 44 released",
                 date="2026-09-01", security=True, detail="kernel 6.17.2"),
        Evidence(label="C1", kind="community", title="Anyone else losing grub?",
                 date="2026-09-02"),
        Evidence(label="R2", kind="release", title="Chrome v155.0.8047 released",
                 date="2026-09-08"),
    ]

    good = "Fedora 44 shipped on 2026-09-01 with kernel 6.17.2 [R1], and users report grub loss [C1]."
    assert check(good, ev).ok, check(good, ev).violations

    v = check("Fedora 45.0.1 landed on 2026-09-05 [R9].", ev)
    codes = sorted(x.code for x in v.violations)
    assert codes == ["unknown_citation", "unsupported_date", "unsupported_version"], codes

    # A bare integer is a count, a year or a major number -- not a version to
    # check. Reading it as one refused answers that were quoting the sources:
    # "Chrome 155" against a v155.0.8047 row, and every "fixed 3 bugs".
    # ponytail: this also stops catching an invented bare major ("Fedora 45");
    # dotted forms are what the domain decides on, per extract_versions.
    counts = "The feed returned 5 release(s); kernel 6.17.2 is in 2 of them [R1]."
    assert check(counts, ev).ok, check(counts, ev).violations

    # The prefix rule: a bare major is checked when the sources version that
    # product, and a source's 155.0.8047 is what makes "Chrome 155" true.
    assert check("Chrome 155 shipped [R2].", ev).ok, check("Chrome 155 shipped [R2].", ev).violations
    assert check("Fedora 44 shipped [R1].", ev).ok            # exact, bare in the source
    v = check("Fedora 45 is out [R1].", ev)
    assert [x.code for x in v.violations] == ["unsupported_version"], v.violations
    assert "sources have 44" in v.violations[0].detail, v.violations[0].detail
    # Products the sources do not version are not version claims at all.
    assert check("Debian 13 is unaffected [R1].", ev).ok

    # One weak marker used to skip every check below it. UNKNOWN is a literal
    # security-type value in this domain's release rows, so a model echoing it
    # was granted a free pass to invent a version, a date and a label.
    sneaky = "Security type is unknown, but Fedora 45.0.1 shipped on 2026-09-05 [R9]."
    codes = sorted(x.code for x in check(sneaky, ev).violations)
    assert codes == ["unknown_citation", "unsupported_date", "unsupported_version"], codes

    # Declining still does not need a citation.
    assert check("I cannot determine that from these sources.", ev).ok

    assert check("Fedora 44 is out.", ev).violations[0].code == "uncited"
    assert check("Fedora 44 shipped [R1].", []).violations[0].code == "no_evidence"
    assert check("I don't know.", []).ok                 # abstention with no pool
    assert check("Not enough information in the sources.", ev).ok

    text, v = guard("Fedora 45.0.1 is out [R1].", ev)
    assert text == REFUSAL and not v
    assert check(REFUSAL, ev).ok                         # the refusal passes itself
    print("ok — guardrail:", "; ".join(str(x) for x in check("Fedora 45.0.1 landed on 2026-09-05 [R9].", ev).violations))


if __name__ == "__main__":
    _demo()
