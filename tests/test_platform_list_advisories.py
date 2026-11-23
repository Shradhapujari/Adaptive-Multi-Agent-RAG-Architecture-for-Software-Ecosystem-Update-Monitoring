"""An OS named in a list of platforms is still the platform, not the product.
#215 caught "X for Linux"; these name the OS second or later in the list,
or as a build architecture (releasetrain linux/macos pages, 2026-11-23)."""
import pytest
import vendor

PEAZIP = ("Out-of-bounds Write (CWE-787) in the PEA archive extraction routine of PeaZip 11.2.0 "
          "and earlier, confirmed against the official Linux x86-64 and Windows x64 builds, and "
          "the denial-of-service and memory-corruption primitive is cross-platform "
          "(Windows, macOS, Linux, BSD).")
SUPREMO = ("Nanosystems Supremo for Windows and macOS before 5.0.2.3874 contains an improper "
           "certificate validation vulnerability.")
# Apple's own advisories list every OS it fixed, each with its version.
APPLE_MAC = ("An out-of-bounds write issue was addressed with improved bounds checking. This issue "
             "is fixed in macOS Sequoia 15.8.2, macOS Tahoe 26.7.2. An app may be able to cause "
             "unexpected system termination.")
APPLE_IOS = ("An out-of-bounds write issue was addressed with improved bounds checking. This issue "
             "is fixed in iOS 26.7.1 and iPadOS 26.7.1, macOS Sequoia 15.8.1, macOS Tahoe 26.7.1.")


@pytest.mark.parametrize("notes,name", [(PEAZIP, "linux"), (PEAZIP, "macos"), (PEAZIP, "windows"),
                                        (SUPREMO, "macos"), (SUPREMO, "windows")])
def test_os_in_a_platform_list_is_not_the_product(notes, name):
    assert not vendor.advisory_names_vendor({"notes": notes}, name)


@pytest.mark.parametrize("notes,name", [(APPLE_MAC, "macos"), (APPLE_IOS, "ios"), (APPLE_IOS, "macos")])
def test_apple_fixed_in_lists_stay(notes, name):
    assert vendor.advisory_names_vendor({"notes": notes}, name)
