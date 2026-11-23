"""A Rust crate's CVE is not a Rust CVE. "Did rust v1.92.0 ship?" said Patch now
on Apache Arrow's `parquet` crate (sweep, 2026-11-23; texts from NVD)."""
import pytest
import vendor

NOT_RUST = [
    # CVE-2026-125651
    "Cleartext storage in encrypted parquet file vulnerability in Apache Arrow Rust "
    "(`parquet` crate), from version 55.0.0 through to 57.3.2, 58.4.1, 59.3.2 and 60.1.0.",
    "The hyper-staticfile Rust crate before 0.10.1 allows path traversal.",
]

RUST = [
    # CVE-2024-24576
    "Rust is a programming language. The Rust Security Response WG was notified that "
    "the Rust standard library did not properly escape arguments when invoking batch "
    "files (with the bat and cmd extensions) on Windows using the Command API. "
    "This issue was fixed in Rust 1.77.2.",
    # CVE-2022-21658
    "Rust is a multi-paradigm, general-purpose programming language. The Rust Security "
    "Response WG was notified that the std::fs::remove_dir_all standard library function "
    "is vulnerable a race condition enabling symlink following. Versions of Rust prior "
    "to 1.58.1 are affected.",
]


@pytest.mark.parametrize("notes", NOT_RUST)
def test_a_crate_is_not_rust(notes):
    assert not vendor.advisory_names_vendor({"notes": notes}, "rust")


@pytest.mark.parametrize("notes", RUST)
def test_rust_itself_still_rust(notes):
    assert vendor.advisory_names_vendor({"notes": notes}, "rust")
