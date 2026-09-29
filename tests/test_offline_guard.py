"""The offline guard has to fail loudly, or it is worse than not having it.

A guard that quietly stops working returns the suite to reaching the network
without anyone noticing -- which is the state these tests were already in. So
the guard gets tests of its own.
"""
import socket

import pytest
import requests

from conftest import NetworkUsedInTest


def test_a_remote_connection_is_refused():
    with pytest.raises(NetworkUsedInTest):
        socket.create_connection(("example.com", 80), timeout=1)


def test_requests_cannot_reach_out():
    """The guard sits at the socket, so it holds for the HTTP client too."""
    with pytest.raises(Exception) as exc:
        requests.get("https://releasetrain.io/api/c/names", timeout=1)
    assert "offline" in str(exc.value).lower() or "NetworkUsedInTest" in repr(exc.value)


def test_dns_for_a_remote_host_is_refused():
    with pytest.raises(NetworkUsedInTest):
        socket.getaddrinfo("releasetrain.io", 443)


def test_local_addresses_stay_open():
    """Ollama, a temp server and sqlite are local and legitimate."""
    assert socket.getaddrinfo("127.0.0.1", 0)
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        client = socket.socket()
        client.connect(s.getsockname())          # must not raise
        client.close()
    finally:
        s.close()


def test_the_vendor_catalog_still_loads_offline():
    """What the suite actually depends on: extraction works with no network."""
    import multiagent_rag_v3 as m
    m._VENDORS_LOADED = False                     # force the load path
    found = m.extract_vendor("Which is more stable, Teams or Zoom?")
    assert set(found) >= {"teams", "zoom"}, found
    assert m.catalog_status()["source"] != "live"


def test_the_opt_out_works(network):
    """`network` is the deliberate escape hatch; it must actually disable the
    guard, or a test that needs egress cannot be written at all.

    Asserted by checking the guard is not installed rather than by reaching a
    remote host: proving the suite *can* leave the machine should not require
    it to leave the machine."""
    assert network is True
    assert socket.getaddrinfo.__name__ != "guard_getaddrinfo", "guard still on"
    assert socket.socket.connect.__name__ != "guard_connect", "guard still on"


def test_the_guard_is_on_without_the_opt_out():
    """The mirror of the test above -- otherwise both would pass with the
    fixture doing nothing at all."""
    assert socket.getaddrinfo.__name__ == "guard_getaddrinfo"
    assert socket.socket.connect.__name__ == "guard_connect"
