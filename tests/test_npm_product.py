"""npm is a product, and the packages published to it are not npm.

"How do I fix EACCES on npm install?" named no product the app knew, so the
quoted-thread gate (#210) never applied and it led with "Installed apps
appearing inside the Google app" (live check, 2026-11-22). Detected as a
product, NVD's "npm" search brings every package published there; texts from
NVD, 2026-11-22."""
import pytest
import vendor


def test_npm_is_detected():
    assert [v.name for v in vendor.detect_vendors("How do I fix EACCES on npm install?",
                                                  catalog=[])] == ["npm"]


@pytest.mark.parametrize("notes", [
    "The devalue package for npm before 5.6.3 can consume excessive CPU and memory.",
    "CWE-918: Server-Side Request Forgery in the Progress @progress/sitefinity-nextjs-sdk "
    "npm package versions 15.1.8326 through 15.4.8637 may allow SSRF.",
    "An Origin Validation Error in the middleware of the connect-xcors npm package allows "
    "an attacker to bypass origin verification.",
    "The @openclaw/slack npm package before 2026.8.1 contains an authorization flaw.",
])
def test_a_package_published_to_npm_is_not_npm(notes):
    assert not vendor.advisory_names_vendor({"notes": notes}, "npm")


def test_the_npm_cli_itself_is_npm():
    assert vendor.advisory_names_vendor(
        {"notes": "The npm CLI before 6.13.4 allows arbitrary file overwrite via bin links."}, "npm")


def test_python_package_is_not_python():
    assert not vendor.advisory_names_vendor(
        {"notes": "The fastjsonschema Python package before 2.21 allows ReDoS."}, "python")
