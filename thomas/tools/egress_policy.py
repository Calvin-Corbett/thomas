"""CAP-130: VPC / self-host egress control -- deny-by-default policy engine.

The hermetic core of self-host egress control: a deterministic policy engine
that decides ``allow`` / ``deny`` for a single outbound connection described by
``(host, ip, port)``. It answers the VPC question "may this workload talk to
that endpoint?" *before* a socket is ever opened, and records every verdict to
a durable, append-only audit log.

Policy model
------------

- **Deny-by-default.** An empty allowlist denies everything. Anything that does
  not match an explicit allow rule is denied.
- **Allowlist rules**, evaluated in caller-supplied order (first match wins),
  each of which may constrain any combination of:

  * **host** -- an exact hostname (``api.example.com``) or a wildcard subdomain
    (``*.example.com``, which matches ``a.example.com`` and ``a.b.example.com``
    but NOT the apex ``example.com``);
  * **cidr** -- an IPv4/IPv6 network in CIDR notation (``10.0.0.0/8``), matched
    against the connection's resolved ``ip`` via the stdlib :mod:`ipaddress`;
  * **ports** -- a single port, an inclusive range, or a set of either; a
    connection port outside every allowed range is denied even when the host
    matches.

- **Ordered decision.** :meth:`EgressPolicyEngine.decide` returns an
  :class:`EgressDecision` naming the matched rule and a human reason.
- **Audit log.** Every decision (allow *and* deny) is appended as one JSON line
  to a durable log whose path is (in priority order) the constructor argument,
  the ``THOMAS_EGRESS_AUDIT_LOG`` environment variable, or a default file under
  the system temp directory. Writes are flushed and ``fsync``-ed so a verdict
  survives a crash.

Determinism
-----------

Given the same rules, the same connection, and an injected fixed clock, the
engine returns byte-identical decisions and writes byte-identical audit lines.
The clock is injectable for exactly this reason.

Live lane (documented, NOT run here)
------------------------------------

This module is the *decision plane* only -- it never touches a socket, firewall,
or kernel. In a real VPC / self-host deployment you wire :meth:`decide` into the
*enforcement plane*: call it from a connect-time hook (an ``eBPF``/``LD_PRELOAD``
socket shim, a forward-proxy's ``CONNECT`` handler, or a sidecar) and, on a deny
verdict, drop the connection; periodically compile the same rule set into
``iptables``/``nftables`` OUTPUT chains or a cloud security-group so kernel-level
enforcement matches this engine. That enforcement edge needs root / a running
proxy / cloud credentials and is intentionally out of scope for this hermetic
core -- only the physical block is gated, the policy and audit are real.

This module depends only on the standard library (tools layer rule: no imports
from agent/server/cli).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_AUDIT_LOG = "THOMAS_EGRESS_AUDIT_LOG"
_DEFAULT_LOG_NAME = "thomas_egress_audit.log"

DECISION_ALLOW = "allow"
DECISION_DENY = "deny"

REASON_DEFAULT_DENY = "deny-by-default: no allow rule matched"

# Type alias for the accepted port specifications.
PortSpec = "int | tuple[int, int] | str | Iterable[int | tuple[int, int] | str] | None"


class EgressPolicyError(Exception):
    """Base class for egress-policy configuration errors."""


class InvalidRuleError(EgressPolicyError):
    """Raised when a rule is malformed (no matcher, bad CIDR, bad port range)."""


class InvalidConnectionError(EgressPolicyError):
    """Raised when a connection to evaluate has a malformed ip or port."""


def _normalize_host(host: str) -> str:
    """Lowercase and strip a single trailing dot from a hostname."""
    return host.strip().rstrip(".").lower()


def _parse_ports(spec: PortSpec) -> tuple[tuple[int, int], ...]:
    """Normalize a port spec into a tuple of inclusive ``(lo, hi)`` ranges.

    ``None`` means "any port" and is represented by the empty tuple. Accepts an
    int, an inclusive ``(lo, hi)`` tuple, a ``"lo-hi"`` / ``"port"`` string, or
    an iterable mixing those.
    """
    if spec is None:
        return ()
    atoms: list[object]
    if isinstance(spec, (int, str, tuple)):
        atoms = [spec]
    else:
        atoms = list(spec)
    ranges: list[tuple[int, int]] = []
    for atom in atoms:
        ranges.append(_parse_port_atom(atom))
    return tuple(ranges)


def _parse_port_atom(atom: object) -> tuple[int, int]:
    """Normalize one port atom into an inclusive ``(lo, hi)`` range."""
    if isinstance(atom, bool):  # bool is an int subclass; reject to avoid True==1 traps
        raise InvalidRuleError(f"invalid port {atom!r}")
    if isinstance(atom, int):
        lo = hi = atom
    elif isinstance(atom, tuple):
        if len(atom) != 2:
            raise InvalidRuleError(f"port range must be (lo, hi): {atom!r}")
        lo, hi = int(atom[0]), int(atom[1])
    elif isinstance(atom, str):
        text = atom.strip()
        if "-" in text:
            lo_s, _, hi_s = text.partition("-")
            try:
                lo, hi = int(lo_s), int(hi_s)
            except ValueError as exc:
                raise InvalidRuleError(f"invalid port range {atom!r}") from exc
        else:
            try:
                lo = hi = int(text)
            except ValueError as exc:
                raise InvalidRuleError(f"invalid port {atom!r}") from exc
    else:
        raise InvalidRuleError(f"unsupported port spec {atom!r}")
    if lo > hi:
        lo, hi = hi, lo
    if not (0 <= lo <= 65535 and 0 <= hi <= 65535):
        raise InvalidRuleError(f"port out of range [0, 65535]: {atom!r}")
    return (lo, hi)


@dataclass(frozen=True)
class EgressRule:
    """One ordered allowlist entry.

    A rule matches a connection when *every* constraint it declares is satisfied
    (host AND cidr AND ports). A constraint left as ``None``/empty means "any".
    At least one of ``host`` or ``cidr`` must be declared -- a rule that
    constrains nothing but ports would allow arbitrary destinations and is
    rejected as a misconfiguration.
    """

    name: str
    host: str | None = None
    cidr: str | None = None
    ports: tuple[tuple[int, int], ...] = ()
    _network: ipaddress.IPv4Network | ipaddress.IPv6Network | None = field(default=None, repr=False, compare=False)

    @classmethod
    def allow(
        cls,
        name: str,
        *,
        host: str | None = None,
        cidr: str | None = None,
        ports: PortSpec = None,
    ) -> EgressRule:
        """Build a validated allow rule.

        Raises :class:`InvalidRuleError` if neither host nor cidr is given, or if
        the cidr / ports are malformed.
        """
        if not name or not name.strip():
            raise InvalidRuleError("rule name is required")
        if host is None and cidr is None:
            raise InvalidRuleError(f"rule {name!r} must declare a host or a cidr")
        norm_host = _normalize_host(host) if host is not None else None
        if norm_host is not None and not norm_host:
            raise InvalidRuleError(f"rule {name!r} has an empty host")
        network: ipaddress.IPv4Network | ipaddress.IPv6Network | None = None
        if cidr is not None:
            try:
                network = ipaddress.ip_network(cidr.strip(), strict=False)
            except ValueError as exc:
                raise InvalidRuleError(f"rule {name!r} has invalid cidr {cidr!r}") from exc
        return cls(
            name=name,
            host=norm_host,
            cidr=str(network) if network is not None else None,
            ports=_parse_ports(ports),
            _network=network,
        )

    def _host_matches(self, host: str) -> bool:
        if self.host is None:
            return True
        if self.host.startswith("*."):
            base = self.host[2:]
            # Wildcard matches a strict subdomain, never the apex itself.
            return host != base and host.endswith("." + base)
        return host == self.host

    def _ip_matches(self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None) -> bool:
        if self._network is None:
            return True
        if ip is None:
            return False
        if ip.version != self._network.version:
            return False
        return ip in self._network

    def _port_matches(self, port: int) -> bool:
        if not self.ports:
            return True
        return any(lo <= port <= hi for lo, hi in self.ports)

    def matches(
        self,
        host: str,
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
        port: int,
    ) -> bool:
        """True when this rule permits ``(host, ip, port)``."""
        return self._host_matches(host) and self._ip_matches(ip) and self._port_matches(port)


@dataclass(frozen=True)
class EgressDecision:
    """The verdict for one outbound connection."""

    decision: str  # DECISION_ALLOW | DECISION_DENY
    host: str
    ip: str
    port: int
    matched_rule: str | None
    reason: str
    timestamp: float

    @property
    def allowed(self) -> bool:
        return self.decision == DECISION_ALLOW

    def to_audit_record(self) -> dict[str, object]:
        """The exact mapping serialized as one audit-log line."""
        return {
            "timestamp": self.timestamp,
            "decision": self.decision,
            "host": self.host,
            "ip": self.ip,
            "port": self.port,
            "matched_rule": self.matched_rule,
            "reason": self.reason,
        }


def _resolve_log_path(explicit: str | os.PathLike[str] | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get(_ENV_AUDIT_LOG, "").strip()
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / _DEFAULT_LOG_NAME


class EgressPolicyEngine:
    """Deny-by-default egress policy engine with a durable audit log.

    Parameters
    ----------
    rules:
        Ordered allowlist. First matching rule wins. Empty => deny everything.
    audit_log_path:
        Explicit audit-log path. When ``None`` the path is taken from
        ``$THOMAS_EGRESS_AUDIT_LOG`` or a default temp file.
    clock:
        Injectable ``() -> float`` returning a POSIX timestamp; defaults to
        :func:`time.time`. Injecting a fixed clock makes decisions deterministic.
    """

    def __init__(
        self,
        rules: Sequence[EgressRule] | None = None,
        *,
        audit_log_path: str | os.PathLike[str] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._rules: tuple[EgressRule, ...] = tuple(rules or ())
        self._clock: Callable[[], float] = clock or time.time
        self._audit_path = _resolve_log_path(audit_log_path)
        self._lock = threading.Lock()
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def rules(self) -> tuple[EgressRule, ...]:
        return self._rules

    @property
    def audit_log_path(self) -> Path:
        return self._audit_path

    def decide(self, host: str, ip: str | None, port: int) -> EgressDecision:
        """Decide allow/deny for one connection and append it to the audit log.

        ``ip`` may be ``None`` when the destination has not been resolved; in
        that case cidr rules cannot match (they require an ip) but host/port
        rules still can.
        """
        norm_host = _normalize_host(host)
        parsed_ip = self._parse_ip(ip)
        parsed_port = self._parse_port(port)

        decision = self._evaluate(norm_host, parsed_ip, parsed_port, ip)
        self._append_audit(decision)
        return decision

    def _evaluate(
        self,
        host: str,
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
        port: int,
        raw_ip: str | None,
    ) -> EgressDecision:
        ts = float(self._clock())
        ip_text = str(ip) if ip is not None else (raw_ip or "")
        for rule in self._rules:
            if rule.matches(host, ip, port):
                return EgressDecision(
                    decision=DECISION_ALLOW,
                    host=host,
                    ip=ip_text,
                    port=port,
                    matched_rule=rule.name,
                    reason=f"allowed by rule {rule.name!r}",
                    timestamp=ts,
                )
        return EgressDecision(
            decision=DECISION_DENY,
            host=host,
            ip=ip_text,
            port=port,
            matched_rule=None,
            reason=REASON_DEFAULT_DENY,
            timestamp=ts,
        )

    @staticmethod
    def _parse_ip(
        ip: str | None,
    ) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
        if ip is None:
            return None
        text = ip.strip()
        if not text:
            return None
        try:
            return ipaddress.ip_address(text)
        except ValueError as exc:
            raise InvalidConnectionError(f"invalid ip {ip!r}") from exc

    @staticmethod
    def _parse_port(port: int) -> int:
        if isinstance(port, bool) or not isinstance(port, int):
            raise InvalidConnectionError(f"invalid port {port!r}")
        if not 0 <= port <= 65535:
            raise InvalidConnectionError(f"port out of range [0, 65535]: {port!r}")
        return port

    def _append_audit(self, decision: EgressDecision) -> None:
        """Append one decision as a JSON line; flush + fsync for durability."""
        line = json.dumps(decision.to_audit_record(), sort_keys=True, separators=(",", ":"))
        with self._lock:
            with open(self._audit_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    # Best-effort durability: some filesystems / handles reject
                    # fsync. The line is already flushed to the OS buffer.
                    logger.debug("fsync unavailable for %s", self._audit_path)

    def read_audit_log(self) -> list[dict[str, object]]:
        """Read every audit record back in write order (empty if no log yet)."""
        if not self._audit_path.exists():
            return []
        records: list[dict[str, object]] = []
        with open(self._audit_path, encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if raw:
                    records.append(json.loads(raw))
        return records
