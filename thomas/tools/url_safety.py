"""Canonical outbound-URL safety guard for agent tools (SSRF hardening).

This is the single source of truth for the host policy applied to every tool
that fetches a model- or user-supplied URL (``web.fetch``, ``eng.web_extract``,
``browser.open``). Keeping one implementation avoids the drift that let
``eng.web_extract`` and ``browser.open`` ship with *no* guard at all while
``web.fetch`` had one.

The check is **tiered** on purpose so a local-first install stays usable:

* Cloud-metadata / link-local (``169.254.0.0/16`` -- the AWS/GCP/Azure IMDS
  address), multicast, reserved and the unspecified address are **never**
  legitimate fetch targets for an AI tool, so they are blocked *regardless* of
  policy. This is the classic SSRF escalation path (stealing cloud IAM
  credentials from ``http://169.254.169.254/``).
* RFC1918 private ranges and loopback stay gated behind ``allow_private`` so a
  local install can still fetch ``http://localhost:3000`` dev servers when the
  operator opts in (which is the default for the local-first product).

Hostnames are resolved (best-effort) so ``evil.example`` pointing at a private
or blocked IP is caught, not just literal-IP URLs. DNS resolution is advisory
(a rebind between this check and the real connection is still possible); the
literal-IP and policy checks are authoritative.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlparse

_IpAddr = ipaddress.IPv4Address | ipaddress.IPv6Address


def _ip_never_allowed(ip: _IpAddr) -> bool:
    """Address classes that are never a legitimate outbound fetch target.

    Blocked even when ``allow_private`` is true, because nothing an AI tool
    should fetch lives here -- but the cloud metadata service does.

    Loopback is deliberately excluded: it belongs to the local-dev tier gated by
    ``allow_private``. (Python's ``ipaddress`` also marks IPv6 loopback ``::1``
    as ``is_reserved`` because it falls in ``::/8``, so loopback must be checked
    first or a permitted ``localhost`` fetch would be wrongly refused.)
    """
    if ip.is_loopback:
        return False
    return bool(ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def _ip_is_private(ip: _IpAddr) -> bool:
    """RFC1918 / loopback -- legitimate only for local-dev fetches (opt-in)."""
    return bool(ip.is_private or ip.is_loopback)


def _host_matches_rule(host: str, rule: str) -> bool:
    h = host.lower().strip()
    r = rule.lower().strip()
    if not h or not r:
        return False
    if r.startswith("."):
        return h == r[1:] or h.endswith(r)
    return h == r


def _literal_ip(host: str) -> _IpAddr | None:
    h = host.strip().lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        return None


def _resolve_ips(host: str) -> list[_IpAddr]:
    """Best-effort DNS resolution.

    Returns an empty list on any resolution failure; the caller still applies
    the literal-host checks, so a failed lookup cannot be used to bypass them.
    """
    ips: list[_IpAddr] = []
    try:
        for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP):
            sockaddr = info[4]
            try:
                ips.append(ipaddress.ip_address(sockaddr[0]))
            except ValueError:
                continue
    except (OSError, UnicodeError):
        return []
    return ips


def check_url(
    url: str,
    *,
    allow_private: bool,
    allowed_hosts: Iterable[str] = (),
    blocked_hosts: Iterable[str] = (),
) -> str | None:
    """Validate that *url* is safe to fetch.

    Returns a human-readable error string if the URL must be refused, or
    ``None`` if it passes the policy.
    """
    try:
        parsed = urlparse(url)
    except (ValueError, AttributeError):
        return "Invalid URL."
    if parsed.scheme not in ("http", "https"):
        return "Only http(s) URLs may be fetched."
    if not parsed.netloc:
        return "Invalid URL host."
    if parsed.username or parsed.password:
        return "URLs with embedded credentials are not allowed."

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return "Invalid URL host."

    blocked = [str(r).strip().lower() for r in blocked_hosts if str(r).strip()]
    allowed = [str(r).strip().lower() for r in allowed_hosts if str(r).strip()]
    for rule in blocked:
        if _host_matches_rule(host, rule):
            return f"Host blocked by policy: {host}"
    if allowed and not any(_host_matches_rule(host, rule) for rule in allowed):
        return f"Host not in allowed_hosts policy: {host}"

    # Textual loopback aliases that may not resolve in restricted environments.
    if (host == "localhost" or host.endswith(".localhost") or host.endswith(".local")) and not allow_private:
        return f"Private/loopback host disallowed by policy: {host}"

    # Candidate IPs: the literal IP if the host is one, else DNS-resolved IPs.
    literal = _literal_ip(host)
    candidates = [literal] if literal is not None else _resolve_ips(host)
    for ip in candidates:
        if _ip_never_allowed(ip):
            return f"Host resolves to a blocked address ({ip}); refusing (SSRF guard)."
        if not allow_private and _ip_is_private(ip):
            return f"Private network host disallowed by policy: {host} ({ip})."
    return None
