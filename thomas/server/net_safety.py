"""Outbound URL safety guard (SSRF mitigation).

User-supplied URLs -- e.g. a marketplace ``store_url`` taken from a request --
must be validated before the server fetches them, or an attacker can point them
at internal services and cloud metadata endpoints (169.254.169.254).
``validate_public_url`` rejects non-http(s) schemes and any host that resolves
to a non-publicly-routable address.

Self-hosted deployments that legitimately run a plugin store on a private
address (localhost, a LAN host) can opt out with
``THOMAS_ALLOW_PRIVATE_OUTBOUND=1``.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = ("https", "http")
_ALLOW_PRIVATE_ENV = "THOMAS_ALLOW_PRIVATE_OUTBOUND"


def _allow_private() -> bool:
    return os.environ.get(_ALLOW_PRIVATE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _resolves_public(host: str) -> bool:
    """Return True only if every address *host* resolves to is publicly routable."""
    try:
        addrinfo = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in addrinfo:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return bool(addrinfo)


def validate_public_url(url: str) -> str:
    """Return *url* if the server may safely fetch it, else raise ``ValueError``.

    SSRF guard: only http(s) URLs whose host resolves exclusively to
    publicly-routable addresses are permitted (unless ``THOMAS_ALLOW_PRIVATE_OUTBOUND``
    is set for trusted self-hosted stores).
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"refusing to fetch non-http(s) URL: {url!r}")
    if not parsed.hostname:
        raise ValueError(f"refusing to fetch URL with no host: {url!r}")
    if _allow_private():
        return url
    if not _resolves_public(parsed.hostname):
        raise ValueError(f"refusing to fetch URL resolving to a non-public address: {parsed.hostname!r}")
    return url
