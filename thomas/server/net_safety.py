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
from typing import Any
from urllib.parse import urlparse

_ALLOWED_SCHEMES = ("https", "http")
_ALLOW_PRIVATE_ENV = "THOMAS_ALLOW_PRIVATE_OUTBOUND"
_MAX_REDIRECTS = 5


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


def _validated_next_hop(response: Any) -> str | None:
    """Return the validated absolute target of a redirect, or None if not one.

    Raises ``ValueError`` (from ``validate_public_url``) when a redirect points
    somewhere the guard would have refused on the first request.
    """
    if not getattr(response, "is_redirect", False):
        return None
    location = response.headers.get("location")
    if not location:
        return None
    return validate_public_url(str(response.url.join(location)))


def request_validated(client: Any, method: str, url: str, *, max_redirects: int = _MAX_REDIRECTS, **kwargs: Any) -> Any:
    """Issue an httpx request, re-validating the target at EVERY redirect hop.

    ``validate_public_url`` only judges the URL it is handed. A client left on
    ``follow_redirects=True`` therefore checks the first address and then follows
    a ``Location`` header anywhere it likes -- including straight back to
    localhost or the cloud metadata endpoint the guard exists to refuse. The
    per-request ``follow_redirects=False`` below overrides any client-level
    default, so every hop is validated before it is fetched.
    """
    target = validate_public_url(url)
    for _ in range(max_redirects + 1):
        response = client.request(method, target, follow_redirects=False, **kwargs)
        next_hop = _validated_next_hop(response)
        if next_hop is None:
            return response
        target = next_hop
    raise ValueError(f"refusing to follow more than {max_redirects} redirects from {url!r}")


async def request_validated_async(
    client: Any, method: str, url: str, *, max_redirects: int = _MAX_REDIRECTS, **kwargs: Any
) -> Any:
    """Async twin of :func:`request_validated`, for ``httpx.AsyncClient``."""
    target = validate_public_url(url)
    for _ in range(max_redirects + 1):
        response = await client.request(method, target, follow_redirects=False, **kwargs)
        next_hop = _validated_next_hop(response)
        if next_hop is None:
            return response
        target = next_hop
    raise ValueError(f"refusing to follow more than {max_redirects} redirects from {url!r}")
