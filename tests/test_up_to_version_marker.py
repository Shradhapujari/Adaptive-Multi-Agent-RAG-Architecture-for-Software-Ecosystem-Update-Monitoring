"""VulDB's "X up to 2.2.0" is a version marker: the product is the one in
front of it, not GitHub from the closing "The reported GitHub issue was
closed" (releasetrain github page, 2026-11-23)."""
import vendor

AIP_PUB = ("A weakness has been identified in AIP-PUB ACPs-community up to 2.2.0. The impacted "
           "element is the function send_verification_code of the file "
           "registry-server/app/account/service_auth.py of the component verify-code Endpoint. "
           "The exploit has been made available to the public and could be used for attacks. The "
           "reported GitHub issue was closed with the reason \"completed\".")


def test_vuldb_up_to_names_the_product_in_front():
    assert not vendor.advisory_names_vendor({"notes": AIP_PUB}, "github")


def test_up_to_still_keeps_the_product_itself():
    notes = "A vulnerability was found in GitHub Enterprise Server up to 3.14.2. It allows SSRF."
    assert vendor.advisory_names_vendor({"notes": notes}, "github")


def test_up_to_and_including_unchanged():
    notes = "Django up to and including 5.1.3 allows SQL injection via QuerySet.values()."
    assert vendor.advisory_names_vendor({"notes": notes}, "django")
