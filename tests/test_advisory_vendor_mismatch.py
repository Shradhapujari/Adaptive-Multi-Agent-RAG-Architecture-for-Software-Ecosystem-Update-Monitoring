"""An advisory is about the product its text names, not the one you searched for.

The feed labels every row it returns with the query's product. Checked against
/api/v/?q=teams on 2026-09-24: 30 rows, all tagged `teams`, 24 of them CVE
records for other software that merely contains the word -- Scoold, UVdesk,
vikunja, PraisonAI. One reached a demo answer, ranked 2nd of 42 and cited as a
VERIFIED Targeted Vendor Release Note.

`filter_by_vendor` cannot catch this: the tag really does say "teams". The
strings below are taken from the store, because a rule about how CVE prose is
written should be tested against CVE prose rather than against sentences
invented to satisfy it.

Offline: pure text, no fetch.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vendor import advisory_names_vendor  # noqa: E402


# (description, tagged vendor, may it be cited as that vendor's record)
REAL_ROWS = [
    # Mislabelled: the word appears, the product is something else.
    ("Scoold is a Q&A and a knowledge sharing platform for teams. Prior to "
     "1.69.0, authenticated users who are not members", "teams", False),
    ("UVdesk core-framework before 1.1.7 contains an authorization bypass",
     "teams", False),
    ("vikunja before 2.6.0 fails to validate team access when attaching",
     "teams", False),
    ("PraisonAI is a multi-agent teams system. Prior to 0.1.6, praisonai_p",
     "teams", False),
    ("PraisonAI is a multi-agent teams system. From 1.6.0 until 1.7.2, AgentOS",
     "teams", False),
    ("PraisonAI is a multi-agent teams system. Prior to praisonaiagents 1.6.59,"
     " MentionAgent", "teams", False),
    ("Notepad++ is a free and open-source source code editor", "windows", False),
    ("Nix is a package manager for Linux and other Unix systems. Prior to "
     "2.35.0", "linux", False),
    ("Reflected XSS in Netron versions <=9.1.2 on desktop", "chrome", False),
    ("Tencent BrowserSkill through 0.3.0 contains an authentication bypass",
     "chrome", False),
    # Genuine: these name the product in the version marker's own clause.
    ("Information leak in Extensions in Google Chrome prior to 1.2.3",
     "chrome", True),
    ("Out of bounds read in V8 in Google Chrome prior to 9.9", "chrome", True),
    ("In the Linux kernel, the following vulnerability has been resolved "
     "before 6.1", "linux", True),
]


@pytest.mark.parametrize("text,claimed,citable", REAL_ROWS)
def test_real_advisories_are_judged_by_their_own_text(text, claimed, citable):
    assert advisory_names_vendor({"notes": text}, claimed) is citable


def test_the_sentence_boundary_is_what_separates_the_hard_pair():
    """Both defeat the obvious rules. "…platform for teams. Prior to 1.69.0"
    puts the word before the marker but in the previous sentence, describing
    who the product is for; a real Chrome advisory names the product late but
    in the marker's own clause. A "first N characters" rule drops the second,
    an "N characters before the marker" rule keeps the first."""
    scoold = ("Scoold is a Q&A and a knowledge sharing platform for teams. "
              "Prior to 1.69.0, authenticated users")
    chrome = "Information leak in Extensions in Google Chrome prior to 1.2.3"
    assert advisory_names_vendor({"notes": scoold}, "teams") is False
    assert advisory_names_vendor({"notes": chrome}, "chrome") is True


def test_a_row_with_no_text_is_not_evidence_of_a_mismatch():
    """Silence is not a mismatch, and dropping on it would remove real
    releases: the genuine Teams rows in the store carry empty notes."""
    assert advisory_names_vendor({"notes": "", "title": ""}, "teams") is True


def test_no_vendor_claimed_keeps_everything():
    assert advisory_names_vendor({"notes": "anything at all"}, "") is True


def test_the_title_counts_when_the_notes_are_empty():
    row = {"notes": "", "title": "Google Chrome 156 prior to 156.0.1 fixes"}
    assert advisory_names_vendor(row, "chrome") is True
