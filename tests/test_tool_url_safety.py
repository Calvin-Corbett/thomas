"""Tests for the canonical outbound-URL SSRF guard (``thomas.tools.url_safety``).

Covers the tiered policy that backs ``web.fetch``, ``eng.web_extract`` and
``browser.open``: cloud-metadata/link-local is always blocked, RFC1918/loopback
is gated behind ``allow_private``, and hostnames are resolved so DNS-based SSRF
is caught. DNS is monkeypatched throughout so no test touches the real network.
"""

from __future__ import annotations

import asyncio

import pytest

from thomas.tools import url_safety
from thomas.tools.url_safety import check_url

# --- always-blocked, regardless of allow_private ----------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # AWS/GCP/Azure IMDS
        "http://169.254.169.254/",
        "https://[fe80::1]/",  # IPv6 link-local
        "http://224.0.0.1/",  # multicast
        "http://240.0.0.1/",  # reserved
        "http://0.0.0.0/",  # unspecified
    ],
)
def test_metadata_and_special_ranges_always_blocked(url):
    # Even with allow_private=True these must be refused.
    assert check_url(url, allow_private=True) is not None


# --- private / loopback gated behind allow_private --------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/",
        "http://10.0.0.5/",
        "http://192.168.1.10/",
        "http://172.16.0.1/",
        "http://localhost:3000/",
        "http://[::1]/",
    ],
)
def test_private_blocked_when_disallowed(url):
    assert check_url(url, allow_private=False) is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/",
        "http://10.0.0.5/",
        "http://192.168.1.10/",
        "http://localhost:3000/",
        "http://[::1]/",
    ],
)
def test_private_allowed_when_enabled(url):
    # Local-first product: localhost dev servers are legitimate when opted in.
    assert check_url(url, allow_private=True) is None


# --- public hosts always allowed --------------------------------------------


@pytest.mark.parametrize("allow_private", [True, False])
def test_public_ip_allowed(allow_private):
    assert check_url("http://93.184.216.34/", allow_private=allow_private) is None


# --- scheme / credential validation -----------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com/",
        "data:text/plain;base64,AAAA",
    ],
)
def test_non_http_schemes_blocked(url):
    assert check_url(url, allow_private=True) is not None


def test_embedded_credentials_blocked():
    assert check_url("http://user:pass@example.com/", allow_private=True) is not None


# --- allow / deny host policy -----------------------------------------------


def test_blocked_hosts_rule():
    assert check_url("http://evil.example.com/", allow_private=True, blocked_hosts=[".example.com"]) is not None
    assert check_url("http://good.test/", allow_private=True, blocked_hosts=[".example.com"]) is None


def test_allowed_hosts_allowlist():
    # When an allowlist is set, anything not on it is refused.
    assert check_url("http://other.test/", allow_private=True, allowed_hosts=["api.test"]) is not None
    assert check_url("http://api.test/", allow_private=True, allowed_hosts=["api.test"]) is None


# --- DNS-based SSRF (hostname resolves to a blocked / private IP) ------------


def _fake_getaddrinfo(ip: str):
    def _inner(host, *args, **kwargs):
        return [(2, 1, 6, "", (ip, 0))]

    return _inner


def test_hostname_resolving_to_metadata_blocked(monkeypatch):
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    assert check_url("http://innocent-looking.example/", allow_private=True) is not None


def test_hostname_resolving_to_private_gated(monkeypatch):
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake_getaddrinfo("10.1.2.3"))
    assert check_url("http://internal.example/", allow_private=False) is not None
    assert check_url("http://internal.example/", allow_private=True) is None


def test_hostname_resolving_to_public_allowed(monkeypatch):
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    assert check_url("http://example.com/", allow_private=False) is None


def test_dns_failure_does_not_bypass_literal_checks(monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("dns down")

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", _boom)
    # A literal metadata IP needs no DNS and must still be refused.
    assert check_url("http://169.254.169.254/", allow_private=True) is not None
    # An unresolvable hostname can't be classified by IP, so literal checks pass.
    assert check_url("http://example.com/", allow_private=True) is None


# --- integration: the two newly-guarded tools refuse metadata early ---------


def test_web_extract_refuses_metadata():
    from thomas.tools.engineering import WebExtractTool

    res = asyncio.run(WebExtractTool().execute({"url": "http://169.254.169.254/latest/meta-data/"}))
    assert res.ok is False
    assert res.error


def test_browser_open_refuses_metadata():
    from thomas.tools.browser import BrowserOpenTool

    res = asyncio.run(BrowserOpenTool().execute({"url": "http://169.254.169.254/"}))
    assert res.ok is False
    assert res.error
