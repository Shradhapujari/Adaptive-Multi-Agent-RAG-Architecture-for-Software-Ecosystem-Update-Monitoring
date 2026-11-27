"""nginx, Log4j and Go are not in the product catalog, so questions about them
named no product and quoted unrelated Reddit threads (2026-11-23 sweep)."""
import pytest

from vendor import detect_vendors


@pytest.mark.parametrize("q, name", [
    ("Any new CVEs for nginx?", "nginx"),
    ("Is Log4j still vulnerable?", "log4j"),
    ("Is log4j2 safe?", "log4j"),
    ("Latest golang release?", "go"),
    ("Which version of Go is the newest?", "go"),
    ("Is Go 1.25 safe to update?", "go"),
])
def test_detected(q, name):
    assert name in [v.name for v in detect_vendors(q, catalog=[])]


@pytest.mark.parametrize("q", [
    "Go to settings and update Chrome?",
    "Should I go ahead and update Firefox?",
    "Is nginx-proxy-manager safe?",
    "Qwen3.8-Flash is now available in OpenCode Go",
    "OneDrive blown up in Go Finder...wtf lol",
])
def test_not_detected(q):
    names = [v.name for v in detect_vendors(q, catalog=[])]
    assert "go" not in names and "nginx" not in names
