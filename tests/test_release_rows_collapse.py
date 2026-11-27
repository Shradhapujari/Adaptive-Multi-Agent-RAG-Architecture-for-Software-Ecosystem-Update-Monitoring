"""The release panel shows one row per release, not one per kernel commit."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_1  # noqa: E402

TAG = "https://github.com/torvalds/linux/archive/refs/tags/v7.3.tar.gz"


def _row(version, url, notes="n"):
    return {"versionProductName": "linux", "versionNumber": version,
            "versionUrl": url, "versionReleaseNotes": notes}


def test_commit_rows_are_dropped_and_a_tag_is_listed_once():
    rows = [_row("7.3.0", TAG, "a"), _row("7.41.0", "https://x/commit/1cb6"),
            _row("7.3.0", TAG, "b"), _row("7.41.0", "https://x/commit/ae36")]
    out = app_1._one_row_per_release(rows)
    assert [r["versionNumber"] for r in out] == ["7.3.0"]


def test_a_version_is_listed_once_whatever_it_links():
    rows = [_row("7.2.0", "https://x/tags/v7.2.tar.gz"), _row("7.2.0", "https://x/linux")]
    out = app_1._one_row_per_release(rows)
    assert [r["versionUrl"] for r in out] == ["https://x/tags/v7.2.tar.gz"]


def test_an_all_commit_feed_is_not_emptied():
    rows = [_row("7.41.0", "https://x/commit/1"), _row("7.41.0", "https://x/commit/2")]
    assert len(app_1._one_row_per_release(rows)) == 1


def _app_row(version, url, **kw):
    # The shape the terminal's rows arrive in, via app_1._release_rows.
    return {"product": "linux", "version": version, "url": url, "notes": "n", **kw}


def test_app_shaped_commit_rows_are_dropped_too():
    # Sweep 2026-11-25, "Did the latest Fedora 44 update delete your kernel and
    # grub?": the terminal's rows bypassed this filter and the answer cited
    # "linux v7.41.0" and "linux v7.44.0" -- the feed's spelling of the
    # 7.4-rc1 and 7.4-rc4 merge commits.
    rows = [_app_row("7.41.0", "https://github.com/torvalds/linux/commit/d40c"),
            _app_row("7.3.0", TAG),
            _app_row("7.44.0", "https://github.com/torvalds/linux/commit/eef2")]
    assert [r["version"] for r in app_1._one_row_per_release(rows)] == ["7.3.0"]


def test_advisories_pass_through_untouched():
    cve = lambda n: {"product": "Linux", "version": "6.1.0", "is_cve": True,
                     "url": f"https://nvd.nist.gov/vuln/detail/CVE-2026-{n}"}
    rows = [cve(1), _app_row("7.44.0", "https://x/commit/1"), _app_row("7.3.0", TAG), cve(2)]
    out = app_1._one_row_per_release(rows)
    assert [r["url"][-6:] for r in out] == ["2026-1", TAG[-6:], "2026-2"]
