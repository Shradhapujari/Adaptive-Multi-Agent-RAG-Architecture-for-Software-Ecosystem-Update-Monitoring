"""A bare "CVE" asks about advisories, not the newest release.

"What is the latest Linux CVE?" routed as a version lookup ("latest") and the
console headlined linux v7.3.0 (user report, 2026-11-23). Only a full CVE id
counted as a CVE cue.
"""
import pytest

from graph import asks, route_query


@pytest.mark.parametrize("q", [
    "What is the latest Linux CVE?",
    "What is the latest CVE for Linux?",
    "most recent Firefox CVE",
    "Any new CVEs for nginx?",
    "What CVEs affect Linux 6.8?",
    "What's the newest Chrome security advisory?",
    "Latest Microsoft security bulletin?",
    "Latest Chrome zero-day?",
    "What's the latest 0-day in Chrome?",
    "Did Microsoft fix the latest zero-day?",
    "Latest npm advisory?",
    "Latest patch Tuesday?",
])
def test_cve_word_is_a_cve_question(q):
    assert asks(q) == "cve"
    assert route_query(q)[0] == "full"


@pytest.mark.parametrize("q", [
    "What is the latest Linux version?",
    "Latest Chrome version?",
    "What is the most recent Python release?",
])
def test_plain_latest_is_still_a_version_question(q):
    assert asks(q) == "version"


@pytest.mark.parametrize("q", [
    "Latest critical bugs in PostgreSQL?",
    "Latest breaking changes in React?",
    "What are the newest known issues in Windows 11?",
])
def test_latest_bugs_or_changes_is_not_a_version_lookup(q):
    assert asks(q) != "version"
    assert route_query(q)[0] == "full"


def test_newest_advisory_line_names_the_newest_dated_cve():
    from answer_agent import Evidence, newest_advisory_line
    ev = [
        Evidence(label="Release Notes - linux v7.3.0", kind="release", title="linux v7.3.0",
                 date="2026-11-22"),
        Evidence(label="Security Advisory - CVE-2026-1111 (affects linux 7.2.0)", kind="advisory",
                 title="CVE-2026-1111", detail="Old flaw.", date="2026-09-25"),
        Evidence(label="Security Advisory - CVE-2026-2222 (affects linux 7.2.0)", kind="advisory",
                 title="CVE-2026-2222", detail="Use-after-free in netfilter.", date="2026-11-20"),
        Evidence(label="Security Advisory - undated", kind="advisory", title="no id", date="2026-12-01"),
    ]
    line = newest_advisory_line(ev)
    assert line.startswith("Newest: CVE-2026-2222 (2026-11-20)")
    assert "netfilter" in line
    assert newest_advisory_line(ev[:1]) == ""
