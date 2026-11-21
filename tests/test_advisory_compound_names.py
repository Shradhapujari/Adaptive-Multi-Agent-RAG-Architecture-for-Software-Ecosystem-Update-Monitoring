"""An advisory for software named after a product is not that product's.

/api/v/?q=<product> files every CVE whose text contains the word under that
product. Descriptions below are live rows from 2026-11-21, when they drove
"Patch now" for rust, linux and GitHub questions in the demo sweep.
"""
import pytest

import decide as D


def _about(text, product):
    return D._about({"text": text, "source": "cve"}, D._vendor_tokens([product]),
                    set(), vendors=[product])


@pytest.mark.parametrize("product,text", [
    ("rust", "falcon-rust is a Rust implementation of the Falcon post-quantum "
             "signature scheme. Prior to 0.2.0, the discrete-Gaussian sampler ..."),
    ("rust", "libp2p-rust is the official Rust language implementation of the "
             "libp2p networking stack. Prior to 0.49.5, Gossipsub GRAFT ..."),
    ("linux", "util-linux is a random collection of Linux utilities. Before "
              "util-linux 2.41.4, `parse_dos_extended()` computes ..."),
    ("github", "Octo STS (github.com/octo-sts/app) before 0.11.2 returns trust "
               "policy configuration to callers ..."),
    ("github", "install-artifact-from-github installs prebuilt native artifacts "
               "hosted by GitHub without compiling them locally. Prior to 1.7.0, ..."),
    ("github", "Renovate, a dependency update tool, follows pagination links "
               "supplied by the GitHub server in the HTTP `Link` header ..."),
    ("linux", "A weakness has been identified in Linux Foundation Magma up to "
              "1.9.0. The impacted element is an unknown function ..."),
    ("linux", "Missing network timeouts in the Linux builds of Progressive Robot "
              "hMailServer 6.3.0 through 6.3.5 allow a remote attacker ..."),
])
def test_software_named_after_the_product_is_not_it(product, text):
    assert not _about(text, product)


@pytest.mark.parametrize("product,text", [
    ("linux", "In the Linux kernel, the following vulnerability has been "
              "resolved:  vhost/vsock: size receive SKBs from declared payload"),
    ("rust", "The Rust standard library before 1.77.2 does not escape arguments "
             "properly on Windows."),
    ("node.js", "Node.js before 22.1 allows a crafted request to ..."),
    ("chrome", "Use after free in Dawn in Google Chrome prior to 131.0 allowed ..."),
])
def test_the_product_itself_still_counts(product, text):
    assert _about(text, product)
