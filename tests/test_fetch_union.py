"""
Tests for the two-phrasing union fetch.

The behaviour under test is a regression fix with a measured cause: grounding
"today" into the query and fetching *only* that phrasing took the release
endpoint from 5 results to 0, because it matches `q` against note text and a
note does not contain "Aug 31, 2026". Recall has to come from the plain
phrasing; the date is for ranking.

Offline: the fetch function is injected, so nothing here calls an API.
"""

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fetch_union import doc_key, union_fetch  # noqa: E402
from temporal import resolve_temporal  # noqa: E402

NOW = date(2026, 8, 31)


def _fake(by_phrase):
    """A fetch_fn that returns canned items per phrasing and records calls."""
    calls = []

    def fetch(phrase, limit=5):
        calls.append((phrase, limit))
        return list(by_phrase.get(phrase, []))[:limit]

    fetch.calls = calls
    return fetch


def test_plain_phrasing_supplies_recall_the_dated_one_loses():
    tr = resolve_temporal("Any critical Linux updates today?", now=NOW)
    plain, dated = tr.fetch_phrasings
    fetch = _fake({plain: [{"url": "u1", "date": "2026-08-31"},
                           {"url": "u2", "date": "2026-08-20"}],
                   dated: []})
    out = union_fetch(fetch, tr.fetch_phrasings, limit=5, temporal=tr)
    assert [d["url"] for d in out] == ["u1", "u2"]
    assert [c[0] for c in fetch.calls] == [plain, dated]


def test_results_are_deduped_across_phrasings():
    fetch = _fake({"a": [{"url": "u1"}, {"url": "u2"}], "b": [{"url": "u2"}, {"url": "u3"}]})
    out = union_fetch(fetch, ["a", "b"], limit=10)
    assert [d["url"] for d in out] == ["u1", "u2", "u3"]


def test_in_window_items_rank_first_but_others_are_kept():
    tr = resolve_temporal("updates today", now=NOW)
    fetch = _fake({"a": [{"url": "old", "date": "2026-01-02"},
                         {"url": "hit", "date": "2026-08-31"}]})
    out = union_fetch(fetch, ["a"], limit=5, temporal=tr)
    assert [d["url"] for d in out] == ["hit", "old"]
    assert len(out) == 2  # ranked, not filtered


def test_undated_items_are_not_treated_as_misses_ahead_of_dated_misses():
    # None (cannot tell) and False (outside) both sort after a hit, and among
    # themselves the original order is preserved — sort is stable.
    tr = resolve_temporal("updates today", now=NOW)
    fetch = _fake({"a": [{"url": "undated"}, {"url": "outside", "date": "2020-01-01"},
                         {"url": "hit", "date": "2026-08-31"}]})
    out = union_fetch(fetch, ["a"], limit=5, temporal=tr)
    assert [d["url"] for d in out] == ["hit", "undated", "outside"]


def test_limit_caps_the_union_not_each_phrasing():
    fetch = _fake({"a": [{"url": f"a{i}"} for i in range(5)],
                   "b": [{"url": f"b{i}"} for i in range(5)]})
    out = union_fetch(fetch, ["a", "b"], limit=5)
    assert len(out) == 5
    assert [c[1] for c in fetch.calls] == [5, 5]


def test_no_window_leaves_order_untouched():
    tr = resolve_temporal("Latest Django release notes", now=NOW)
    fetch = _fake({"a": [{"url": "old", "date": "2020-01-01"},
                         {"url": "new", "date": "2026-08-31"}]})
    out = union_fetch(fetch, ["a"], limit=5, temporal=tr)
    assert [d["url"] for d in out] == ["old", "new"]


def test_empty_and_blank_phrasings_are_skipped():
    fetch = _fake({"a": [{"url": "u1"}]})
    out = union_fetch(fetch, ["", None, "a"], limit=5)
    assert [d["url"] for d in out] == ["u1"]
    assert [c[0] for c in fetch.calls] == ["a"]


@pytest.mark.parametrize("item,expected", [
    ({"url": "https://x/1", "title": "t"}, "https://x/1"),
    ({"url": "", "product": "Linux", "version": "6.18.21"}, "linux|6.18.21"),
    ({"title": "Only A Title"}, "only a title"),
])
def test_doc_key_falls_back_through_url_version_title(item, expected):
    assert doc_key(item) == expected


def test_the_same_release_under_two_capitalisations_is_one_document():
    # Measured against /api/v/ on 2026-09-10: fetching "chrome" and "Chrome"
    # for one question returns Chrome 152.0.7977 with `product` echoing each
    # phrasing, and the release has no url to dedupe on. Both reached the
    # answer as separate cited sources.
    fetch = _fake({
        "chrome": [{"url": "", "product": "chrome", "version": "152.0.7977"}],
        "Chrome": [{"url": "", "product": "Chrome", "version": "152.0.7977"}],
    })
    out = union_fetch(fetch, ["chrome", "Chrome"], limit=5)
    assert len(out) == 1, out

    # A different version is still a different document.
    fetch2 = _fake({
        "chrome": [{"url": "", "product": "chrome", "version": "152.0.7977"}],
        "Chrome": [{"url": "", "product": "Chrome", "version": "155.0.8049"}],
    })
    assert len(union_fetch(fetch2, ["chrome", "Chrome"], limit=5)) == 2


def test_unchanged_query_fetches_one_phrasing():
    tr = resolve_temporal("Any security vulnerabilities in Python?", now=NOW)
    assert tr.fetch_phrasings == ["Any security vulnerabilities in Python?"]


# ── product terms ────────────────────────────────────────────────────────
# The release endpoint matches product names, not sentences: measured against
# the live API on 2026-08-31, "Linux" returned 606 versions and "critical Linux
# updates" returned 0. Without a product-term phrasing the release agent
# answers nothing at all for a normally-worded question.

@pytest.mark.parametrize("query,expected", [
    ("Any critical Linux updates today?", ["Linux"]),
    ("What bugs were fixed in Chrome recently?", ["Chrome"]),
    ("Latest Django release notes", ["Django"]),
    ("Any security vulnerabilities in Python?", ["Python"]),
    ("MacOS updates with negative community reaction", ["MacOS"]),
    ("tell me about kubernetes", ["kubernetes"]),
])
def test_product_terms_finds_the_product(query, expected):
    from fetch_union import product_terms
    assert product_terms(query) == expected


def test_product_terms_skips_generic_words_and_the_leading_capital():
    from fetch_union import product_terms
    # "Any" and "Security" are sentence words, not products; the first word is
    # capitalised only because it starts the sentence.
    assert product_terms("Any critical security updates?") == []


def test_product_terms_are_deduped_and_capped():
    from fetch_union import product_terms
    q = "Linux linux Chrome Django Python"
    assert product_terms(q, limit=2) == ["Linux", "Chrome"]


def test_windowed_fetch_asks_for_more_than_it_shows():
    # Ranking the first 5 by date cannot surface a match that was never
    # fetched, so the fetch is widened when a window exists.
    tr = resolve_temporal("updates today", now=NOW)
    fetch = _fake({"a": []})
    union_fetch(fetch, ["a"], limit=5, temporal=tr)
    assert fetch.calls[0][1] == 25

    plain = _fake({"a": []})
    union_fetch(plain, ["a"], limit=5)
    assert plain.calls[0][1] == 5
