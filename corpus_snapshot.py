"""
Frozen-corpus record/replay for the evaluation harness.
=======================================================
Why this module exists
----------------------
Every retrieval in this project reads *live* endpoints — releasetrain.io,
CISA KEV, Apple RSS, Google News, Reddit — plus a local Ollama for the query
rewrite, the embeddings and the answer. Nothing about that is stable between
two runs a few minutes apart.

Measured on the three-arm rerank ablation of 2026-08-30: for the *same*
question and the *same* system, the retrieved document set differed on 10 of
10 questions between consecutive runs. Both arms of that sweep shared
`RetrieverAgent`, so both were reranked, and there was no rerank-independent
control. Arm effect and corpus drift were therefore not separable at all —
the numbers could not be interpreted, at any sample size.

An ablation compares arms. If the corpus moves under the arms, it compares
nothing. This module freezes the corpus so `MARAG_RERANK` is the only thing
that differs between two runs.

How it works
------------
Both HTTP paths the project uses are wrapped:

    requests.get(...)              -> every fetch_* live source
    urllib.request.urlopen(...)    -> call_llama (rewrite), Ollama embeddings,
                                      eval_harness.providers (judge, synthesis)

A request is keyed by what determines its response — method, full URL, sorted
query params, and a hash of the body — and the raw bytes are stored under that
key. Nothing is parsed, so a snapshot is faithful to whatever the endpoint
actually returned, including malformed or empty payloads.

Usage
-----
    MARAG_CORPUS=record:data/corpus_snapshot   # pass 1: populate from live
    MARAG_CORPUS=replay:data/corpus_snapshot   # passes 2..n: serve from disk
    MARAG_CORPUS=strict:data/corpus_snapshot   # same, but a document miss is fatal

Record once, then run every arm against `replay`. The arms then see byte-
identical sources.

Miss policy
-----------
`replay` is deliberately *not* strict. A miss goes live, is recorded, and is
counted. A hard failure would be worse than useless here: arms legitimately
make calls the recording pass never made — the embedding arm calls Ollama's
embeddings endpoint and the `none` arm never does — and killing the run for
that would make the ablation unrunnable.

`strict` is `replay` for everyone except the document sources: a miss on a
corpus host raises `CorpusMiss` instead of going live, while model calls to
localhost still pass through exactly as under `replay`. That keeps the reason
replay is lenient — arms make different model calls — while removing the
failure mode it allows, where two arms of the same experiment quietly read
different documents. Use it for runs whose numbers have to be re-derivable:
record once, then run every arm under `strict:<dir>` and a run that would have
drifted stops instead of reporting.

What matters is that misses are *visible*, so `stats()` reports them broken
down by host and the harness writes them into `config.json`. A run whose
misses include a corpus host (releasetrain.io, reddit, CISA, ...) did not have
a frozen corpus, and its cross-arm comparison is void. A run whose misses are
all `localhost:11434` is fine: those are model calls the arm is supposed to
make, not documents.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
from datetime import datetime
import urllib.parse
import urllib.request
from typing import Dict, Optional

ENV_VAR = "MARAG_CORPUS"


class CorpusMiss(RuntimeError):
    """
    A `strict` replay needed a document the snapshot does not hold.

    Raised only for corpus hosts. `replay` keeps its lenient behaviour; this is
    for the runs whose numbers have to be re-derivable later, where a document
    fetched live is a silent difference between arms rather than a convenience.
    """


class RecordedFailure(Exception):
    """Raised on replay where the recording pass saw the request fail.

    Every fetch in the pipeline is already wrapped in try/except, so this
    surfaces to the caller exactly as the original network error did.
    """

# Hosts that serve *documents*. A replay miss on one of these means the corpus
# was not actually frozen for that call; a miss anywhere else (the local model
# server) is expected and harmless.
CORPUS_HOST_HINTS = (
    "releasetrain.io", "reddit.com", "cisa.gov", "apple.com", "circl.lu",
    "news.google.com", "github.com", "nvd.nist.gov", "cve.org", "cveawg",
)


def is_corpus_host(url: str) -> bool:
    """True when a URL serves retrievable documents rather than model output."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(h in host for h in CORPUS_HOST_HINTS)


# ─────────────────────────────────────────────────────────────────────────
# Keying
# ─────────────────────────────────────────────────────────────────────────

def request_key(method: str, url: str, params: Optional[dict] = None,
                body: Optional[bytes] = None) -> str:
    """Canonical key for one request.

    Params are sorted so that `?a=1&b=2` and `?b=2&a=1` share a recording, and
    the body is hashed rather than embedded so a long Ollama prompt does not
    become a filename. Two calls with the same key must be two calls that
    should get the same answer.
    """
    parsed = urllib.parse.urlparse(url)
    merged = urllib.parse.parse_qsl(parsed.query)
    if params:
        merged += [(str(k), str(v)) for k, v in params.items()]
    qs = urllib.parse.urlencode(sorted(merged))
    base = urllib.parse.urlunparse(parsed._replace(query=""))
    bh = hashlib.sha1(body or b"").hexdigest()[:12]
    return f"{method.upper()}|{base}|{qs}|{bh}"


def _key_path(directory: str, key: str) -> str:
    return os.path.join(directory, hashlib.sha1(key.encode()).hexdigest()[:20] + ".json.gz")


# ─────────────────────────────────────────────────────────────────────────
# Response shims
# ─────────────────────────────────────────────────────────────────────────

class ReplayedResponse:
    """Stands in for a `requests.Response` over recorded bytes.

    Only the surface the project actually touches is implemented —
    `status_code`, `json()`, `text`, `content`, `ok`, `raise_for_status()`,
    `headers`. Anything else should fail loudly rather than return a
    plausible-looking default.
    """

    def __init__(self, status: int, content: bytes, headers: Optional[dict] = None,
                 url: str = ""):
        self.status_code = status
        self.content = content
        self.headers = headers or {}
        self.url = url

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.content.decode("utf-8", "replace"))

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code} for {self.url}")


class ReplayedUrlResponse:
    """Stands in for the object `urllib.request.urlopen` returns."""

    def __init__(self, status: int, content: bytes, headers: Optional[dict] = None):
        self.status = status
        self._content = content
        self.headers = headers or {}

    def read(self, *_a) -> bytes:
        return self._content

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


# ─────────────────────────────────────────────────────────────────────────
# Snapshot
# ─────────────────────────────────────────────────────────────────────────

class Snapshot:
    """Record/replay layer over the two HTTP entry points the project uses."""

    def __init__(self, mode: str, directory: str):
        if mode not in ("record", "replay", "strict"):
            raise ValueError(
                f"corpus mode must be record|replay|strict, got {mode!r}")
        self.mode = mode
        self.dir = directory
        self.hits = 0
        self.misses = 0
        self.recorded = 0
        self.miss_urls: Dict[str, int] = {}
        self._active = False
        self._real_requests_get = None
        self._real_urlopen = None
        os.makedirs(self.dir, exist_ok=True)
        self.recorded_at = self._pin_clock()

    # ---- the clock ------------------------------------------------------

    META = "_meta.json"

    def _pin_clock(self) -> Optional[str]:
        """Freeze time along with the content.

        Retrieval reads the clock: "latest" and "last week" become date filters
        that decide which documents are fetched and kept (`temporal.now`). A
        snapshot that freezes only the HTTP responses therefore still drifts --
        replayed a day after it was recorded, the same questions came back with
        16.8 candidates apiece against the 20.1 of the recording day, which is
        enough to move every retrieval metric and to confound any comparison
        whose arms ran on different days.

        So a recording stamps the directory with its date, and a replay sets
        `MARAG_NOW` from that stamp. An explicitly set `MARAG_NOW` always wins,
        and a snapshot recorded before this existed has no stamp: the run goes
        on with the live clock and `stats()` reports `recorded_at: null`, which
        is the honest answer rather than a guess.
        """
        meta_path = os.path.join(self.dir, self.META)
        if self.mode == "record":
            if not os.path.exists(meta_path):
                stamp = datetime.now().replace(microsecond=0).isoformat()
                try:
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump({"recorded_at": stamp}, f)
                except OSError:
                    return None
            # fall through: a re-record into an existing directory keeps the
            # original stamp, so the two passes share one clock.
        try:
            with open(meta_path, encoding="utf-8") as f:
                stamp = json.load(f).get("recorded_at")
        except (OSError, ValueError):
            return None
        if stamp and not os.environ.get("MARAG_NOW", "").strip():
            os.environ["MARAG_NOW"] = str(stamp)
        return stamp

    # ---- storage --------------------------------------------------------

    def _load(self, key: str) -> Optional[dict]:
        p = _key_path(self.dir, key)
        if not os.path.exists(p):
            return None
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001 — a corrupt entry is a miss, not a crash
            return None

    def _store(self, key: str, status: int, content: bytes, headers: dict,
               url: str) -> None:
        rec = {
            "key": key,
            "url": url,
            "status": int(status),
            "headers": {str(k): str(v) for k, v in (headers or {}).items()},
            "body_b64": base64.b64encode(content or b"").decode("ascii"),
        }
        with gzip.open(_key_path(self.dir, key), "wt", encoding="utf-8") as f:
            json.dump(rec, f)
        self.recorded += 1

    @staticmethod
    def _body(rec: dict) -> bytes:
        return base64.b64decode(rec.get("body_b64") or "")

    def _store_failure(self, key: str, url: str, exc: BaseException) -> None:
        """Record that a request *failed*, so replay reproduces the same failure.

        Recording only successes leaves a permanently unrecorded request: the
        call raises, nothing is stored, and the next replay misses again and
        goes live again. Measured on the 100-question run, 4 such requests
        leaked on every arm, and because one failed source call drops a whole
        tier the candidate pool differed on 16 of 200 (system, question) pairs
        -- pool sizes of 20 against 9 for the same question.

        A frozen corpus must freeze what the experiment actually observed, and
        what it observed here was a failure. Replaying the failure keeps every
        arm on identical inputs, which is the property the control exists for.
        """
        rec = {"key": key, "url": url, "error": f"{type(exc).__name__}: {exc}"[:500]}
        with gzip.open(_key_path(self.dir, key), "wt", encoding="utf-8") as f:
            json.dump(rec, f)
        self.recorded += 1

    @staticmethod
    def _replay_failure(rec: dict):
        """Re-raise a recorded failure. Callers already guard every fetch."""
        raise RecordedFailure(rec.get("error", "recorded failure"))

    def _on_miss(self, url: str) -> None:
        """Count the miss, and under `strict` refuse to substitute a live read."""
        self._note_miss(url)
        if self.mode == "strict" and is_corpus_host(url):
            raise CorpusMiss(
                f"strict replay: {url} is not in the snapshot at {self.dir!r}. "
                f"Fetching it live would give this arm a document the others "
                f"did not see. Re-record the snapshot, or use replay: to allow "
                f"live reads and accept that the run is not frozen.")

    def _note_miss(self, url: str) -> None:
        self.misses += 1
        host = (urllib.parse.urlparse(url).hostname or "?").lower()
        self.miss_urls[host] = self.miss_urls.get(host, 0) + 1

    # ---- patched entry points -------------------------------------------

    def _get(self, url, **kw):
        """Replacement for `requests.get`."""
        key = request_key("GET", url, kw.get("params"))
        if self.mode in ("replay", "strict"):
            rec = self._load(key)
            if rec is not None:
                self.hits += 1
                if "error" in rec:
                    self._replay_failure(rec)
                return ReplayedResponse(rec["status"], self._body(rec),
                                        rec.get("headers"), url)
            self._on_miss(url)
        try:
            resp = self._real_requests_get(url, **kw)
        except Exception as e:  # noqa: BLE001 — a failure is an observation too
            self._store_failure(key, url, e)
            raise
        try:
            self._store(key, getattr(resp, "status_code", 0), resp.content or b"",
                        dict(getattr(resp, "headers", {}) or {}), url)
        except Exception:  # noqa: BLE001 — recording must never break a live run
            pass
        return resp

    def _urlopen(self, req, *a, **kw):
        """Replacement for `urllib.request.urlopen`."""
        if isinstance(req, urllib.request.Request):
            url = req.full_url
            method = req.get_method()
            body = req.data or b""
            headers = dict(req.headers or {})
        else:
            url, method, body, headers = str(req), "GET", b"", {}
        key = request_key(method, url, None, body)

        if self.mode in ("replay", "strict"):
            rec = self._load(key)
            if rec is not None:
                self.hits += 1
                if "error" in rec:
                    self._replay_failure(rec)
                return ReplayedUrlResponse(rec["status"], self._body(rec),
                                           rec.get("headers"))
            self._on_miss(url)

        try:
            resp = self._real_urlopen(req, *a, **kw)
            # The caller gets one shot at the stream, so read it here and hand
            # back a replay object over the same bytes, not a half-consumed one.
            content = resp.read()
        except Exception as e:  # noqa: BLE001 — a failure is an observation too
            self._store_failure(key, url, e)
            raise
        status = getattr(resp, "status", None) or resp.getcode() or 0
        try:
            self._store(key, status, content, dict(getattr(resp, "headers", {}) or {}),
                        url)
        except Exception:  # noqa: BLE001
            pass
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
        return ReplayedUrlResponse(status, content, headers)

    # ---- lifecycle ------------------------------------------------------

    def start(self) -> "Snapshot":
        if self._active:
            return self
        import requests

        self._real_requests_get = requests.get
        self._real_urlopen = urllib.request.urlopen
        requests.get = self._get
        urllib.request.urlopen = self._urlopen
        self._active = True
        return self

    def stop(self) -> None:
        if not self._active:
            return
        import requests

        requests.get = self._real_requests_get
        urllib.request.urlopen = self._real_urlopen
        self._active = False

    def __enter__(self) -> "Snapshot":
        return self.start()

    def __exit__(self, *_a) -> bool:
        self.stop()
        return False

    # ---- reporting ------------------------------------------------------

    def stats(self) -> dict:
        """Everything a results table needs to say whether the corpus held."""
        corpus_misses = {h: n for h, n in self.miss_urls.items()
                         if any(x in h for x in CORPUS_HOST_HINTS)}
        return {
            "mode": self.mode,
            "dir": self.dir,
            "hits": self.hits,
            "misses": self.misses,
            "recorded": self.recorded,
            "misses_by_host": dict(sorted(self.miss_urls.items())),
            "corpus_misses": sum(corpus_misses.values()),
            # `strict` cannot finish with a corpus miss -- the run raises -- so a
            # strict run that reached stats() is frozen by construction.
            "frozen": self.mode in ("replay", "strict") and not corpus_misses,
            "strict": self.mode == "strict",
            "recorded_at": self.recorded_at,
            "now": os.environ.get("MARAG_NOW") or None,
        }


def activate(spec: Optional[str] = None) -> Optional[Snapshot]:
    """Build and start a snapshot from a `record:` / `replay:` / `strict:` spec.

    Returns None when no spec is set, which is the ordinary live behaviour —
    the harness must run unchanged for anyone who does not want a snapshot.
    """
    spec = spec if spec is not None else os.environ.get(ENV_VAR, "")
    spec = (spec or "").strip()
    if not spec:
        return None
    if ":" not in spec:
        raise ValueError(
            f"{ENV_VAR} must look like record:<dir>, replay:<dir> or "
            f"strict:<dir>, got {spec!r}")
    mode, directory = spec.split(":", 1)
    return Snapshot(mode.strip().lower(), directory.strip()).start()
