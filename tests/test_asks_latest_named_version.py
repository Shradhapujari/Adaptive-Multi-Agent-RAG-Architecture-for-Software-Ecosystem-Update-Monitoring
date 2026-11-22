"""'latest' before a named version describes it; it does not ask for the newest.

"Did the latest Fedora 44 update delete your kernel and grub?" routed as a
version question and headlined Fedora v45.0.0 (2026-11-21 demo sweep).
"""
import pytest

from graph import asks


@pytest.mark.parametrize("q", [
    "Did the latest Fedora 44 update delete your kernel and grub?",
    "Is the latest iOS 26 update safe?",
    "Copy shortcut broken in Ptxyis (Gnome Terminal) on latest update in 26.04?",
])
def test_latest_describing_a_named_version_is_not_a_version_question(q):
    assert asks(q) == "stance"


@pytest.mark.parametrize("q", [
    "What is the latest Fedora version?",
    "Is Mozilla Firefox v148.0.0 the latest release, or is there a newer one?",
    "Is Fedora 44 the latest version?",
    "What is the latest iOS 26 update?",
    "Is the latest Firefox stable?",
])
def test_asking_for_the_newest_still_is(q):
    assert asks(q) == "version"
