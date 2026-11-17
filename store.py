"""
Persistence: what was retrieved, and what was answered over it.
==============================================================
Everything the pipeline learned used to die with the process. Each demo run
re-fetched the same rows from releasetrain.io, and the only record that a run
happened at all was whatever the user still had on screen. Two concrete costs:

  * **A host that cannot reach the API answers nothing.** The fetchers in
    `app_1.py` return an "API unavailable" placeholder row and the answer is
    composed over it. Yet the rows needed to answer are the same rows the last
    twenty runs already fetched.
  * **No run is inspectable after the fact.** The paper's failure analysis is
    reconstructed from harness artifacts in `results/`, which the demo does not
    write. A question answered in the UI leaves no trace to point at.

This module is the store that fixes both, and nothing more. It is deliberately
*not* a second retrieval system: ranking stays in `fetch_union`, intent in
`intent`, record typing in `vendor`. The store holds documents and runs.

    documents      one row per retrieved document, keyed the same way
                   `fetch_union.doc_key` dedupes them, so a document fetched
                   under three phrasings is one row and not three.
    documents_fts  FTS5 over product/title/notes, which is what makes the
                   offline fallback a search rather than a dump.
    runs           one row per answered question: the phrasings, the intent,
                   the answer, the timings.
    run_documents  which documents that run retrieved, at what rank, and
                   which ones the answer cited.

`sqlite3` from the standard library, on purpose. `requirements.txt` is pinned
so a re-run reproduces the reported numbers, and a store that exists to make
the demo survive a dead network should not itself add a dependency that can
fail to install. One file under `data/`, gitignored like the other fetched
data -- it is a cache and a log, not a source.

Every write is best-effort from the caller's point of view: `record_*` raises
nothing a demo has to catch, because a store failing must never be the reason
a question goes unanswered. Read paths are explicit and do raise, since a
caller asking the store a question wants the answer or the error.
"""

from __future__ import annotations

import functools
import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from fetch_union import doc_key

__all__ = [
    "DEFAULT_PATH",
    "SCHEMA_VERSION",
    "POOLS",
    "Store",
    "open_store",
    "caching_fetch",
]

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "marag.db")

# Bumped when the schema changes in a way an existing file cannot satisfy.
# Stored in `PRAGMA user_version`, which sqlite carries in the file header, so
# a stale database is detected without a metadata table of its own.
SCHEMA_VERSION = 1

# The three retrieval pools, named as `intent.pool_weights` names them so a
# weight and a stored row can be joined without a translation table.
POOLS = ("release", "cve", "community")

# Rows the fetchers return *instead of* results when the endpoint is down.
# Storing them would poison the fallback: the offline path would then serve
# the record of an outage as though it were a document.
_PLACEHOLDER_PREFIXES = ("api unavailable", "cve api unavailable")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_key    TEXT PRIMARY KEY,
    pool       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    product    TEXT NOT NULL DEFAULT '',
    version    TEXT NOT NULL DEFAULT '',
    published  TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    url        TEXT NOT NULL DEFAULT '',
    is_cve     INTEGER NOT NULL DEFAULT 0,
    payload    TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS documents_pool_seen
    ON documents (pool, last_seen DESC);
CREATE INDEX IF NOT EXISTS documents_product
    ON documents (product);

CREATE TABLE IF NOT EXISTS runs (
    run_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT NOT NULL,
    original_query   TEXT NOT NULL,
    grounded_query   TEXT NOT NULL DEFAULT '',
    rewritten_query  TEXT NOT NULL DEFAULT '',
    intent           TEXT NOT NULL DEFAULT '',
    intent_confident INTEGER NOT NULL DEFAULT 0,
    vendors          TEXT NOT NULL DEFAULT '[]',
    phrasings        TEXT NOT NULL DEFAULT '[]',
    answer           TEXT NOT NULL DEFAULT '',
    evaluation       TEXT NOT NULL DEFAULT '{}',
    timing           TEXT NOT NULL DEFAULT '{}',
    offline          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS runs_ts ON runs (ts DESC);

CREATE TABLE IF NOT EXISTS run_documents (
    run_id  INTEGER NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    doc_key TEXT    NOT NULL,
    pool    TEXT    NOT NULL,
    rank    INTEGER NOT NULL,
    cited   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, pool, doc_key)
);
"""

# External-content FTS: the index reads its text out of `documents` rather than
# storing a second copy, so the file does not double in size. Kept in its own
# statement block because a sqlite built without FTS5 must still get a usable
# store -- `search` degrades to LIKE, which is slower and dumber but correct.
_SCHEMA_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5 (
    product, title, notes,
    content='documents', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts (rowid, product, title, notes)
    VALUES (new.rowid, new.product, new.title, new.notes);
END;
CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts (documents_fts, rowid, product, title, notes)
    VALUES ('delete', old.rowid, old.product, old.title, old.notes);
END;
CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts (documents_fts, rowid, product, title, notes)
    VALUES ('delete', old.rowid, old.product, old.title, old.notes);
    INSERT INTO documents_fts (rowid, product, title, notes)
    VALUES (new.rowid, new.product, new.title, new.notes);
END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# How old a stored document may be and still stand in for a feed that is down.
# The store's newest CVE row was last seen 2026-10-13, so before this bound a
# November outage was answered with September advisories as if current.
# ponytail: one global window; per-pool windows if releases need a longer one.
FALLBACK_MAX_AGE_DAYS = int(os.environ.get("MARAG_STORE_MAX_AGE_DAYS", "14"))


def _is_placeholder(row: Dict) -> bool:
    """True for the outage row a fetcher returns in place of results."""
    for field in ("title", "product"):
        text = str(row.get(field) or "").strip().lower()
        if any(text.startswith(p) for p in _PLACEHOLDER_PREFIXES):
            return True
    return False


def _kind(pool: str, row: Dict) -> str:
    """Release, advisory or community post.

    Same distinction `vendor.classify_record` draws and for the same reason --
    a CVE's `versionNumber` is an affected-version string, not a shipped
    version -- but read off the *normalised* row the app fetchers produce
    (`is_cve`, `url`) rather than the upstream field names.
    """
    if pool == "community":
        return "community"
    if row.get("is_cve") is True or pool == "cve":
        return "advisory"
    url = str(row.get("url") or "").lower()
    if "nvd.nist.gov" in url or "cve.org" in url or "cve.mitre.org" in url:
        return "advisory"
    return "release"


def _normalise(pool: str, row: Dict) -> Optional[Dict[str, Any]]:
    """One fetched row as a `documents` row, or None if it is not storable.

    The three fetchers return three shapes: releases carry product/version/
    notes, community and CVE rows carry title/subreddit/score. Columns are the
    union, the original row is kept verbatim in `payload`, and nothing is
    dropped -- a caller that needs a field the columns do not have reads the
    payload back.
    """
    if not isinstance(row, dict) or _is_placeholder(row):
        return None
    key = doc_key(row)
    if not key:
        return None
    return {
        "doc_key": key,
        "pool": pool,
        "kind": _kind(pool, row),
        "product": str(row.get("product") or "").strip(),
        "version": str(row.get("version") or "").strip(),
        "published": str(row.get("date") or "").strip(),
        "title": str(row.get("title") or "").strip(),
        "notes": str(row.get("notes") or "").strip(),
        "url": str(row.get("url") or "").strip(),
        "is_cve": 1 if row.get("is_cve") else 0,
        "payload": json.dumps(row, default=str, sort_keys=True),
    }


@dataclass(frozen=True)
class RunSummary:
    """One answered question, as the history pane needs it."""

    run_id: int
    ts: str
    query: str
    intent: str
    answer: str
    n_documents: int
    offline: bool


def _synchronized(method):
    """Serialise one Store method against the others on the same connection.

    `check_same_thread=False` only silences sqlite's thread check; it does not
    make a connection safe to use from two threads at once. Streamlit runs each
    script execution on its own thread and `st.cache_resource` hands every
    session the *same* Store, so two overlapping reruns share one connection.
    Without this, concurrent work on it raises -- "cannot start a transaction
    within a transaction" from interleaved `with self.conn:` blocks, or
    "Recursive use of cursors not allowed" -- and the demo renders an empty
    page, because the exception escapes before anything is drawn.

    WAL lets separate *connections* overlap; this is the other half, for the
    one connection shared between threads.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class Store:
    """The SQLite store. One instance per process, shared across threads."""

    def __init__(self, conn: sqlite3.Connection, fts: bool):
        self.conn = conn
        self.fts = fts
        # Reentrant: record_run calls record_documents, and a plain Lock would
        # deadlock on the nested call.
        self._lock = threading.RLock()

    # ── lifecycle ────────────────────────────────────────────────────────

    @_synchronized
    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── writes ───────────────────────────────────────────────────────────

    @_synchronized
    def record_documents(self, pool: str, rows: Iterable[Dict]) -> int:
        """Upsert fetched rows; returns how many were storable.

        `first_seen` survives an update and `last_seen` moves, so the store can
        answer "when did this document first appear" -- which is the question a
        monitoring system exists to answer -- without a second table.
        """
        now = _now()
        prepared = [r for r in (_normalise(pool, row) for row in rows) if r]
        if not prepared:
            return 0
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO documents (doc_key, pool, kind, product, version,
                                       published, title, notes, url, is_cve,
                                       payload, first_seen, last_seen)
                VALUES (:doc_key, :pool, :kind, :product, :version, :published,
                        :title, :notes, :url, :is_cve, :payload, :now, :now)
                ON CONFLICT (doc_key) DO UPDATE SET
                    pool      = excluded.pool,
                    kind      = excluded.kind,
                    product   = excluded.product,
                    version   = excluded.version,
                    published = excluded.published,
                    title     = excluded.title,
                    notes     = excluded.notes,
                    url       = excluded.url,
                    is_cve    = excluded.is_cve,
                    payload   = excluded.payload,
                    last_seen = excluded.last_seen
                """,
                [dict(r, now=now) for r in prepared],
            )
        return len(prepared)

    @_synchronized
    def record_run(self, results: Dict, answer: str = "",
                   offline: bool = False) -> Optional[int]:
        """Log one `run_pipeline` result and the documents it retrieved.

        Takes the pipeline's own result dict rather than a bespoke argument
        list: the dict is what the app already has, and a logger that needs the
        caller to restate its state is a logger that drifts from it.

        Returns the run id, or None if the write failed -- a store that cannot
        log must not take the answer down with it.
        """
        temporal = results.get("temporal")
        intent = results.get("intent")
        try:
            with self.conn:
                cur = self.conn.execute(
                    """
                    INSERT INTO runs (ts, original_query, grounded_query,
                                      rewritten_query, intent, intent_confident,
                                      vendors, phrasings, answer, evaluation,
                                      timing, offline)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        _now(),
                        str(results.get("original_query") or ""),
                        str(results.get("grounded_query")
                            or getattr(temporal, "query", "") or ""),
                        str(results.get("rewritten_query") or ""),
                        str(getattr(intent, "label", intent) or ""),
                        1 if getattr(intent, "confident", False) else 0,
                        json.dumps(results.get("vendors") or [], default=str),
                        json.dumps(results.get("fetch_phrasings") or []),
                        answer or str(results.get("answer") or ""),
                        json.dumps(results.get("evaluation") or {}, default=str),
                        json.dumps(results.get("timing") or {}, default=str),
                        1 if offline else 0,
                    ),
                )
                run_id = int(cur.lastrowid)

                cited = {str(k) for k in (results.get("cited_keys") or [])}
                links = []
                for pool, field in (("community", "community"),
                                    ("release", "releases"),
                                    ("cve", "cve")):
                    rows = results.get(field) or []
                    self.record_documents(pool, rows)
                    for rank, row in enumerate(rows, start=1):
                        prepared = _normalise(pool, row)
                        if prepared:
                            links.append((run_id, prepared["doc_key"], pool, rank,
                                          1 if prepared["doc_key"] in cited else 0))
                if links:
                    self.conn.executemany(
                        """
                        INSERT OR REPLACE INTO run_documents
                            (run_id, doc_key, pool, rank, cited)
                        VALUES (?,?,?,?,?)
                        """,
                        links,
                    )
            return run_id
        except sqlite3.Error:
            return None

    # ── reads ────────────────────────────────────────────────────────────

    @_synchronized
    def search(self, query: str, pool: Optional[str] = None,
               limit: int = 5, max_age_days: Optional[int] = None) -> List[Dict]:
        """Stored documents matching `query`, best first.

        This is the offline path: when a fetcher cannot reach the endpoint,
        the honest fallback is the documents already retrieved for questions
        like this one, not an empty answer and not a placeholder. Returns the
        original fetched rows, so a caller cannot tell a replayed document from
        a fresh one by its shape -- only by `last_seen`.
        """
        terms = [t for t in _tokens(query) if t]
        if not terms:
            return []
        params: List[Any] = []
        if self.fts:
            # Each term is quoted, because FTS5 reads bare punctuation as
            # syntax: "7.1.0" is three terms and a syntax error, "node-red" is
            # a NOT. Both are ordinary words in this corpus, and an unquoted
            # query raises rather than matching -- which would turn the offline
            # fallback into an empty result exactly when it is needed.
            #
            # OR rather than AND: a question names a product plus a lot of
            # question words, and requiring every token match finds nothing.
            match = " OR ".join('"%s"' % t.replace('"', '""') for t in terms)
            sql = ("SELECT d.payload, d.pool, d.last_seen FROM documents_fts f "
                   "JOIN documents d ON d.rowid = f.rowid "
                   "WHERE documents_fts MATCH ?")
            params.append(match)
        else:
            clauses = " OR ".join(
                ["(d.product LIKE ? OR d.title LIKE ? OR d.notes LIKE ?)"] * len(terms))
            sql = f"SELECT d.payload, d.pool, d.last_seen FROM documents d WHERE ({clauses})"
            for t in terms:
                params.extend([f"%{t}%"] * 3)
        if pool:
            sql += " AND d.pool = ?"
            params.append(pool)
        if max_age_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            sql += " AND d.last_seen >= ?"
            params.append(cutoff.isoformat(timespec="seconds"))
        sql += (" ORDER BY rank" if self.fts else " ORDER BY d.last_seen DESC")
        sql += " LIMIT ?"
        params.append(int(limit))

        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.Error:
            return []
        return [_payload(r) for r in rows]

    @_synchronized
    def recent_runs(self, limit: int = 20) -> List[RunSummary]:
        """The history pane's rows, newest first."""
        rows = self.conn.execute(
            """
            SELECT r.run_id, r.ts, r.original_query, r.intent, r.answer,
                   r.offline, COUNT(rd.doc_key) AS n
            FROM runs r
            LEFT JOIN run_documents rd ON rd.run_id = r.run_id
            GROUP BY r.run_id
            ORDER BY r.ts DESC, r.run_id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [RunSummary(run_id=r["run_id"], ts=r["ts"], query=r["original_query"],
                           intent=r["intent"], answer=r["answer"],
                           n_documents=r["n"], offline=bool(r["offline"]))
                for r in rows]

    @_synchronized
    def run_documents(self, run_id: int) -> List[Dict]:
        """What one run retrieved, in the order it retrieved it."""
        rows = self.conn.execute(
            """
            SELECT d.payload, rd.pool, rd.rank, rd.cited, d.last_seen
            FROM run_documents rd JOIN documents d ON d.doc_key = rd.doc_key
            WHERE rd.run_id = ?
            ORDER BY rd.pool, rd.rank
            """,
            (int(run_id),),
        ).fetchall()
        out = []
        for r in rows:
            doc = _payload(r)
            doc["_rank"] = r["rank"]
            doc["_cited"] = bool(r["cited"])
            out.append(doc)
        return out

    @_synchronized
    def stats(self) -> Dict[str, Any]:
        """Counts for the sidebar and for `scripts/` to assert against."""
        docs = self.conn.execute(
            "SELECT pool, COUNT(*) AS n FROM documents GROUP BY pool").fetchall()
        runs = self.conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()
        oldest = self.conn.execute(
            "SELECT MIN(first_seen) AS t FROM documents").fetchone()
        return {
            "documents": {r["pool"]: r["n"] for r in docs},
            "documents_total": sum(r["n"] for r in docs),
            "runs": runs["n"],
            "since": oldest["t"],
            "fts": self.fts,
        }


def _tokens(query: str) -> List[str]:
    """Query words worth searching on.

    Alphanumeric runs of 3+ characters, lowercased. Deliberately not the
    stopword list in `fetch_union`: that one shapes what is *fetched* from a
    keyword endpoint, and dropping "security" there is right because the
    endpoint matches product names. Here the corpus is the stored text, where
    "security" is a real discriminator.
    """
    import re
    seen, out = set(), []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+#_-]*", query.lower()):
        w = w.strip(".-_")
        if len(w) >= 3 and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _payload(row: sqlite3.Row) -> Dict:
    try:
        doc = json.loads(row["payload"])
    except (ValueError, TypeError):
        doc = {}
    doc.setdefault("pool", row["pool"])
    doc["_last_seen"] = row["last_seen"]
    return doc


def open_store(path: Optional[str] = None) -> Store:
    """Open (creating if needed) the store at `path`.

    WAL, because Streamlit reruns the script on every widget interaction and
    two overlapping reruns must not lock each other out of the file. `:memory:`
    is passed through unchanged, which is what the tests use.
    """
    target = path or DEFAULT_PATH
    if target != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Wait for a writer instead of raising "database is locked" immediately.
    conn.execute("PRAGMA busy_timeout = 5000")
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(_SCHEMA)

    fts = True
    try:
        conn.executescript(_SCHEMA_FTS)
    except sqlite3.OperationalError:
        # sqlite built without FTS5. `search` falls back to LIKE; everything
        # else is unaffected, so this is a slower store and not a broken one.
        fts = False
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return Store(conn, fts)


def caching_fetch(store: Optional[Store], pool: str,
                  fetch_fn: Callable[..., Sequence[Dict]],
                  outage: Optional[Callable[[], int]] = None,
                  max_age_days: Optional[int] = FALLBACK_MAX_AGE_DAYS,
                  ) -> Callable[..., List[Dict]]:
    """Wrap one agent's fetch so results are stored, and outages are survivable.

    Drops straight into `union_fetch`, which takes the fetch function as an
    argument for exactly this reason. Behaviour:

      * live rows come back unchanged and are written to `documents`;
      * an outage -- the placeholder row, an empty result, or a raised
        exception -- falls back to `store.search` over what previous runs
        retrieved for questions like this one;
      * with no store, or with nothing stored yet, the original result is
        returned untouched, placeholder and all. The fallback may not invent a
        better outcome than the pipeline had before it existed.

    `outage` is a counter of recorded outages (the app's fetch-error log). Given
    one, an empty result is an outage only if the counter moved during the call:
    "nothing new this week" is a live answer, and replacing it with stored rows
    is how September advisories answered November questions. `max_age_days`
    bounds how old a stored row may be to stand in for a live one.
    """
    def fetch(query: str, limit: int = 5, **kwargs) -> List[Dict]:
        rows: List[Dict] = []
        before = outage() if outage else 0
        failed = False
        try:
            rows = list(fetch_fn(query, limit=limit, **kwargs))
        except Exception:
            rows, failed = [], True
        live = [r for r in rows if isinstance(r, dict) and not _is_placeholder(r)]
        if outage and not failed and not rows and outage() == before:
            return rows

        if store is None:
            return rows
        if live:
            try:
                store.record_documents(pool, live)
            except sqlite3.Error:
                pass
            return live

        cached = store.search(query, pool=pool, limit=limit,
                              max_age_days=max_age_days)
        return cached if cached else rows

    return fetch
