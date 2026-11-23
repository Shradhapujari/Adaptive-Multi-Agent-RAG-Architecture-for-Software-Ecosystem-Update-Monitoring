"""Linux as the platform is not Linux the product. Releasetrain's linux page
kept these as Linux advisories, and the Fedora 44 question said Patch now on
them (live check, 2026-11-22; texts from the live page)."""
import pytest
import vendor

NOT_LINUX = [
    "Improper neutralization of special elements used in an OS command in the remote SSH "
    "operation functionality of Lenovo XClarity Essentials OneCLI 5.5.0 for Linux could allow "
    "an attacker to execute arbitrary OS commands.",
    "Out-of-Bounds Write Vulnerability in Hitachi Dynamic Link Manager for Linux.\n\n\nThis issue "
    "affects Hitachi Dynamic Link Manager for Linux: from 7.5.0-00 before 9.0.5-00.",
    "TeamViewer Full Client and Host for Linux prior version 15.82 contains an improper path "
    "validation vulnerability.",
    "There\nis stack-based buffer overflow vulnerability recently discovered in MCC Universal "
    "Library for Linux (uldaq). This vulnerability affects MCC Universal Library for Linux "
    "before 1.2.1.",
    "Local privilege escalation due to insecure file permissions. The following products are "
    "affected: Acronis Backup plugin for cPanel & WHM (Linux) before build 1.9.3.1021.",
    "When a message was forwarded inline, a specially crafted link attachment (a .desktop file "
    "on Linux, or a .url or .lnk file on Windows) was replaced with the content.",
    "A weakness has been identified in Linux Foundation Magma up to 1.9.0. The impacted element "
    "is an unknown function.",
    "Missing network timeouts in the Linux builds of Progressive Robot hMailServer 6.3.0 through "
    "6.3.5 allow a remote attacker to hold server threads indefinitely.",
    "EnergizeLab AI Station firmware, EilikO Linux robot firmware v2.1_20260617182218_release, "
    "and the EnergizeLab Windows desktop app 3.1.2 download firmware updates over plain HTTP.",
    "The Super Forms plugin for WordPress is vulnerable to Directory Traversal in all versions "
    "up to, and including, 6.3.316. Exploitation on Linux requires a real 13-digit timestamp.",
]

STAYS = [
    ({"notes": "The Linux kernel before 6.1.12 allows a use-after-free in io_uring."}, "linux"),
    ({"notes": "Use after free in Navigation in Google Chrome on Android prior to 120.0 "
               "allowed a remote attacker to exploit heap corruption."}, "chrome"),
    ({"notes": "Use-after-free in the Audio/Video: Playback component. This vulnerability "
               "was fixed in Firefox 160.0.1."}, "firefox"),
]


@pytest.mark.parametrize("notes", NOT_LINUX)
def test_linux_as_platform_is_not_linux(notes):
    assert not vendor.advisory_names_vendor({"notes": notes}, "linux")


@pytest.mark.parametrize("row,name", STAYS)
def test_products_named_as_products_stay(row, name):
    assert vendor.advisory_names_vendor(row, name)


def test_chrome_on_android_is_not_android():
    assert not vendor.advisory_names_vendor(STAYS[1][0], "android")
