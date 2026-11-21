"""CVE-2026-103418 is a Firefox *for iOS* advisory. `_owns` reads "Firefox for
iOS ..." as a Firefox advisory, so it counted against "Is it safe to update
Firefox right now?" -- a desktop question. "<product> for <platform>" is a
different product unless the question names that platform."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decide

IOS = ("Firefox for iOS directly interpolated the page's HTML language attribute "
       "into a script. This vulnerability was fixed in Firefox for iOS 157.1.")
DESKTOP = ("Mitigation bypass in the File Handling component allowed a sandbox "
           "escape. This vulnerability was fixed in Firefox 157.0.1.")


def _about(text, question="Is it safe to update Firefox right now?", product="firefox"):
    d = {"doc_id": "c1", "source": "nvd", "text": text}
    return decide._about(d, decide._vendor_tokens([product]),
                         decide._tokens(question), [], [product])


def test_an_ios_advisory_is_not_about_desktop_firefox():
    assert not _about(IOS)


def test_the_desktop_advisory_still_counts():
    assert _about(DESKTOP)


def test_a_question_that_names_the_platform_keeps_it():
    assert _about(IOS, question="Is it safe to update Firefox on iOS?")
    assert _about(IOS, question="Any Firefox for iPhone vulnerabilities?")


def test_a_platform_word_elsewhere_in_the_text_is_not_read():
    assert _about("Mitigation bypass in Firefox lets a page escape the sandbox, "
                  "also seen in builds for Android. Fixed in Firefox 157.0.1.")


# CVE-2026-130020, NVD text verbatim. Mozilla names the platform on the
# component, not the product, and the fix version is the shared "Firefox 160.0.1".
ANDROID = ("Privilege escalation due to incorrect boundary conditions in the Graphics: "
           "CanvasWebGL component on Android. This vulnerability was fixed in Firefox 160.0.1.")


def test_a_component_on_android_is_not_about_desktop_firefox():
    assert not _about(ANDROID)


def test_a_component_on_android_counts_when_android_is_asked():
    assert _about(ANDROID, question="Is it safe to update Firefox on Android?")


def test_a_desktop_component_on_a_platform_still_counts():
    # A Windows-only desktop bug is still about the desktop build a bare
    # "Firefox" question asks about; only the mobile platforms are split off.
    assert _about("Use-after-free in the Audio component on Windows. "
                  "This vulnerability was fixed in Firefox 160.0.1.")


def test_mac_is_macos_on_the_question_side():
    mac = "Firefox for macOS allowed code execution. Fixed in Firefox for macOS 157.1."
    assert _about(mac, question="Is it safe to update Firefox on Mac?")
    assert not _about(mac, question="Is it safe to update Firefox right now?")
