"""Unit tests for the SSRF guard in thomas/server/net_safety.py.

conftest sets THOMAS_ALLOW_PRIVATE_OUTBOUND=1 globally so integration tests can
hit local test servers; the autouse fixture here turns it back off so the guard
is actually enforced in these tests.
"""

from __future__ import annotations

import asyncio
import socket
from urllib.parse import urljoin

import pytest

from thomas.server.net_safety import request_validated, request_validated_async, validate_public_url


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


# --- redirect-hop validation -------------------------------------------------
#
# validate_public_url only judges the URL it is handed. Both plugin-store call
# sites used to run an httpx client with follow_redirects=True, so the guard
# checked the first address and the client then followed a Location header
# anywhere -- including back to the loopback and metadata addresses the tests
# above prove are refused on a direct request. These cover the redirect path.


class _FakeURL(str):
    """Minimal stand-in for httpx.URL: needs .join() and str()."""

    def join(self, other):
        return _FakeURL(urljoin(str(self), str(other)))


class _FakeResponse:
    def __init__(self, url, location=None):
        self.url = _FakeURL(url)
        self.headers = {"location": location} if location else {}
        self.is_redirect = location is not None


class _FakeClient:
    """Records every URL actually requested, so we can assert what was NOT fetched."""

    def __init__(self, script):
        self._script = dict(script)
        self.requested: list[str] = []

    def request(self, method, url, **kwargs):
        self.requested.append(str(url))
        return self._script.get(str(url), _FakeResponse(url))


class _FakeAsyncClient(_FakeClient):
    async def request(self, method, url, **kwargs):  # type: ignore[override]
        return _FakeClient.request(self, method, url, **kwargs)


def test_redirect_to_private_address_is_blocked_and_never_fetched(monkeypatch):
    """A 302 pointing at loopback must raise, and must not be requested."""

    def _resolver(host, port, *args, **kwargs):
        ip = "127.0.0.1" if host == "internal.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _resolver)
    client = _FakeClient(
        {"https://store.example/bundle": _FakeResponse("https://store.example/bundle", "https://internal.example/secret")}
    )
    with pytest.raises(ValueError):
        request_validated(client, "GET", "https://store.example/bundle")
    assert "https://internal.example/secret" not in client.requested


def test_relative_redirect_is_resolved_then_validated(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    client = _FakeClient(
        {"https://store.example/a": _FakeResponse("https://store.example/a", "/b")}
    )
    response = request_validated(client, "GET", "https://store.example/a")
    assert client.requested == ["https://store.example/a", "https://store.example/b"]
    assert response.is_redirect is False


def test_redirect_chain_is_bounded(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    # every URL redirects to the next, forever
    client = _FakeClient({})
    client.request = lambda method, url, **kw: (  # type: ignore[assignment]
        client.requested.append(str(url)) or _FakeResponse(url, "https://store.example/next")
    )
    with pytest.raises(ValueError, match="more than"):
        request_validated(client, "GET", "https://store.example/start")


def test_non_redirect_passes_straight_through(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    client = _FakeClient({})
    response = request_validated(client, "GET", "https://store.example/ok")
    assert client.requested == ["https://store.example/ok"]
    assert response.is_redirect is False


def test_async_variant_blocks_the_same_redirect(monkeypatch):
    def _resolver(host, port, *args, **kwargs):
        ip = "169.254.169.254" if host == "metadata.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _resolver)
    client = _FakeAsyncClient(
        {"https://store.example/c": _FakeResponse("https://store.example/c", "https://metadata.example/latest")}
    )
    with pytest.raises(ValueError):
        asyncio.run(request_validated_async(client, "GET", "https://store.example/c"))
    assert "https://metadata.example/latest" not in client.requested
