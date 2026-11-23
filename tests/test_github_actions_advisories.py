"""A CVE in someone's GitHub Actions workflow, or in a third-party action, is
not a GitHub vulnerability. "Any security vulnerabilities in GitHub?" said
Patch now on five of them (live check, 2026-11-22; texts from NVD)."""
import pytest
import vendor

NOT_GITHUB = [
    # CVE-2026-129840, full NVD text (no version marker: whole text is read).
    # Its last sentence names GitHub Pages; the trimmed copy here hid that
    # and the row reached "Patch now" again (sweep, 2026-11-23).
    "In the nrfconnect/ncs-zigbee repository, the GitHub Actions workflow "
    ".github/workflows/build_documentation.yml used the pull_request_target trigger "
    "while checking out and executing untrusted pull request code. This allowed a "
    "pull request from a fork to run attacker-controlled code in the base repository "
    "context with a write-scoped GITHUB_TOKEN (contents: write, pages: write, "
    "pull-requests: write), enabling remote code execution in CI, token "
    "exfiltration, and unauthorized modification of repository content and GitHub "
    "Pages. The workflow was disabled and then rewritten to remove the issue.",
    # CVE-2026-133630
    "The flowintel Docker build workflow used the GitHub Actions checkout action with "
    "default credential persistence, causing the job authentication token to be written "
    "into the repository's Git configuration file.",
    # CVE-2026-133192..133194
    "In JetBrains Junie GitHub Action before 1.10.0 untrusted fork code could be processed "
    "in privileged workflow runs",
    "In JetBrains Junie GitHub Action before 1.10.0 command injection was possible via the "
    "action version input",
]

GITHUB = [
    "An improper access control vulnerability in GitHub Enterprise Server allowed "
    "privilege escalation. This vulnerability affected all versions of GitHub Enterprise "
    "Server prior to 3.18.",
    "The GitHub Actions Runner before 2.330.0 allows a job to read another job's secrets.",
]


@pytest.mark.parametrize("notes", NOT_GITHUB)
def test_workflow_and_third_party_actions_are_not_github(notes):
    assert not vendor.advisory_names_vendor({"notes": notes}, "github")


@pytest.mark.parametrize("notes", GITHUB)
def test_github_own_products_still_github(notes):
    assert vendor.advisory_names_vendor({"notes": notes}, "github")
