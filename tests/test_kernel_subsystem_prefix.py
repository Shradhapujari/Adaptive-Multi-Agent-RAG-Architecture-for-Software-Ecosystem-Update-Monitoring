"""A Linux kernel CVE is about Linux, whatever subsystem prefix follows the
preamble: "rust: configfs: ..." is the kernel's own Rust code, not the Rust
toolchain (live check, 2026-11-22: "Is it safe to update rust?" -> Patch now
on CVE-2026-99486/99487)."""
import vendor

RUST_IN_KERNEL = ("In the Linux kernel, the following vulnerability has been resolved:\n\n"
                  "rust: configfs: fix data offset calculation for subsystem callbacks")


def test_kernel_rust_subsystem_is_not_rust():
    assert not vendor.advisory_names_vendor({"notes": RUST_IN_KERNEL}, "rust")


def test_kernel_cve_still_linux():
    assert vendor.advisory_names_vendor({"notes": RUST_IN_KERNEL}, "linux")


def test_other_kernel_prefixes():
    for sub in ("btrfs: fix leak", "net: sched: fix race", "drm/amd: fix oops"):
        notes = "In the Linux kernel, the following vulnerability has been resolved:\n\n" + sub
        assert not vendor.advisory_names_vendor({"notes": notes}, sub.split(":")[0].split("/")[0])
        assert vendor.advisory_names_vendor({"notes": notes}, "linux")
