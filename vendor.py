"""
Vendor grounding: catalog, detection, disambiguation, filtering.
================================================================
The demo answered "What is the latest Linux version?" with
`Linux v25.642087.0`, and the natural reading is that the model invented it.
It did not. That string is verbatim from `/api/v/?q=Linux`, and the reason it
is wrong is a *record-type* confusion, not a generation failure:

    measured against the live endpoint, 2026-09-01, q=Linux, 606 rows

      versionProductName  isCve   n     versionNumber means
      ------------------  -----   ---   ------------------------------------
      "Linux"             True    449   the NVD *affected-version* string of
                                        a CVE record ("25.642087.0")
      "linux"             False   157   an actual kernel release ("7.1.0",
                                        from github.com/torvalds/linux)

Both arrive under one `q`, differing only in the capitalisation of a product
name, so a pipeline that treats every row as a release will answer a
"latest version" question with a CVE's affected-version field. No amount of
prompt engineering fixes that: the wrong document was retrieved, and a
faithful answer over a wrong document is still a wrong answer.

This module supplies the three things needed to keep them apart:

  * `load_catalog` / `detect_vendors` — the canonical product vocabulary from
    `/api/c/names` (5,776 names, 2026-09-01), so "Linux" is recognised as a
    catalog product rather than guessed at from capitalisation;
  * `classify_record` — release vs. security advisory, from the record itself;
  * `filter_by_vendor` — drop rows whose product is not the product asked
    about, which is what stops a "Chrome" question answering with `chromium-bsu`.

Rule-based and clock-free on purpose, for the same reasons `temporal` is: it
has to run on the deployed Streamlit host, which reaches no model, and it has
to be testable without a network. The catalog is cached to disk so a demo
answering one question does not re-download 104 KB of names.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

__all__ = [
    "CATALOG_URL",
    "VendorMatch",
    "load_catalog",
    "detect_vendors",
    "disambiguate",
    "classify_record",
    "is_release_record",
    "advisory_id",
    "describe_record",
    "doc_kind",
    "filter_by_vendor",
    "filter_community",
    "subreddit_vendor",
    "vendor_terms",
]

CATALOG_URL = "https://releasetrain.io/api/c/names"

# Where the downloaded catalog is cached. Kept next to the other fetched data
# so a clone that never runs the demo does not carry it.
_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "data", "vendor_names.json")

# The catalog is a flat list of every product string the upstream index knows,
# and a lot of them cannot be searched for: bare numbers ("3", "4.20"), two
# letter initialisms ("AA"), and generic words that appear in ordinary English
# questions. Matching those turns "What are the 3 latest updates?" into a query
# about the product named "3". A name has to clear all of these to be matchable.
_MIN_NAME_LEN = 3

# Catalog entries that are also ordinary question words. Matching them costs
# far more than it gains -- every one of these is a real row in /api/c/names.
_UNSEARCHABLE = frozenset({
    "all", "any", "are", "can", "core", "day", "die", "does", "end", "for",
    "free", "get", "has", "have", "help", "here", "how", "its", "latest",
    "less", "list", "look", "made", "make", "more", "most", "much", "need",
    "new", "news", "next", "not", "now", "one", "open", "our", "out", "own",
    "page", "part", "past", "put", "run", "see", "set", "show", "site", "some",
    "take", "team", "text", "than", "that", "the", "them", "then", "there",
    "they", "this", "time", "today", "top", "try", "two", "use", "used", "user",
    "using", "version", "versions", "very", "want", "was", "way", "web", "were",
    "what", "when", "where", "which", "who", "why", "will", "with", "work",
    "you", "your", "update", "updates", "release", "releases", "security",
    "patch", "patches", "bug", "bugs", "fix", "fixes", "issue", "issues",
    "software", "vulnerability", "vulnerabilities", "cve", "recent", "support",
})

# Query words that name a product without being the catalog's spelling of it.
# Small and hand-checked: an alias that maps to the wrong product is worse than
# no alias, because it silently narrows retrieval to another vendor's rows.
_ALIASES: Dict[str, str] = {
    "kernel": "linux",
    "linux kernel": "linux",
    "iphone": "ios",
    "ipad": "ios",
    "macbook": "macos",
    "mac": "macos",
    "osx": "macos",
    "os x": "macos",
    "win10": "windows",
    "win11": "windows",
    "chromium": "chrome",
    "gcloud": "google cloud",
    "postgres": "postgresql",
    "node": "node.js",
    "nodejs": "node.js",
    "k8s": "kubernetes",
    "vscode": "visual studio code",
    "nvim": "neovim",
    "chatgpt": "gpt",
    "openai": "gpt",
    "anthropic": "claude",
}

# A detected product whose catalog name is ambiguous in prose, and the phrase
# that resolves it. "Linux" alone reaches both the kernel release track and
# every CVE filed against a distribution kernel, which is exactly the collision
# this module exists to name; saying "Linux kernel" in the rewritten question
# tells a reader (and a judge) which one was meant.
_DISAMBIGUATION: Dict[str, str] = {
    "linux": "Linux kernel",
    "windows": "Microsoft Windows",
    "chrome": "Google Chrome",
    "edge": "Microsoft Edge",
    "java": "Java runtime",
    "go": "Go language",
    "rust": "Rust toolchain",
    "swift": "Swift language",
}

# Fallback vocabulary for a host that can neither reach the catalog endpoint
# nor find a cache. Deliberately the products the benchmark questions name, so
# an offline demo still detects a vendor instead of detecting none.
_FALLBACK_NAMES: Sequence[str] = (
    "linux", "chrome", "firefox", "safari", "edge", "windows", "macos", "ios",
    "android", "ubuntu", "debian", "fedora", "python", "django", "flask",
    "node.js", "deno", "bun", "react", "angular", "vue", "rust", "java",
    "kotlin", "swift", "php", "laravel", "ruby", "rails", "postgresql",
    "mysql", "mariadb", "mongodb", "redis", "sqlite", "docker", "kubernetes",
    "terraform", "ansible", "nginx", "apache", "openssl", "openssh", "curl",
    "git", "gitlab", "github", "jenkins", "elasticsearch", "kafka", "spark",
    "tensorflow", "pytorch", "numpy", "pandas", "visual studio code",
    "slack", "zoom", "outlook", "wordpress", "drupal", "jira", "homeassistant",
    "truenas", "neovim", "ollama", "claude", "gpt", "gemini", "llama",
    "mistral", "deepseek", "qwen", "spotify",
)


@dataclass(frozen=True)
class VendorMatch:
    """One product detected in a question."""

    name: str            # the catalog spelling, lowercased
    matched: str         # the substring of the query that matched
    via_alias: bool = False

    @property
    def display(self) -> str:
        """The phrase to use when rewriting the question for a human."""
        return _DISAMBIGUATION.get(self.name, self.name)


def _searchable(name: str) -> bool:
    """Whether a catalog entry is safe to match against free text."""
    low = name.strip().lower()
    if len(low) < _MIN_NAME_LEN or low in _UNSEARCHABLE:
        return False
    # Bare version-ish strings ("3", "4.20", "2.5 Pro") name a model release in
    # the catalog but match arithmetic in a question.
    if re.fullmatch(r"[\d.\s]+", low):
        return False
    # A name has to contain a letter run long enough to be a word, which drops
    # "3mini" and "4G" while keeping "k9s" and "vlc".
    return bool(re.search(r"[a-z]{2,}", low))


def load_catalog(path: Optional[str] = None, fetch: bool = True,
                 timeout: int = 15) -> List[str]:
    """The canonical product vocabulary, lowercased and de-duplicated.

    Disk cache first, network second, bundled fallback last. `fetch=False`
    keeps it offline, which is what the tests and any replayable evaluation
    run use -- a catalog that changes under a rerun would make retrieval
    non-reproducible.
    """
    cache = path or _CACHE_PATH
    names: List[str] = []

    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as fh:
                names = [str(n) for n in json.load(fh)]
        except (OSError, ValueError):
            names = []

    if not names and fetch:
        try:
            import requests  # imported lazily: offline hosts never need it
            resp = requests.get(CATALOG_URL, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()
            names = [str(n) for n in payload if isinstance(n, str)]
            try:
                os.makedirs(os.path.dirname(cache), exist_ok=True)
                with open(cache, "w", encoding="utf-8") as fh:
                    json.dump(names, fh)
            except OSError:
                pass          # a read-only host still gets the in-memory list
        except Exception:
            names = []

    if not names:
        names = list(_FALLBACK_NAMES)

    seen, out = set(), []
    for n in names:
        low = n.strip().lower()
        if low and low not in seen and _searchable(low):
            seen.add(low)
            out.append(low)
    return out


def detect_vendors(query: str, catalog: Optional[Sequence[str]] = None,
                   limit: int = 3) -> List[VendorMatch]:
    """Products named in `query`, most specific first.

    Longest match wins, so "visual studio code" is detected as itself and not
    as "code": a question about one product should not retrieve another's rows
    merely because the shorter name is a substring of the longer one.
    """
    if catalog is None:
        catalog = load_catalog()
    low = query.lower()
    found: List[VendorMatch] = []
    claimed: List[str] = []

    def overlaps(term: str) -> bool:
        return any(term in c or c in term for c in claimed)

    # Aliases first: they are hand-checked, and "kernel" should resolve to
    # linux even though the catalog has no entry spelled "kernel".
    # Same boundary guard as the catalog pass below, not `\b`: `\b` treats the
    # hyphen in "chromium-bsu" as a word boundary, so `\bchromium\b` matches a
    # different product's name and a question about a game retrieves Chrome.
    for alias, canon in sorted(_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![\w.-]){re.escape(alias)}(?![\w-])", low) and not overlaps(canon):
            found.append(VendorMatch(name=canon, matched=alias, via_alias=True))
            claimed.append(canon)

    for name in sorted(catalog, key=len, reverse=True):
        if len(found) >= limit:
            break
        if overlaps(name):
            continue
        if re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w-])", low):
            found.append(VendorMatch(name=name, matched=name))
            claimed.append(name)

    return found[:limit]


def disambiguate(query: str, vendors: Sequence[VendorMatch]) -> str:
    """`query` with an ambiguous product name replaced by its resolving phrase.

    "What is the latest Linux version?" -> "What is the latest Linux kernel
    version?". Only the names in `_DISAMBIGUATION` are touched, and only when
    the resolving phrase is not already present, so a question that already
    said "Linux kernel" is returned unchanged.
    """
    out = query
    for v in vendors:
        phrase = _DISAMBIGUATION.get(v.name)
        if not phrase or phrase.lower() in out.lower():
            continue
        pattern = re.compile(rf"(?<![\w-]){re.escape(v.matched)}(?![\w-])", re.I)
        if pattern.search(out):
            out = pattern.sub(phrase, out, count=1)
    return out


def vendor_terms(vendors: Sequence[VendorMatch]) -> List[str]:
    """The single-term phrasings to fetch on, given detected products.

    The release endpoint matches `q` against product names, so the term -- not
    the sentence -- is what retrieves. Same role as `fetch_union.product_terms`,
    but catalog-grounded rather than capitalisation-guessed.
    """
    return [v.name for v in vendors]


# ── Record type ───────────────────────────────────────────────────────────

def classify_record(row: Dict) -> str:
    """`"advisory"` for a CVE record, `"release"` for a shipped version.

    Reads the record rather than the query, because the two arrive
    interleaved under one `q`. `isCve` is the upstream's own flag and is
    authoritative when present; the URL host is the fallback, since an NVD or
    MITRE link is never a release announcement.
    """
    if row.get("isCve") is True:
        return "advisory"
    url = str(row.get("url") or row.get("versionUrl") or "").lower()
    if "nvd.nist.gov" in url or "cve.org" in url or "cve.mitre.org" in url:
        return "advisory"
    notes = str(row.get("notes") or row.get("versionReleaseNotes") or "")
    if notes.lstrip().lower().startswith("in the linux kernel, the following vulnerability"):
        return "advisory"
    return "release"


def is_release_record(row: Dict) -> bool:
    """True when the row describes a version that actually shipped."""
    return classify_record(row) == "release"


def doc_kind(row: Dict) -> str:
    """`"cve"`, `"community"` or `"release"` — the kind `intent.citable_kinds` names.

    `classify_record` answers a narrower question (is this row a shipped
    version or an advisory) and defaults to `"release"`, which is right for a
    release-feed row and wrong for a Reddit post. This is the mapping a
    citability filter needs: filtering on `classify_record` alone keeps
    community posts as though they were releases.
    """
    if classify_record(row) == "advisory":
        return "cve"

    source = str(row.get("source") or "").lower()
    url = str(row.get("url") or "").lower()

    # `source` is checked before anything else because `RetrieverAgent` reuses
    # the `subreddit` field to carry a release's *brand* ("torvalds"), so a
    # subreddit test run first labels every kernel release a community post.
    if "release" in source or "github" in source:
        return "release"
    if "reddit" in source or "reddit.com" in url or "news" in source:
        return "community"
    if row.get("version") or row.get("versionNumber"):
        return "release"
    return "community"


_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.I)


def advisory_id(row: Dict) -> str:
    """The CVE identifier a row is about, or `""`.

    Read from the URL, which is where it actually is -- an advisory row's
    `versionNumber` holds an affected-version string, and its notes hold the
    kernel's own description of the flaw.
    """
    haystack = " ".join(str(row.get(k) or "") for k in
                        ("url", "versionUrl", "title", "notes", "versionReleaseNotes"))
    m = _CVE_RE.search(haystack)
    return m.group(0).upper() if m else ""


def describe_record(row: Dict) -> str:
    """How a row should be named when it is cited.

    An advisory is named by its CVE id, never by its `versionNumber`: printing
    "Linux v25.642087.0" invites the reader to believe a version by that name
    shipped, which is the misreading this whole module exists to prevent. The
    affected-version string is still reported, but as what it is.
    """
    product = str(row.get("product") or row.get("versionProductName") or "").strip()
    version = str(row.get("version") or row.get("versionNumber") or "").strip()
    if classify_record(row) == "release":
        return f"{product} v{version}".strip() if version else product

    cve = advisory_id(row)
    head = cve or f"{product} advisory"
    return f"{head} (affects {product} {version})" if version else head


# Subreddit -> catalog product. The community feed carries no product field at
# all, only the subreddit a post came from, so this is the only handle on which
# product a post is about. Hand-built from the subreddits actually present in
# `/api/reddit/query/positive` (200 rows sampled 2026-09-01): chrome 58,
# MicrosoftEdge 37, firefox 14, applehelp 14, and a long tail.
_SUBREDDIT_VENDOR: Dict[str, str] = {
    "chrome": "chrome", "chromeos": "chrome", "googlechrome": "chrome",
    "microsoftedge": "edge", "edge": "edge",
    "firefox": "firefox", "mozilla": "firefox",
    "applehelp": "macos", "macos": "macos", "mac": "macos", "osx": "macos",
    "ios": "ios", "iphone": "ios", "ipad": "ios",
    "windows": "windows", "windows10": "windows", "windows11": "windows",
    "sysadmin": "", "linux": "linux", "linuxquestions": "linux",
    "kernel": "linux", "archlinux": "arch", "ubuntu": "ubuntu",
    "debian": "debian", "fedora": "fedora", "pop_os": "pop!_os",
    "android": "android", "androidquestions": "android",
    "neovim": "neovim", "vim": "vim", "emacs": "emacs",
    "wordpress": "wordpress", "docker": "docker", "kubernetes": "kubernetes",
    "homeassistant": "homeassistant", "truenas": "truenas",
    "ollama": "ollama", "comfyui": "comfyui", "immich": "immich",
    "ubiquiti": "ubiquiti", "python": "python", "rust": "rust",
    "golang": "go", "node": "node.js", "reactjs": "react",
}


def subreddit_vendor(subreddit: str) -> str:
    """The product a subreddit is about, or `""` when it is a general forum.

    `r/sysadmin` maps to nothing on purpose: it discusses every product, so
    treating it as one product's evidence would attribute an unrelated
    complaint to whatever was asked about.
    """
    return _SUBREDDIT_VENDOR.get(str(subreddit or "").strip().lower(), "")


def filter_community(rows: Iterable[Dict], vendors: Sequence[VendorMatch],
                     terms: Sequence[str] = ()) -> List[Dict]:
    """Keep community posts that are about one of the detected products.

    Needed because `/api/reddit/query/positive` ignores its `q` parameter
    entirely -- verified 2026-09-01, where `q=linux`, `q=chrome` and a full
    sentence all return byte-identical 50-row pages. The Community Agent was
    therefore doing no query-dependent retrieval at all: it returned the same
    global feed whatever was asked. Since the endpoint cannot be filtered
    server-side, the filter has to run here.

    A post matches on its subreddit's product, or on a product name appearing
    in its title. With no vendor detected, `terms` (the question's content
    words) are used instead, and if those match nothing the rows pass through
    unfiltered -- an empty community pool is worse than a loose one.

    A subreddit match says the post is about the right *product*. It says
    nothing about whether it is about the right *subject*, and the two were
    treated as one: asked whether a Fedora update deleted a kernel and grub,
    the detected vendors were linux and fedora, and the single row that
    survived the 50-row global feed was "How to limit battery charge?" from
    r/linuxquestions -- kept because the subreddit is a Linux one, and then
    cited in the answer as this question's community evidence. `terms` was
    already being computed and passed in for exactly this, but it was read only
    in the branch above, so the moment a vendor was detected the subject
    dropped out of the decision entirely.

    So the product match now narrows to the rows that also share a content
    word with the question, and unlike the no-vendor branch above this
    narrowing is allowed to empty the pool. The rule this file follows
    elsewhere is the CVE pool's, not the fallback's: a thin pool beats a false
    one. "No community posts matched" is a true statement about the feed and
    costs the answer a sentence; handing the presenter an off-subject post
    because something had to be returned costs it a citation that is wrong.
    The vendor branch is where that distinction bites, because a subreddit
    match guarantees a plausible-looking row is always available to fall back
    to.
    """
    wanted = {v.name for v in vendors}
    rows = list(rows)
    if not wanted:
        if not terms:
            return rows
        low_terms = [t.lower() for t in terms if len(t) > 2]
        hit = [r for r in rows
               if any(t in str(r.get("title", "")).lower() for t in low_terms)]
        return hit or rows

    out = []
    for r in rows:
        sub = subreddit_vendor(r.get("subreddit", ""))
        title = str(r.get("title", "")).lower()
        if (sub and sub in wanted) or any(
                re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", title) for w in wanted):
            out.append(r)

    low_terms = [t.lower() for t in terms if len(t) > 2]
    if low_terms:
        return [r for r in out
                if any(t in str(r.get("title", "")).lower() for t in low_terms)]
    return out


def filter_by_vendor(rows: Iterable[Dict], vendors: Sequence[VendorMatch],
                     field: str = "product") -> List[Dict]:
    """Keep only rows whose product is one of the detected products.

    Exact match on the lowercased product name, not a substring test: the
    catalog contains `chromium-bsu` and `LinuxCNC`, and a substring test lets
    a question about Chrome answer with a game's release notes. Rows with no
    product field survive -- community posts carry no product, and dropping
    them would silently empty the community pool.

    With no vendor detected the rows pass through: filtering on nothing would
    be filtering everything.
    """
    wanted = {v.name for v in vendors}
    if not wanted:
        return list(rows)
    out = []
    for r in rows:
        product = str(r.get(field) or "").strip().lower()
        if not product or product in wanted:
            out.append(r)
    return out
