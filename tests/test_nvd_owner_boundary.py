"""NVD advisories arrive as free text (no trustworthy product field from
/api/v/). Advisory descriptions are written vendor-first, so when a different
known vendor is named before the asked product in the subject, the artifact is
that vendor's: Cisco's IOS is not Apple's iOS, Zoom's Windows client is not
Windows. Applies only to products whose owner is on file (vendor_kb.json)."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decide


def _nvd(desc, cve="CVE-2026-2001"):
    return {"doc_id": "n1", "source": "nvd", "title": cve, "text": f"{desc} ({cve})"}


CASES = [
    ("edge", "Cisco IOS XE edge router firmware contains a command injection flaw.", "insufficient_evidence"),
    ("ios", "Cisco IOS XE Software contains a privilege escalation flaw.", "insufficient_evidence"),
    ("windows", "Zoom Windows client contains an untrusted search path flaw.", "insufficient_evidence"),
    ("linux", "Android kernel (Linux) contains a use-after-free.", "insufficient_evidence"),
    ("linux", "Red Hat Enterprise Linux contains a privilege escalation flaw.", "insufficient_evidence"),
    # The owner, or no vendor at all, before the product: still the product's.
    ("windows", "Microsoft Windows SMB contains a missing authentication flaw.", "patch_urgently"),
    ("chrome", "Google Chrome before 140.0.1 allows a heap overflow.", "patch_urgently"),
    ("ios", "Apple iOS before 26.1 allows an app to gain root privileges.", "patch_urgently"),
    ("linux", "Linux kernel before 6.17.2 contains a use-after-free.", "patch_urgently"),
    ("node.js", "Node.js before 24.9.1 contains a request smuggling flaw.", "patch_urgently"),
    # No owner on file: the vendor-first rule does not apply.
    ("ubuntu", "Canonical Ubuntu contains a privilege escalation flaw.", "patch_urgently"),
]


@pytest.mark.parametrize("product,desc,want", CASES, ids=[f"{p}:{d[:30]}" for p, d, _ in CASES])
def test_a_foreign_vendor_before_the_product_owns_the_advisory(product, desc, want):
    d = decide.decide([_nvd(desc)], f"Is it safe to update {product}?", vendors=[product])
    assert d.verdict == want, d.rationale


def test_any_asked_product_may_still_own_it():
    row = _nvd("Microsoft Edge contains a memory corruption flaw.")
    assert decide.decide([row], "Is it safe to update Edge?", vendors=["edge", "safe"]).verdict \
        == "patch_urgently"
