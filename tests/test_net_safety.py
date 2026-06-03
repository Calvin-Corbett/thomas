"""Unit tests for the SSRF guard in thomas/server/net_safety.py.

conftest sets THOMAS_ALLOW_PRIVATE_OUTBOUND=1 globally so integration tests can
hit local test servers; the autouse fixture here turns it back off so the guard
is actually enforced in these tests.
"""

from __future__ import annotations

import socket

import pytest

from thomas.server.net_safety import validate_public_url


def _fake_getaddrinfo(ip: str):
    def _resolver(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return _resolver


@pytest.fixture(autouse=True)
def _enforce_guard(monkeypatch):
    monkeypatch.delenv("THOMAS_ALLOW_PRIVATE_OUTBOUND", raising=False)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "gopher://example.com",
        "javascript:alert(1)",
        "https://",  # no host
        "not-a-url",
    ],
)
def test_rejects_bad_scheme_or_host(url):
    with pytest.raises(ValueError):
        validate_public_url(url)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # RFC1918 private
        "192.168.1.10",  # RFC1918 private
        "172.16.0.1",  # RFC1918 private
        "169.254.169.254",  # cloud metadata / link-local
        "0.0.0.0",  # unspecified
        "::1",  # IPv6 loopback
    ],
)
def test_blocks_non_public_addresses(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(ip))
    with pytest.raises(ValueError):
        validate_public_url("https://attacker.example/path")


def test_allows_public_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    assert validate_public_url("https://example.com/catalog") == "https://example.com/catalog"


def test_unresolvable_host_is_rejected(monkeypatch):
    def _boom(*args, **kwargs):
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    with pytest.raises(ValueError):
        validate_public_url("https://does-not-resolve.invalid")


def test_opt_out_allows_private(monkeypatch):
    monkeypatch.setenv("THOMAS_ALLOW_PRIVATE_OUTBOUND", "1")
    # With the opt-out set, a private/loopback target passes without resolution.
    assert validate_public_url("http://127.0.0.1:8080/store") == "http://127.0.0.1:8080/store"
