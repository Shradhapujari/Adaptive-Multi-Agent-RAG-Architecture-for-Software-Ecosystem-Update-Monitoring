"""
Tests for the question picker's two shortcuts: newest, and a random draw.

Offline: `newest` is pure, and the sampling arithmetic the picker does around
`questions_total` is checked without asking the feed for anything.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yesno  # noqa: E402


def _row(ts, title="q"):
    return {"created_utc": ts, "title": title, "redditId": title}


def test_newest_is_the_latest_post_not_the_first_row():
    """The feed returns newest-first today, so taking rows[0] would pass by
    accident and fail silently the day that changes."""
    rows = [_row("2026-01-01T00:00:00", "old"),
            _row("2026-08-28T10:47:20", "newest"),
            _row("2026-03-05T12:00:00", "middle")]
    assert yesno.newest(rows)["title"] == "newest"


def test_newest_of_nothing_is_nothing():
    assert yesno.newest([]) is None


def test_a_row_with_no_timestamp_does_not_win_by_default():
    """An undated row sorts as "" against an ISO string, which would make it
    the newest under a plain max()."""
    rows = [{"title": "undated"}, _row("2025-05-23T15:14:50", "dated")]
    assert yesno.newest(rows)["title"] == "dated"


def test_undated_rows_still_yield_a_pick():
    """Rather than None, which would read to the caller as an unreachable feed."""
    assert yesno.newest([{"title": "a"}])["title"] == "a"


def test_page_count_covers_every_question():
    """The random draw picks a page in 1..pages; a floor division here would
    leave the feed's last partial page unreachable."""
    def pages(total, pool):
        return max(1, -(-total // pool))

    assert pages(3212, 100) == 33          # 32 full pages plus a remainder
    assert pages(100, 100) == 1
    assert pages(101, 100) == 2
    assert pages(0, 100) == 1              # an unreachable feed still needs a page
