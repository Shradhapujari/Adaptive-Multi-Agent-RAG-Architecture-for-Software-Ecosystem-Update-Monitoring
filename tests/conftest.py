"""The suite does not reach the network, and now cannot.

It was never supposed to: `vendor.load_catalog(fetch=False)` exists for exactly
this, and `specs/status.md` has claimed "399 passing, offline, no network"
since August. It was not true. `load_vendor_lists()` prefers a live fetch to
releasetrain.io and only falls back to the disk cache, so any test that reached
vendor extraction went out to the internet -- and for a long stretch of the run
it did not, because a catalog-outage test leaked a stubbed `requests.get` that
answered instantly (fixed in `_fresh_module`). Removing that stub is what made
the real behaviour visible: the suite slowed from 75 s to 183 s.

A test that silently depends on a remote host is a test that fails on a plane,
in CI without egress, and on the day that host is down -- and a green run that
depended on the network proves less than it appears to.

The guard is at the socket, not at `requests`, so it holds for urllib, httpx,
raw sockets and anything else a future test reaches for. Local addresses stay
open: Ollama, a temp HTTP server and sqlite are all local and legitimate.

To let one test out deliberately, ask for the `network` fixture -- and expect
to justify it in review.

One hole, stated rather than papered over: the guard is a per-test fixture, so
a module that reaches the network at *import* time runs before it is installed.
Nothing does today. If something starts to, the fix is a `pytest_collection`
hook, not a wider fixture.
"""
from __future__ import annotations

import socket

import pytest

_LOCAL = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}


class NetworkUsedInTest(RuntimeError):
    """Raised instead of opening a connection to a remote host."""


def _host_of(address):
    if isinstance(address, (tuple, list)) and address:
        return str(address[0])
    return str(address)


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """Block outbound connections to anything that is not this machine."""
    if "network" in request.fixturenames:          # opted out, deliberately
        return

    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def guard_connect(self, address, *a, **k):
        host = _host_of(address)
        if host not in _LOCAL:
            raise NetworkUsedInTest(
                f"{request.node.nodeid} tried to connect to {host}. Tests run "
                f"offline; use a fixture or stub, or request the `network` "
                f"fixture if the test genuinely needs egress.")
        return real_connect(self, address, *a, **k)

    def guard_getaddrinfo(host, *a, **k):
        if str(host) not in _LOCAL:
            raise NetworkUsedInTest(
                f"{request.node.nodeid} tried to resolve {host}. Tests run "
                f"offline; use a fixture or stub.")
        return real_getaddrinfo(host, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", guard_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guard_getaddrinfo)


@pytest.fixture
def network():
    """Opt out of `no_network` for one test. Justify it where you use it."""
    return True
