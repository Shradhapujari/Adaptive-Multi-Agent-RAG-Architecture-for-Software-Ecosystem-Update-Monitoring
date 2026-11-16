"""
Tests for the SQLite store.

The store exists for two claims and both are tested here: a document fetched
under several phrasings is stored once, and a fetch that fails is answered from
what earlier runs retrieved rather than with the outage placeholder.

Offline: every test opens `:memory:` and injects its own fetch function, so
nothing here touches the filesystem or an API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import store as store_mod  # noqa: E402
from fetch_union import union_fetch  # noqa: E402

RELEASE = {"product": "linux", "version": "7.1.0", "date": "2026-08-30",
           "notes": "kernel release", "channel": "stable",
           "url": "https://github.com/torvalds/linux/releases/tag/v7.1.0",
           "security": [], "breaking": [], "is_cve": False}

ADVISORY = {"product": "Linux", "version": "25.642087.0", "date": "2026-08-29",
            "notes": "affected versions", "channel": "", "is_cve": True,
            "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-1234",
            "security": ["critical"], "breaking": []}

POST = {"title": "Anyone else hating the new Chrome UI?", "subreddit": "chrome",
        "url": "https://reddit.com/r/chrome/abc", "score": 42,
        "sentiment": "Neutral", "date": "2026-08-31",
        "is_cve": False, "is_update": True}

OUTAGE = {"title": "API unavailable: timed out", "subreddit": "", "url": "",
          "score": 0, "sentiment": "Neutral", "date": "", "is_cve": False,
          "is_update": False}


@pytest.fixture
def st():
    s = store_mod.open_store(":memory:")
    yield s
    s.close()


def test_schema_and_empty_stats(st):
    stats = st.stats()
    assert stats["runs"] == 0
    assert stats["documents_total"] == 0


def test_documents_dedupe_on_doc_key(st):
    # The same release arriving under three phrasings is one row, keyed the way
    # union_fetch dedupes it -- otherwise the store counts retrieval effort
    # rather than documents.
    assert st.record_documents("release", [RELEASE, RELEASE, RELEASE]) == 3
    assert st.stats()["documents"]["release"] == 1


def test_first_seen_survives_re_fetch(st):
    st.record_documents("release", [RELEASE])
    first = st.conn.execute("SELECT first_seen, last_seen FROM documents").fetchone()
    st.record_documents("release", [dict(RELEASE, notes="updated notes")])
    second = st.conn.execute(
        "SELECT first_seen, last_seen, notes FROM documents").fetchone()
    assert second["first_seen"] == first["first_seen"]
    assert second["notes"] == "updated notes"


def test_outage_placeholder_is_not_stored(st):
    assert st.record_documents("community", [OUTAGE]) == 0
    assert st.stats()["documents_total"] == 0


def test_kind_separates_release_from_advisory(st):
    st.record_documents("release", [RELEASE, ADVISORY])
    kinds = dict(st.conn.execute(
        "SELECT version, kind FROM documents").fetchall())
    assert kinds["7.1.0"] == "release"
    assert kinds["25.642087.0"] == "advisory"


def test_search_finds_stored_document(st):
    st.record_documents("release", [RELEASE])
    st.record_documents("community", [POST])
    hits = st.search("latest linux kernel version", pool="release")
    assert [h["version"] for h in hits] == ["7.1.0"]
    assert hits[0]["_last_seen"]


def test_search_respects_pool(st):
    st.record_documents("community", [POST])
    assert st.search("chrome", pool="release") == []
    assert len(st.search("chrome", pool="community")) == 1


def test_search_returns_the_original_row_shape(st):
    st.record_documents("community", [POST])
    hit = st.search("chrome UI", pool="community")[0]
    for k, v in POST.items():
        assert hit[k] == v


def test_record_run_links_documents_with_rank(st):
    results = {
        "original_query": "Any critical Linux updates today?",
        "grounded_query": "Any critical Linux updates on Aug 31, 2026?",
        "rewritten_query": "critical Linux kernel updates",
        "fetch_phrasings": ["critical Linux kernel updates", "linux"],
        "community": [POST],
        "releases": [RELEASE, ADVISORY],
        "cve": [],
        "evaluation": {"quality": 0.2},
        "timing": {"releases": 1.1},
        "cited_keys": [RELEASE["url"]],
    }
    run_id = st.record_run(results, answer="Linux 7.1.0 shipped 2026-08-30.")
    assert run_id is not None

    docs = st.run_documents(run_id)
    assert len(docs) == 3
    ranks = [(d["pool"], d["_rank"]) for d in docs if d.get("pool") == "release"]
    assert sorted(ranks) == [("release", 1), ("release", 2)]
    assert [d["_cited"] for d in docs].count(True) == 1

    summary = st.recent_runs()[0]
    assert summary.run_id == run_id
    assert summary.n_documents == 3
    assert summary.intent == ""          # no intent supplied by this caller


def test_record_run_carries_intent_object(st):
    from intent import classify
    intent = classify("Any critical CVEs in Chrome?")
    run_id = st.record_run({"original_query": "Any critical CVEs in Chrome?",
                            "intent": intent})
    row = st.conn.execute("SELECT intent, intent_confident FROM runs "
                          "WHERE run_id = ?", (run_id,)).fetchone()
    assert row["intent"] == "security"
    assert row["intent_confident"] == 1


def test_caching_fetch_stores_live_rows(st):
    calls = []

    def live(query, limit=5):
        calls.append(query)
        return [RELEASE]

    fetch = store_mod.caching_fetch(st, "release", live)
    assert fetch("linux", limit=5) == [RELEASE]
    assert st.stats()["documents"]["release"] == 1
    assert calls == ["linux"]


def test_caching_fetch_serves_cache_when_endpoint_is_down(st):
    st.record_documents("release", [RELEASE])

    def down(query, limit=5):
        raise RuntimeError("connection refused")

    fetch = store_mod.caching_fetch(st, "release", down)
    served = fetch("latest linux version", limit=5)
    assert [d["version"] for d in served] == ["7.1.0"]


def test_caching_fetch_serves_cache_on_placeholder_row(st):
    st.record_documents("community", [POST])
    fetch = store_mod.caching_fetch(st, "community", lambda q, limit=5: [OUTAGE])
    served = fetch("chrome UI complaints", limit=5)
    assert [d["title"] for d in served] == [POST["title"]]


def test_caching_fetch_returns_placeholder_when_nothing_cached(st):
    # With an empty store the fallback must not improve on the old behaviour by
    # inventing an answer: the caller gets exactly what the fetcher returned.
    fetch = store_mod.caching_fetch(st, "community", lambda q, limit=5: [OUTAGE])
    assert fetch("anything", limit=5) == [OUTAGE]


def test_caching_fetch_without_store_is_a_passthrough():
    fetch = store_mod.caching_fetch(None, "release", lambda q, limit=5: [RELEASE])
    assert fetch("linux", limit=5) == [RELEASE]


def test_caching_fetch_composes_with_union_fetch(st):
    seen = []

    def live(query, limit=5):
        seen.append(query)
        return [RELEASE] if query == "linux" else [POST]

    fetch = store_mod.caching_fetch(st, "release", live)
    out = union_fetch(fetch, ["critical linux updates", "linux"], limit=5)
    # union_fetch dedupes across phrasings; the store agrees on the key.
    assert len(out) == 2
    assert seen == ["critical linux updates", "linux"]
    assert st.stats()["documents"]["release"] == 2


def test_file_backed_store_round_trips(tmp_path):
    path = str(tmp_path / "marag.db")
    with store_mod.open_store(path) as s:
        s.record_documents("release", [RELEASE])
    with store_mod.open_store(path) as s:
        assert s.stats()["documents_total"] == 1
        assert s.conn.execute("PRAGMA user_version").fetchone()[0] == \
            store_mod.SCHEMA_VERSION


@pytest.mark.parametrize("query", [
    "linux 7.1.0",          # dots are FTS5 term separators
    "node-red release",     # a bare hyphen is FTS5's NOT
    'chrome "quoted" ui',   # an unbalanced quote in the user's own question
    "c++ compiler",
    "what about (this)?",
])
def test_search_survives_fts_punctuation(st, query):
    # An outage is the moment search runs, so a query that raises instead of
    # matching costs the whole fallback. Every one of these is a question a
    # user can type.
    st.record_documents("release", [RELEASE])
    assert isinstance(st.search(query), list)


def test_search_finds_a_dotted_version_string(st):
    st.record_documents("release", [RELEASE])
    assert [h["version"] for h in st.search("linux 7.1.0")] == ["7.1.0"]


def test_an_empty_live_feed_is_not_an_outage(st):
    # 2026-11-15: the CVE pool answered November questions with September
    # advisories because "no CVEs this week" came back empty and empty read as
    # an outage. With an outage signal, empty-and-healthy stays empty.
    st.record_documents("cve", [ADVISORY])
    log = []
    fetch = store_mod.caching_fetch(st, "cve", lambda q, limit=5: [],
                                    outage=lambda: len(log))
    assert fetch("linux", limit=5) == []


def test_a_recorded_outage_still_falls_back(st):
    st.record_documents("cve", [ADVISORY])
    log = []

    def down(q, limit=5):
        log.append("timeout")
        return []

    fetch = store_mod.caching_fetch(st, "cve", down, outage=lambda: len(log))
    assert [d["version"] for d in fetch("linux", limit=5)] == ["25.642087.0"]


def test_the_fallback_does_not_serve_stale_documents(st):
    st.record_documents("release", [RELEASE])
    st.conn.execute("UPDATE documents SET last_seen = '2026-09-01T00:00:00+00:00'")
    assert st.search("linux", pool="release", max_age_days=14) == []
    assert len(st.search("linux", pool="release")) == 1   # explicit store reads stay unbounded
