"""
decide: a verdict with evidence obligations, computed by rule from the pool.
=========================================================================

Fourteen findings say every arm retrieves the same documents (nDCG@3 0.30 on
every arm at n=500, 101 won / 103 lost at n=1000). Retrieval metrics cannot
separate architectures that fetch the same thing, so the output changes type:
not a paragraph over the top-k, but a *decision* about the update, each
decision carrying the rule-checkable evidence it needs before it may be made.

    verdict             obligation (every clause checked against the pool)
    ------------------  ------------------------------------------------------
    patch_urgently      an advisory-tier document (CISA KEV / CVE feed) about
                        the product, carrying a CVE id, matching the asked
                        version when one is asked
    hold                >= K community reports of a problem on the product /
                        asked version, and no vendor release newer than the
                        newest report that says it is fixed
    update_with_caveat  a release note for the product / asked version that
                        names a breaking change, deprecation or known issue --
                        or problem reports that a newer release says it fixed
    safe                a release note for the product / asked version, no
                        advisory, fewer than K problem reports, no caveat
    insufficient_evidence  none of the above holds within the pool -> abstain

Precedence is the table's order: an exploited CVE outranks a regression
thread, which outranks a changelog caveat, which outranks silence.

Rule-based and model-free on purpose, for the reason guardrail.py gives: the
check has to run when Ollama is down, and -- the Phase 2 bet -- if structure
does not help as plain Python over the pool we already retrieve, no
orchestration framework will make it help. A document's prose never reaches the
verdict; only fields extracted from it do (source class, CVE ids, version
tokens, dates, problem / fix / caveat markers), which is also what makes an
injected instruction inside a Reddit post irrelevant to the decision.

The five verdicts collapse onto the three the annotation sheet uses
(docs/decision_annotation_guide.md): patch_urgently, update_with_caveat and
safe are all `act`. The five-way split is kept because it names *which*
obligation fired, which is what a human gate (Phase 3) routes on.

    python decide.py                 # verdict distribution over the 200 sheet pools
    python decide.py --gold a1       # ... scored against one annotator's labels
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from eval_harness.benchmarks import extract_versions
from guardrail import normalize
import vendor as _vendor_rules

VERDICTS = ("patch_urgently", "hold", "update_with_caveat", "safe",
            "insufficient_evidence")
COLLAPSE = {"patch_urgently": "act", "update_with_caveat": "act", "safe": "act",
            "hold": "hold", "insufficient_evidence": "insufficient_evidence"}

# Source classes, by what a document can be evidence *of*. Mirrors TIER1/TIER2
# in multiagent_rag_v3 but split one level finer: an advisory and a release
# note are both tier 1 and carry different obligations.
ADVISORY = frozenset({"cisa_kev", "circl_cve", "nvd", "cve"})
RELEASE = frozenset({"vendor_releases", "releases", "llm_releases", "apple_rss"})
COMMUNITY = frozenset({"vendor_reddit", "reddit_live", "reddit_search",
                       "google_news", "news_feeds", "github", "local"})

# How many independent community reports make a regression a reason to wait.
# One popular wrong post is the failure mode docs/Roadmap names; two is the
# smallest number that is not one post.
K_REPORTS = 2

# An advisory filed more than this long before the newest document in the pool
# is about a release the product has long since moved past: a 2022 KEV entry
# ordered "patch now" for a 2026 Firefox question (2026-11-12). Measured on the
# 200-question sheet: 14 of the 37 KEV rows behind patch verdicts were over a
# year old, and dropping them moved 6 verdicts off patch_urgently, 5 of them
# regression posts. The pool's own newest date stands in for "now", so a frozen
# pool decides the same way on every replay.
STALE_ADVISORY_DAYS = 365

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)
_PROBLEM_RE = re.compile(
    r"\b(brok(e|en)|crash(es|ed|ing)?|bug|regression|not working|stopped working|"
    r"fail(s|ed|ing)?|stuck|bricked|freez(es|ing)|boot ?loop|won'?t (boot|start|open)|"
    r"issue|problem|unusable|drain|lost|missing|disappear(s|ed|ing)?)\b", re.I)
_FIX_RE = re.compile(r"\b(fix(es|ed)?|resolv(es|ed)|patch(es|ed)?|addresses|hotfix)\b", re.I)
_CAVEAT_RE = re.compile(
    r"\b(breaking change|breaking|deprecat(ed|es|ion)|removed|no longer support|"
    r"incompatib|known issue|requires? (manual|migration)|migration required)\b", re.I)
_DATE_RE = re.compile(r"\b(\d{4})-?(\d{2})-?(\d{2})\b")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9.+#-]{1,}")
_STOP = frozenset("the a an and or to of in on for is are was were be been with "
                  "after update updated updating upgrade upgraded version latest new "
                  "anyone else help why how does did do my i it this that".split())


@dataclass
class Decision:
    verdict: str
    evidence: List[str] = field(default_factory=list)     # doc_ids the rule used
    obligations: Dict[str, bool] = field(default_factory=dict)
    stop_reason: str = ""          # obligations_met | no_evidence | evidence_insufficient
    probes_wanted: List[str] = field(default_factory=list)  # source class a graph would fetch next
    confidence: float = 0.0
    rationale: str = ""

    @property
    def verdict3(self) -> str:
        return COLLAPSE[self.verdict]

    @classmethod
    def from_dict(cls, d: dict) -> "Decision":
        return cls(d["verdict"], list(d.get("evidence_doc_ids") or []), dict(d.get("obligations") or {}),
                   d.get("stop_reason", ""), list(d.get("probes_wanted") or []),
                   float(d.get("confidence") or 0.0), d.get("rationale", ""))

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "verdict3": self.verdict3,
                "evidence_doc_ids": list(self.evidence), "obligations": dict(self.obligations),
                "stop_reason": self.stop_reason, "probes_wanted": list(self.probes_wanted),
                "confidence": self.confidence, "rationale": self.rationale}


# ----------------------------------------------------------------- extraction

def _text(d: dict) -> str:
    # Normalized here because every extractor below reads through it: the
    # injection screen saw NFKC text, the rules used to see the raw bytes.
    return normalize(f"{d.get('title', '')} {d.get('text', '') or d.get('detail', '')}")


def _date(d: dict) -> Optional[str]:
    m = _DATE_RE.search(str(d.get("date") or ""))
    return "".join(m.groups()) if m else None


def _tokens(s: str) -> set:
    return {w for w in _WORD_RE.findall(s.lower()) if w not in _STOP and len(w) > 2}


def _vendor_tokens(vendors: Iterable[str]) -> set:
    out = set()
    for v in vendors:
        out |= {w for w in _WORD_RE.findall(str(v).lower()) if len(w) > 2}
        # The project's own name is the product's too: "In CPython 3.13 ..."
        # is a Python advisory (vendor_kb.json `nvd_keywords`).
        out |= {w for x in KB.get(str(v).lower(), {}).get("nvd_keywords", ())
                for w in _WORD_RE.findall(x.lower())}
    return out


# An advisory's subject is whatever stands before its first predicate. Both
# catalogues write product-first: CISA KEV descriptions are "<product>
# contains a <weakness>..." almost without exception, and NVD's are
# "<product> is a ...", "<product> before <version> allows ...", or "In the
# <product>, ..." -- which has no predicate here and so is left alone.
_PREDICATE = re.compile(
    r"\b(?:contains?|is|are|was|were|allows?|before|prior\s+to|suffers|fails?|"
    r"does\s+not|has\s+an?|have\s+an?)\b", re.I)

# "...was fixed in Firefox 157.0.1." The product named as the thing patched,
# which is how NVD files a weakness-first advisory (the weakness is the
# subject, the product only shows up in the fix clause). Capture stops at the
# first comma/period/semicolon, so a cross-vendor row -- "fixed in Metabase
# 1.2, also affects MySQL" -- keeps only "Metabase 1.2" and is still rejected.
_FIX_CLAUSE = re.compile(
    r"\b(?:fixed|patched|resolved|addressed|mitigated)\s+in\s+([^.,;]{0,40})", re.I)


_PLATFORM_PREP = re.compile(r"\b(?:on|for)\b", re.I)
# _owns also cuts at "by": "artifacts hosted by GitHub", "links supplied by
# the GitHub server" name the service the affected software talks to.
_OWNER_CUT = re.compile(r"\b(?:on|for|by)\b", re.I)

# A component built *for* the product, named after it: "MariaDB Connector/
# Node.js", "the foo Node.js driver", "a WordPress plugin". The product token
# is there, but another vendor owns the affected artifact. "Linux Foundation
# Magma" and "the Linux builds of hMailServer" are the same shape.
_COMPONENT_AFTER = re.compile(
    r"\s*(?:connectors?|drivers?|modules?|packages?|plugins?|extensions?|add-?ons?"
    r"|sdks?|bindings?|wrappers?|adapters?|foundation|(?:builds?|installers?)\s+of)\b", re.I)

# Hand-curated per-product exclusions (data/vendor_kb.json): names that appear
# in a product's advisory subjects without the product owning the advisory.
# Static on purpose -- a list a run could append to would make one question's
# verdict depend on the questions before it, which the paired tests forbid.
_KB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "vendor_kb.json")
try:
    with open(_KB_PATH, encoding="utf-8") as _f:
        KB: Dict[str, dict] = {k.lower(): v for k, v in json.load(_f)["products"].items()}
except (OSError, ValueError, KeyError):
    KB = {}

# Vendor names that advisories put first ("Cisco IOS XE ...", "Zoom Windows
# client ..."). Static for the same reason as KB.
try:
    with open(os.path.join(os.path.dirname(_KB_PATH), "known_vendors.json"), encoding="utf-8") as _f:
        _kv = json.load(_f)
        KNOWN_VENDORS = frozenset(_kv["kev"]) | frozenset(_kv["extra"])
except (OSError, ValueError, KeyError):
    KNOWN_VENDORS = frozenset()


def _word_at(name: str, text: str) -> Optional[int]:
    """Start of `name` as a whole word in `text`, or None."""
    m = re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", text)
    return m.start() if m else None


def _foreign_vendor_first(d: dict, vendors: Sequence[str]) -> bool:
    """True when an advisory's subject names another vendor before every asked
    product it names -- "Cisco IOS XE ..." for iOS, "Zoom Windows client ..."
    for Windows. Advisories name the owner right before its product, so the
    vendor nearest before the asked product is the artifact's owner.

    Only judged for products whose owner is on file (vendor_kb.json
    `kev_vendors`): without one, a vendor before the product may be its own
    ("Canonical Ubuntu"), so an asked product with no owner on file is never
    blocked. A product the subject does not name (owned through the fix
    clause) is not blocked either.

    ponytail: KNOWN_VENDORS is a static list (KEV vendors + a few by hand);
    a vendor missing from it passes. Upgrade path is NVD CPE vendor fields.
    """
    body = normalize(str(d.get("text") or d.get("detail") or "")).lower()
    m = _PREDICATE.search(body)
    if not m or m.start() == 0:
        return False
    head = _PLATFORM_PREP.split(body[:m.start()], maxsplit=1)[0]
    blocked = False
    for v in vendors:
        pos = min((p for t in _vendor_tokens([v]) if (p := _word_at(t, head)) is not None), default=None)
        if pos is None:
            continue
        owners = {o.lower() for o in KB.get(str(v).lower(), {}).get("kev_vendors", ())}
        if not owners:
            return False
        # The vendor nearest before the product owns it, not the first one
        # named: "Buffer overflow in WebRTC in Google Chrome" is Google's
        # ("webrtc" is a KEV vendor too), "Cisco IOS XE" is Cisco's. Taking
        # the first dropped two real Chrome WebRTC advisories (2026-11-19).
        near = max(((p, n) for n in KNOWN_VENDORS | owners
                    if (p := _word_at(n, head)) is not None and p < pos), default=None)
        if near is None or near[1] in owners:
            return False
        blocked = True
    return blocked


def _owns(segment: str, vtoks: set, exclude: Sequence[str] = ()) -> bool:
    """Does `segment` (an advisory subject or fix clause) name the product as
    the owner of the affected artifact?

    Three ways a product token shows up without owning it: as the platform
    after "on"/"for" (VeraCrypt on macOS), as the target of a component named
    after it (Connector/Node.js, "Node.js driver"), or next to a name the
    knowledge store lists for that product (iTerm2 on macOS)."""
    head = _OWNER_CUT.split(segment.lower(), maxsplit=1)[0]
    if any(x in head for x in exclude):
        return False
    for v in vtoks:
        # Whole word only: a name joined by "-", "_", "/" or a dotted suffix
        # is another product built on this one -- falcon-rust, util-linux,
        # install-artifact-from-github, github.com/octo-sts -- and the raw
        # substring test made all of them "affects rust/linux/github"
        # advisories in the 2026-11-21 demo sweep.
        for m in re.finditer(r"(?<![a-z0-9_./@-])" + re.escape(v)
                             + r"(?![a-z0-9_/@-]|\.[a-z0-9])", head):
            if head[:m.start()].endswith("/") or _COMPONENT_AFTER.match(head, m.end()):
                continue
            return True
    return False


def _subject_names_product(d: dict, vtoks: set, exclude: Sequence[str] = ()) -> bool:
    """Does the asked product appear in the *subject* of an advisory?

    A product name anywhere in an advisory is not evidence that the advisory
    is about that product: it is also how the product gets mentioned in a
    sentence about something else. /api/v/ makes this routine, because it
    files NVD records under whatever product string the query matched -- the
    same reason this codebase already distrusts their `versionNumber`.
    CVE-2026-79920 is stored with `product: "linux"`, `version: "2.2.16"` and
    the description "Ajenti is a Linux & BSD modular server admin panel",
    and "Any critical Linux kernel vulnerabilities?" was answered
    `patch_urgently`, cited to it.

    So for advisory-tier documents only, the product has to be in the clause
    before the first predicate. Measured over the 200-question sheet: four
    documents change class, and all four were citing another vendor's
    advisory -- a MySQL question citing Metabase and Progress MOVEit (the
    token "sql" appears in "SQL Injection"), an npm question citing TanStack,
    and a Linux question citing an Apple iOS advisory (the token "kernel"
    appears in "kernel privileges"). `patch_urgently` over the sheet goes
    from 25 to 22.

    Confined to advisories because that is where the convention holds and
    where the damage is worst -- `patch_urgently` outranks every other
    verdict. A community post opens with whatever its author typed, so the
    same test there would reject "Updates are broken after the upgrade".
    """
    body = str(d.get("text") or d.get("detail") or "").strip()
    if not body:
        return True
    m = _PREDICATE.search(body)
    if m and m.start() == 0:             # no readable subject; rule abstains
        return True
    # No predicate at all is usually a cut, not a subjectless advisory: the
    # app keeps 200 characters of /api/v/ notes, and "The MongoDB Shell
    # (mongosh) relies on Node.js as a third-party runtime ..." lost its
    # "prior to" there and counted for a Node.js question (2026-11-12). The
    # first sentence stands in for the subject -- when it names the product at
    # all; a bare "CVE-2026-1234" still abstains.
    # Never past the first sentence: "A ... flaw has been found in ... the
    # pulp_python package. ... a Python distribution that has a remote" put
    # "Python" in the subject because the first predicate was two sentences
    # on (sweep, 2026-11-26).
    subject = re.split(r"(?<=[.;])\s", body[:m.start()] if m else body, maxsplit=1)[0].lower()
    if not m and not any(v in subject for v in vtoks):
        return True
    # Within the subject, a name after "on"/"for" is the platform the product
    # runs on, not the product: "VeraCrypt 1.26.29 (FUSE-T build) on macOS
    # systems allows ..." is a VeraCrypt advisory. Observed 2026-10-15, when a
    # macOS question returned "Patch now: 10 advisory document(s)" citing
    # VeraCrypt and Open Computer Use -- both of which name macOS in their
    # subject honestly, as their platform. Cutting there also keeps "Firefox
    # for iOS ..." a Firefox advisory rather than an iOS one.
    #
    # ponytail: positional heuristic, no parsing. It mis-rejects a genuine
    # advisory written "Security Update for macOS contains ..." -- the product
    # after the preposition. Upgrade path is the row's own product field once
    # /api/v/ can be trusted to carry it (today it files NVD records under
    # whatever string the query matched, which is why this rule exists).
    if _owns(subject, vtoks, exclude):
        return True
    # Weakness-first fallback: a real advisory whose subject is the flaw still
    # names the product in its fix clause. This is what let "Is it safe to
    # update Firefox right now?" fall back to a green on the live feed after
    # the citable_kinds fix -- the NVD rows read "Mitigation bypass ... fixed
    # in Firefox 157.0.1", product after the predicate, so the subject test
    # above dropped 4 of 5 of them as not-about-Firefox.
    # Same platform-preposition guard as the subject: "fixed in Firefox for
    # iOS 157.1" is a Firefox advisory, so an iOS question must not match the
    # "iOS" after "for".
    return any(_owns(fm.group(1), vtoks, exclude) for fm in _FIX_CLAUSE.finditer(body))


def kev_owns(d: dict, vendors: Sequence[str], exclude: Sequence[str] = ()) -> bool:
    """Does a CISA KEV row's own vendorProject/product name an asked product?

    KEV states the affected vendor and product as fields, so this reads those
    rather than guessing from the description. The description cannot tell a
    homonym from the product -- VMware "SD-WAN Edge" read as Microsoft Edge,
    Cisco "IOS" as Apple iOS -- and it hid the rows it should have counted:
    Chrome's are filed as Google "Chromium V8", which never says "chrome".

    With an owner on file (vendor_kb.json `kev_vendors`), a row from any other
    vendorProject is not this product's; one from the owner counts when its
    product field names the product, or else when the description's subject
    does (Apple files many rows as "Multiple Products"). With no owner on file,
    the fields alone decide, with the platform after "for" cut off, so "Driver
    for Windows" stays Intel's.
    """
    vend = normalize(str(d.get("kev_vendor") or "")).lower().strip()
    prod = normalize(str(d.get("kev_product") or "")).lower()
    for v in vendors:
        vtoks = _vendor_tokens([v])
        kb = KB.get(str(v).lower(), {})
        owners = {o.lower() for o in kb.get("kev_vendors", ())}
        if owners:
            if vend not in owners:
                continue
            head = _PLATFORM_PREP.split(prod, maxsplit=1)[0]
            names = vtoks | {p.lower() for p in kb.get("kev_products", ())}
            if _tokens(head) & names or _subject_names_product(d, vtoks, exclude):
                return True
        # With no owner on file, every word of the name must be there: one
        # shared word is not the product. "vs code" matched Collabora's
        # "Built-in CODE Server" and "Code Aurora" on "code" alone and said
        # Patch now (sweep, 2026-11-23).
        elif set(_WORD_RE.findall(str(v).lower())) <= set(_WORD_RE.findall(
                _PLATFORM_PREP.split(f"{vend} {prod}", maxsplit=1)[0])):
            return True
    return False


# "Firefox for iOS" is the same vendor's different product: its advisories say
# nothing about the desktop build a bare "Firefox" question is asking about.
# `_owns` cuts the subject at "for", which makes it a Firefox advisory -- right
# for the vendor, wrong for the platform. CVE-2026-103418 ("Firefox for iOS
# directly interpolated the page's HTML language attribute ... fixed in
# Firefox for iOS 157.1") therefore counted against "Is it safe to update
# Firefox right now?". Only "<product> for <platform>" is read, never a
# platform word elsewhere in the text, so a desktop advisory that mentions
# another platform in passing is untouched.
_PLATFORM_ALIAS = {"iphone": "ios", "ipad": "ios", "mac": "macos"}
_PLATFORM_VARIANT = re.compile(
    r"\b(?:{products})\s+for\s+(ios|iphone|ipad|android|windows|macos|linux)\b")


def _platform_variant_mismatch(d: dict, vtoks: set, qtoks: set) -> bool:
    """True when the advisory is about "<asked product> for <platform>" and the
    question names no such platform."""
    body = str(d.get("text") or d.get("detail") or "").lower()
    if not vtoks or not body:
        return False
    rx = re.compile(_PLATFORM_VARIANT.pattern.replace(
        "{products}", "|".join(re.escape(v) for v in sorted(vtoks))))
    asked = {_PLATFORM_ALIAS.get(t, t) for t in vtoks | qtoks}
    return any(_PLATFORM_ALIAS.get(m.group(1), m.group(1)) not in asked
               for m in rx.finditer(body))


def _lacks_required_word(d: dict, vendors: Sequence[str]) -> bool:
    """True when the advisory names an asked product that is also an ordinary
    word, without the word that makes it that product (vendor_kb.json
    `name_requires`). "The VAPIX Edge storage API ..." and "AMD Versal AI Edge
    Series ..." named Edge, passed the subject rule, and were cited in an Edge
    answer (live, 2026-11-19). Judged per product the advisory names, so a
    Chrome advisory is not held to Edge's requirement in an Edge-and-Chrome
    question."""
    body = _text(d).lower()
    named = [str(v).lower() for v in vendors if _word_at(str(v).lower(), body) is not None]
    if not named:
        return False
    need = {v: KB.get(v, {}).get("name_requires") for v in named}
    return all(need[v] and not any(w in body for w in need[v]) for v in named)


def _about(d: dict, vtoks: set, qtoks: set, exclude: Sequence[str] = (),
           vendors: Sequence[str] = ()) -> bool:
    """Is the document about the asked product? With a known vendor, the vendor
    name has to appear -- and for an advisory it has to appear in the subject,
    for the reason `_subject_names_product` gives. A KEV row that carries its
    vendor/product fields is decided by those instead (`kev_owns`). Without a
    vendor, fall back to sharing two content tokens with the question. The
    fallback is deliberately weak -- a document the question's own words do
    not touch is not evidence about it."""
    toks = _tokens(_text(d))
    if vtoks and d.get("source") in ADVISORY and d.get("kev_vendor"):
        return kev_owns(d, vendors, exclude)
    if vtoks and d.get("source") in ADVISORY and _lacks_required_word(d, vendors):
        return False
    if vtoks and d.get("source") in ADVISORY and vendors and all(
            _vendor_rules.other_wordpress_plugin(_text(d), v)
            or _vendor_rules.foreign_name_before(_text(d), v) for v in vendors):
        return False
    if vtoks:
        if not toks & vtoks:
            return False
        return (_subject_names_product(d, vtoks, exclude)
                and not _foreign_vendor_first(d, vendors)
                and not _platform_variant_mismatch(d, vtoks, qtoks)
                if d.get("source") in ADVISORY else True)
    return len(toks & qtoks) >= 2


def _version_ok(d: dict, asked: Sequence[str]) -> bool:
    """True when no version was asked, or the document names the asked one
    (prefix match, so "26.1" is satisfied by "26.1.1")."""
    if not asked:
        return True
    found = extract_versions(_text(d), multipart_only=False)
    return any(f == a or f.startswith(a + ".") or a.startswith(f + ".")
               for f in found for a in asked)


def _days(yyyymmdd: str) -> int:
    return date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:])).toordinal()


def _stale(d: dict, pool: Sequence[dict], asked: Sequence[str]) -> bool:
    """True when the advisory is over STALE_ADVISORY_DAYS older than the newest
    dated document in the pool. Undated advisories are kept (age unknown), and
    so is an old one naming the version the question asked about: a user on
    that old version is exactly who it applies to."""
    when = _date(d)
    newest = max(filter(None, (_date(x) for x in pool)), default=None)
    if not when or not newest or _days(newest) - _days(when) <= STALE_ADVISORY_DAYS:
        return False
    return not (asked and _version_ok(d, asked))


# ---------------------------------------------------------------------- rules

def decide(pool: Sequence[dict], question: str, vendors: Iterable[str] = (),
           versions: Optional[Sequence[str]] = None, k_reports: int = K_REPORTS,
           unchecked: Iterable[str] = ()) -> Decision:
    """The verdict the pool supports, with the obligations it met and missed.

    `vendors` are the grounded product names (grounding.ground / the sheet's
    `vendor`); `versions` default to the dotted versions in the question.
    `unchecked` names the evidence classes ("cve", "community") whose feed
    failed this run. A verdict that stands on the *absence* of that class --
    `safe` on both, `update_with_caveat` on community (with reports it could
    have been `hold`) -- abstains instead: absence of retrieved evidence is
    not evidence of safety when the source was never read.
    """
    unchecked = set(unchecked)
    asked = list(versions) if versions is not None else \
        extract_versions(question, multipart_only=True)
    vendors = list(vendors)
    vtoks, qtoks = _vendor_tokens(vendors), _tokens(question)
    exclude = [x.lower() for v in vendors
               for x in KB.get(str(v).lower(), {}).get("not_this_product", ())]
    about = [d for d in pool if d.get("doc_id") and _about(d, vtoks, qtoks, exclude, vendors)]
    on_version = [d for d in about if _version_ok(d, asked)]

    # An advisory counts when it is about the product even if it does not name
    # the asked version: KEV rows carry a CVE id and a product, not an affected
    # range, and "patch" is the right call for a product under active
    # exploitation. Whether the version was confirmed shows in `confidence`.
    advisories = [d for d in about if d.get("source") in ADVISORY
                  and _CVE_RE.search(_text(d) + " " + str(d.get("url", "")))]
    # `legacy`: a KEV entry the console shows as history (added over a year
    # ago, app_1._show_cve). Java's 2013 JRE rows said Patch now on a question
    # about the newest Java (sweep, 2026-11-23).
    advisories = [d for d in advisories if not _stale(d, pool, asked) and not d.get("legacy")]
    releases = [d for d in on_version if d.get("source") in RELEASE]
    reports = [d for d in on_version
               if d.get("source") in COMMUNITY and _PROBLEM_RE.search(_text(d))]
    newest_report = max((_date(d) or "" for d in reports), default="")
    fix_releases = [d for d in releases if _FIX_RE.search(_text(d))
                    and (_date(d) or "") > newest_report]
    caveats = [d for d in releases if _CAVEAT_RE.search(_text(d))]

    obligations = {
        "about_product": bool(about),
        "version_matched": bool(on_version),
        "advisory_with_cve": bool(advisories),
        "reports_at_least_k": len(reports) >= k_reports,
        "no_newer_fix_release": not fix_releases,
        "release_note_present": bool(releases),
        "caveat_named": bool(caveats),
        "sources_checked": not unchecked,
    }
    ids = lambda docs: [d["doc_id"] for d in docs]  # noqa: E731

    if advisories:
        # With no version asked, `_version_ok` is vacuously true; that is not a
        # confirmed match, so it must not earn the confirmed-version confidence.
        versioned = bool(asked) and any(_version_ok(d, asked) for d in advisories)
        return Decision("patch_urgently", ids(advisories), obligations, "obligations_met",
                        [], 1.0 if versioned else 0.8,
                        # "name" rather than "are about": attribution is a text
                        # match on the advisory's subject, and two of the seven
                        # it accepted over the 24 live macOS rows belonged to
                        # another product that merely runs on macOS (iTerm2,
                        # OpenSSH). Those are not separable from a genuine row
                        # by text alone -- "An issue in iTerm2 macOS before
                        # 3.6.12" and "An issue in macOS before 27.1" differ by
                        # a word no catalogue holds -- so the sentence claims
                        # only what was checked and points at the citations,
                        # which is where a reader catches the rest.
                        f"{len(advisories)} advisory document(s) with a CVE id name this "
                        f"product" + (f" on {asked[0]}" if versioned and asked else "")
                        + "; attribution is by text match, so check the citations")
    if len(reports) >= k_reports and not fix_releases:
        return Decision("hold", ids(reports), obligations, "obligations_met", ["release"],
                        min(1.0, len(reports) / (2 * k_reports)),
                        f"{len(reports)} community reports of a problem and no newer "
                        f"release note saying it is fixed")
    # Both verdicts below stand on something *not* being in the pool: a caveat
    # on fewer than K reports (else hold), safe on that and no advisory.
    caveat = bool(caveats or (reports and fix_releases))
    needs = {"community"} if caveat else {"cve", "community"} if releases else set()
    blind = sorted(unchecked & needs)
    if blind:
        return Decision("insufficient_evidence", [], obligations, "evidence_insufficient",
                        blind, 0.0,
                        f"the {' and '.join(blind)} source could not be checked this run, "
                        "so finding nothing there is not evidence that the update is safe")
    if caveats or (reports and fix_releases):
        used = caveats or (fix_releases + reports)
        return Decision("update_with_caveat", ids(used), obligations, "obligations_met", [],
                        0.8, "release note names a caveat" if caveats else
                        f"{len(reports)} problem report(s) and a newer release that fixes")
    if releases:
        # Absence-based: safe because nothing bad was found, so lower confidence
        # and name what a graph should still go and look for.
        probes = [p for p, have in (("cve", advisories), ("community", reports)) if not have]
        return Decision("safe", ids(releases), obligations, "obligations_met", probes, 0.6,
                        "release note present, no advisory, fewer than "
                        f"{k_reports} problem reports")
    # Nothing an obligation can stand on. Say which class of evidence is missing
    # so an active prober knows where to look instead of re-rolling the rewrite.
    missing = [p for p, have in (("release", releases), ("cve", advisories),
                                 ("community", reports)) if not have]
    reason = "no_evidence" if not about else "evidence_insufficient"
    return Decision("insufficient_evidence", [], obligations, reason, missing, 0.0,
                    "no document about the product" if not about else
                    "documents about the product, none meeting an obligation")


# --------------------------------------------------------------- graph gate

_EVIDENCE_BY_STOP = {"no_evidence": "absent", "evidence_insufficient": "ambiguous",
                     "obligations_met": "sufficient"}


def gate(vendors: Iterable[str] = (), k_reports: int = K_REPORTS,
         unchecked: Iterable[str] = ()):
    """`decide` in the shape graph.run wants: (query, docs, degraded) ->
    (Evidence, reason, payload). The stop reason is the evidence class --
    no document about the product is ABSENT, documents that meet no
    obligation are AMBIGUOUS, an obligation met is SUFFICIENT -- so the
    verdict rule and the attribute gate take the same edges, and ABSENT on a
    healthy fetch abstains without a retry here too."""
    from graph import Evidence
    vendors = list(vendors)

    def _gate(query: str, docs: Sequence[dict], degraded: bool = False):
        if degraded:
            return Evidence.DEGRADED, "fetch degraded", {}
        d = decide(docs, query, vendors=vendors, k_reports=k_reports, unchecked=unchecked)
        return Evidence(_EVIDENCE_BY_STOP[d.stop_reason]), d.rationale, d.as_dict()
    return _gate


# ------------------------------------------------------------------ rendering

REFUSAL = ("I cannot determine that from the sources retrieved, so I am not "
           "going to state it.")   # same wording as guardrail.REFUSAL, trips is_abstention

LEAD = {
    "patch_urgently": "Patch now",
    "hold": "Hold off on this update",
    "update_with_caveat": "Update, with a caveat",
    "safe": "Safe to update",
}


def render(decision: Decision, pool: Sequence[dict]) -> str:
    """One sentence a user can act on, citing the documents the rule used."""
    if decision.verdict == "insufficient_evidence":
        return REFUSAL
    by_id = {d.get("doc_id"): d for d in pool}
    cites = " ".join(f"[{by_id[i].get('title', '')[:60]}]" for i in decision.evidence[:3]
                     if i in by_id)
    return f"{LEAD[decision.verdict]}: {decision.rationale}. {cites}".strip()


# ---------------------------------------------------------------- self-check

def _score(rows: List[dict], gold_block: str) -> dict:
    """System verdict (collapsed) against one annotator block's labels."""
    from collections import Counter
    tp, fp, fn = Counter(), Counter(), Counter()
    abst_tp = abst_fp = abst_fn = 0
    ev_p, ev_r, n = [], [], 0
    for r in rows:
        g = (r.get(gold_block) or {}).get("verdict")
        if g is None:
            continue
        n += 1
        d = decide(r["evidence"], r["query"], vendors=[r.get("vendor", "")])
        p = d.verdict3
        (tp if p == g else fp)[p] += 1
        if p != g:
            fn[g] += 1
        if p == "insufficient_evidence" and g == "insufficient_evidence":
            abst_tp += 1
        elif p == "insufficient_evidence":
            abst_fp += 1
        elif g == "insufficient_evidence":
            abst_fn += 1
        gold_ids = set((r[gold_block] or {}).get("evidence_doc_ids") or [])
        if gold_ids and d.evidence:
            inter = len(gold_ids & set(d.evidence))
            ev_p.append(inter / len(d.evidence))
            ev_r.append(inter / len(gold_ids))
    if not n:
        return {"n": 0}
    f1 = []
    for c in ("act", "hold", "insufficient_evidence"):
        pr = tp[c] / (tp[c] + fp[c]) if tp[c] + fp[c] else 0.0
        rc = tp[c] / (tp[c] + fn[c]) if tp[c] + fn[c] else 0.0
        f1.append(2 * pr * rc / (pr + rc) if pr + rc else 0.0)
    return {
        "n": n, "accuracy": round(sum(tp.values()) / n, 3),
        "macro_f1": round(sum(f1) / 3, 3),
        "abstention_precision": round(abst_tp / (abst_tp + abst_fp), 3) if abst_tp + abst_fp else None,
        "abstention_recall": round(abst_tp / (abst_tp + abst_fn), 3) if abst_tp + abst_fn else None,
        "evidence_precision": round(sum(ev_p) / len(ev_p), 3) if ev_p else None,
        "evidence_recall": round(sum(ev_r) / len(ev_r), 3) if ev_r else None,
    }


if __name__ == "__main__":
    import argparse
    import json
    from collections import Counter

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--sheet", default="data/decision_benchmark_200.jsonl")
    ap.add_argument("--gold", default=None, help="annotator block to score against (a1, a2, gold)")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.sheet) if l.strip()]
    decs = [decide(r["evidence"], r["query"], vendors=[r.get("vendor", "")]) for r in rows]
    print(f"{len(rows)} questions, pool median {sorted(len(r['evidence']) for r in rows)[len(rows)//2]}")
    print("verdict (5):", dict(Counter(d.verdict for d in decs)))
    print("verdict (3):", dict(Counter(d.verdict3 for d in decs)))
    print("stop_reason:", dict(Counter(d.stop_reason for d in decs)))
    print("probes wanted:", dict(Counter(p for d in decs for p in d.probes_wanted)))
    by_asks = Counter((r["asks"], d.verdict3) for r, d in zip(rows, decs))
    for asks in sorted({r["asks"] for r in rows}):
        print(f"  {asks:11s}", {v: by_asks[(asks, v)] for v in ("act", "hold", "insufficient_evidence")})
    if a.gold:
        print(f"vs {a.gold}:", json.dumps(_score(rows, a.gold)))
