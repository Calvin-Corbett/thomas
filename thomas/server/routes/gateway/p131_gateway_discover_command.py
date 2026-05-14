"""Gateway discovery (LAN).

This implements Thomas's *gateway discover* behavior.

The command is best-effort: it uses mDNS/DNS-SD (Bonjour-style discovery) to
collect any Thomas Gateway beacons being advertised on the local network.

Design constraints:
  * No third-party dependencies (stdlib + aiohttp only).
  * Deterministic, machine-readable errors.
  * Clear input/output contracts (dataclasses).
"""

from __future__ import annotations

import asyncio
import socket
import struct
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from aiohttp import web

# --- Public contracts -----------------------------------------------------------------


DEFAULT_DISCOVERY_TIMEOUT_MS = 2000
DEFAULT_DISCOVERY_DOMAIN = "local."

# Thomas-native DNS-SD beacon type. (Do not reuse other projects' service names.)
DEFAULT_SERVICE_TYPE = "_thomas-gw._tcp"

DISCOVER_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class GatewayDiscoverRequest:
    """Input contract for gateway discovery."""

    timeout_ms: int = DEFAULT_DISCOVERY_TIMEOUT_MS
    domain: str = DEFAULT_DISCOVERY_DOMAIN
    service_type: str = DEFAULT_SERVICE_TYPE


@dataclass(frozen=True, slots=True)
class GatewayBeacon:
    """A discovered gateway beacon."""

    instance_name: str
    host: str | None = None
    port: int | None = None
    addresses: list[str] = field(default_factory=list)
    ws_url: str | None = None
    txt: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GatewayDiscoverResult:
    """Output contract for gateway discovery."""

    service_type: str
    domain: str
    timeout_ms: int
    elapsed_ms: int
    beacons: list[GatewayBeacon]


@dataclass(frozen=True, slots=True)
class GatewayDiscoverErrorBody:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class GatewayDiscoverError(RuntimeError):
    """Base class for deterministic gateway discovery errors."""

    code = "gateway_discover_error"
    http_status = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details: dict[str, Any] = details or {}

    def to_body(self) -> GatewayDiscoverErrorBody:
        return GatewayDiscoverErrorBody(code=self.code, message=str(self), details=self.details)


class GatewayDiscoverInvalidInputError(GatewayDiscoverError):
    code = "invalid_input"
    http_status = 400


class GatewayDiscoverExternalFailureError(GatewayDiscoverError):
    code = "external_failure"
    http_status = 502


# --- Route ---------------------------------------------------------------------------


ROUTE_PATH = "/gateway/discover"

# RouteTableDef is a common Thomas pattern; exporting it improves loader compatibility.
routes = web.RouteTableDef()


@routes.get(ROUTE_PATH)
async def handle_gateway_discover(request: web.Request) -> web.Response:
    """HTTP handler: GET /gateway/discover

    Query params:
      - timeout_ms | timeout: integer milliseconds
      - domain: DNS-SD domain suffix (default: local.)
      - service_type | service: service type (default: _thomas-gw._tcp)
      - schema: truthy value to return a JSON schema document

    Responses:
      * 200: {"ok": true, "result": GatewayDiscoverResult}
      * 4xx/5xx: {"ok": false, "error": GatewayDiscoverErrorBody}
    """

    if _truthy(request.rel_url.query.get("schema")):
        return web.json_response({"ok": True, "schema": get_discover_schema()})

    try:
        req = _parse_http_request(request)
    except GatewayDiscoverError as e:
        return web.json_response({"ok": False, "error": asdict(e.to_body())}, status=e.http_status)

    try:
        # Discovery uses blocking sockets; keep the event loop responsive.
        result: GatewayDiscoverResult = await asyncio.to_thread(discover_gateways, req)
    except GatewayDiscoverError as e:
        return web.json_response({"ok": False, "error": asdict(e.to_body())}, status=e.http_status)
    except Exception as e:  # pragma: no cover
        body = GatewayDiscoverErrorBody(
            code="internal_error",
            message="Unexpected server error during gateway discovery",
            details={"exc": type(e).__name__},
        )
        return web.json_response({"ok": False, "error": asdict(body)}, status=500)

    return web.json_response({"ok": True, "result": _result_to_dict(result)})


def add_routes(app: web.Application) -> None:
    """Register aiohttp routes (preferred entrypoint)."""
    app.router.add_routes(routes)


# Common alias names used by various Thomas route loaders.
register_routes = add_routes
register = add_routes

# Declarative form some loaders prefer.
ROUTES: list[tuple[str, str, Any]] = [("GET", ROUTE_PATH, handle_gateway_discover)]


def get_discover_schema() -> dict[str, Any]:
    """Return a small JSON-schema-like document for automation and introspection.

    This is intentionally lightweight (not a full OpenAPI generator).
    """
    return {
        "version": DISCOVER_SCHEMA_VERSION,
        "route": {"method": "GET", "path": ROUTE_PATH},
        "query": {
            "timeout_ms": {"type": "integer", "default": DEFAULT_DISCOVERY_TIMEOUT_MS, "min": 1, "max": 120000},
            "timeout": {"type": "integer", "alias_for": "timeout_ms"},
            "domain": {"type": "string", "default": DEFAULT_DISCOVERY_DOMAIN, "must_end_with": "."},
            "service_type": {"type": "string", "default": DEFAULT_SERVICE_TYPE},
            "service": {"type": "string", "alias_for": "service_type"},
            "schema": {"type": "boolean", "default": False},
        },
        "response": {
            "success": {
                "ok": True,
                "result": {
                    "service_type": "string",
                    "domain": "string",
                    "timeout_ms": "integer",
                    "elapsed_ms": "integer",
                    "beacons": [
                        {
                            "instance_name": "string",
                            "host": "string|null",
                            "port": "integer|null",
                            "addresses": ["string"],
                            "ws_url": "string|null",
                            "txt": {"key": "value"},
                        }
                    ],
                },
            },
            "error": {"ok": False, "error": {"code": "string", "message": "string", "details": {}}},
        },
    }


# --- Core behavior -------------------------------------------------------------------


def discover_gateways(req: GatewayDiscoverRequest) -> GatewayDiscoverResult:
    """Discover gateways advertised on the LAN via mDNS/DNS-SD."""

    _validate_request(req)
    started = time.monotonic()
    try:
        beacons = _discover_via_mdns(req.service_type, req.domain, req.timeout_ms)
    except OSError as e:
        raise GatewayDiscoverExternalFailureError(
            "mDNS discovery failed",
            details={"errno": getattr(e, "errno", None), "exc": type(e).__name__},
        ) from e
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return GatewayDiscoverResult(
        service_type=req.service_type,
        domain=req.domain,
        timeout_ms=req.timeout_ms,
        elapsed_ms=elapsed_ms,
        beacons=beacons,
    )


def _validate_request(req: GatewayDiscoverRequest) -> None:
    if not isinstance(req.timeout_ms, int):
        raise GatewayDiscoverInvalidInputError(
            "timeout_ms must be an integer (milliseconds)",
            details={"timeout_ms": req.timeout_ms},
        )
    if req.timeout_ms <= 0:
        raise GatewayDiscoverInvalidInputError(
            "timeout_ms must be > 0",
            details={"timeout_ms": req.timeout_ms},
        )
    if req.timeout_ms > 120_000:
        raise GatewayDiscoverInvalidInputError(
            "timeout_ms is unreasonably large",
            details={"timeout_ms": req.timeout_ms, "max": 120_000},
        )
    if not isinstance(req.domain, str) or not req.domain:
        raise GatewayDiscoverInvalidInputError("domain must be a non-empty string")
    if not req.domain.endswith("."):
        raise GatewayDiscoverInvalidInputError(
            "domain must be a fully-qualified DNS suffix ending with '.'",
            details={"domain": req.domain},
        )
    if not isinstance(req.service_type, str) or not req.service_type:
        raise GatewayDiscoverInvalidInputError("service_type must be a non-empty string")
    if not req.service_type.startswith("_") or "._tcp" not in req.service_type:
        raise GatewayDiscoverInvalidInputError(
            "service_type must look like a DNS-SD service type (e.g. _name._tcp)",
            details={"service_type": req.service_type},
        )


def _parse_http_request(request: web.Request) -> GatewayDiscoverRequest:
    q = request.rel_url.query
    timeout_raw = q.get("timeout_ms") or q.get("timeout")
    domain = q.get("domain") or DEFAULT_DISCOVERY_DOMAIN
    service_type = q.get("service_type") or q.get("service") or DEFAULT_SERVICE_TYPE

    timeout_ms = DEFAULT_DISCOVERY_TIMEOUT_MS
    if timeout_raw is not None:
        try:
            timeout_ms = int(timeout_raw)
        except Exception as e:
            raise GatewayDiscoverInvalidInputError(
                "timeout_ms must be an integer",
                details={"timeout_ms": timeout_raw},
            ) from e

    return GatewayDiscoverRequest(timeout_ms=timeout_ms, domain=domain, service_type=service_type)


def _result_to_dict(result: GatewayDiscoverResult) -> dict[str, Any]:
    return {
        "service_type": result.service_type,
        "domain": result.domain,
        "timeout_ms": result.timeout_ms,
        "elapsed_ms": result.elapsed_ms,
        "beacons": [asdict(b) for b in result.beacons],
    }


# --- mDNS/DNS-SD implementation ------------------------------------------------------


_MDNS_ADDR_V4 = "224.0.0.251"
_MDNS_PORT = 5353


@dataclass(frozen=True, slots=True)
class _DecodedRecord:
    name: str
    rtype: int
    ttl: int
    data: Any


def _discover_via_mdns(service_type: str, domain: str, timeout_ms: int) -> list[GatewayBeacon]:
    """Best-effort DNS-SD browse + resolve.

    Implementation notes:
      * IPv4-only to keep it dependency-free.
      * Uses QU (unicast-response) bit to encourage unicast responses.
      * Attempts a follow-up SRV/TXT query for instances missing details.
    """

    service_fqdn = _normalize_fqdn(f"{service_type}.{domain}")

    # Split budget: give browse slightly more time.
    stage1_budget = max(200, min(timeout_ms, int(timeout_ms * 0.6)))
    stage2_budget = max(0, timeout_ms - stage1_budget)

    # 1) Browse PTR records for the service type.
    q1 = _build_dns_query([(service_fqdn, 12)])  # PTR
    msgs = _mdns_exchange(q1, stage1_budget)
    records = _decode_records_from_messages(msgs)

    instances = sorted(
        {
            r.data
            for r in records
            if r.rtype == 12 and r.name == service_fqdn and isinstance(r.data, str) and r.data
        }
    )

    # 2) Follow-up SRV/TXT for instances that didn't arrive with details.
    missing: list[str] = []
    for inst in instances:
        if not any(r.rtype == 33 and r.name == inst for r in records):
            missing.append(inst)

    if missing and stage2_budget > 0:
        q2_questions: list[tuple[str, int]] = []
        for inst in missing:
            q2_questions.append((inst, 33))  # SRV
            q2_questions.append((inst, 16))  # TXT
        q2 = _build_dns_query(q2_questions)
        msgs2 = _mdns_exchange(q2, stage2_budget)
        records.extend(_decode_records_from_messages(msgs2))

    # 3) Build beacons.
    beacons: list[GatewayBeacon] = []
    for inst in instances:
        host, port = _find_srv(records, inst)
        txt = _merge_txt(records, inst)

        addresses: list[str] = []
        if host:
            # Prefer A/AAAA from the mDNS response; if missing, fall back to local resolver.
            addresses = [
                r.data
                for r in records
                if r.name == host and r.rtype in (1, 28) and isinstance(r.data, str) and r.data
            ]
            if not addresses:
                addresses = _best_effort_resolve(host)

        ws_url = _infer_ws_url(host=host, port=port, txt=txt)

        beacons.append(
            GatewayBeacon(
                instance_name=_strip_dot(inst),
                host=_strip_dot(host) if host else None,
                port=port,
                addresses=addresses,
                ws_url=ws_url,
                txt=txt,
            )
        )

    return beacons


def _best_effort_resolve(host: str) -> list[str]:
    """Attempt to resolve hostnames into IPs without failing discovery."""

    host = _strip_dot(host)
    out: list[str] = []
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        for fam, _socktype, _proto, _canon, sockaddr in infos:
            if fam == socket.AF_INET and isinstance(sockaddr, tuple) and len(sockaddr) >= 1 or fam == socket.AF_INET6 and isinstance(sockaddr, tuple) and len(sockaddr) >= 1:
                ip = sockaddr[0]
                if ip and ip not in out:
                    out.append(ip)
    except Exception:
        return []
    return out


def _find_srv(records: Sequence[_DecodedRecord], instance_fqdn: str) -> tuple[str | None, int | None]:
    for r in records:
        if r.rtype != 33 or r.name != instance_fqdn:
            continue
        if isinstance(r.data, tuple) and len(r.data) == 2:
            host, port = r.data
            if isinstance(host, str) and isinstance(port, int):
                return host, port
    return None, None


def _merge_txt(records: Sequence[_DecodedRecord], name_fqdn: str) -> dict[str, str]:
    merged: dict[str, str] = {}
    for r in records:
        if r.rtype != 16 or r.name != name_fqdn:
            continue
        if isinstance(r.data, dict):
            merged.update({str(k): str(v) for k, v in r.data.items()})
    return merged


def _infer_ws_url(*, host: str | None, port: int | None, txt: dict[str, str]) -> str | None:
    if not host or not port:
        return None
    tls_hint = (
        txt.get("gateway_tls")
        or txt.get("tls")
        or txt.get("wss")
        or txt.get("gatewayTls")
        or txt.get("gateway_tls_enabled")
    )
    scheme = "wss" if _truthy(tls_hint) else "ws"
    return f"{scheme}://{_strip_dot(host)}:{port}"


def _truthy(val: str | None) -> bool:
    if val is None:
        return False
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_fqdn(name: str) -> str:
    name = name.strip()
    if not name.endswith("."):
        name += "."
    return name


def _strip_dot(name: str) -> str:
    return name[:-1] if name.endswith(".") else name


def _mdns_exchange(query: bytes, timeout_ms: int) -> list[bytes]:
    """Send a single mDNS query and collect responses until timeout.

    We use an ephemeral UDP port to encourage QU (unicast) responses.
    """
    if timeout_ms <= 0:
        return []
    timeout_s = max(0.001, timeout_ms / 1000.0)
    end = time.monotonic() + timeout_s
    responses: list[bytes] = []

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        sock.bind(("", 0))

        sock.sendto(query, (_MDNS_ADDR_V4, _MDNS_PORT))
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(65535)
            except TimeoutError:
                break
            responses.append(data)

    return responses


def _build_dns_query(questions: Iterable[tuple[str, int]]) -> bytes:
    """Build a minimal mDNS query with the QU (unicast-response) bit set."""

    q_list = list(questions)
    header = struct.pack("!HHHHHH", 0, 0, len(q_list), 0, 0, 0)
    body = bytearray()
    for qname, qtype in q_list:
        body.extend(_encode_dns_name(_normalize_fqdn(qname)))
        qclass = 0x8001  # IN + QU bit
        body.extend(struct.pack("!HH", qtype, qclass))
    return header + bytes(body)


def _encode_dns_name(name: str) -> bytes:
    name = name.strip(".")
    if not name:
        return b"\x00"
    out = bytearray()
    for label in name.split("."):
        b = label.encode("utf-8")
        if len(b) > 63:
            raise GatewayDiscoverInvalidInputError("DNS label too long", details={"label": label})
        out.append(len(b))
        out.extend(b)
    out.append(0)
    return bytes(out)


def _decode_records_from_messages(messages: Iterable[bytes]) -> list[_DecodedRecord]:
    out: list[_DecodedRecord] = []
    for msg in messages:
        try:
            out.extend(_decode_dns_message_records(msg))
        except Exception:
            # Discovery is best-effort; ignore malformed messages.
            continue
    return out


def _decode_dns_message_records(data: bytes) -> list[_DecodedRecord]:
    if len(data) < 12:
        return []
    _id, _flags, qdcount, ancount, nscount, arcount = struct.unpack_from("!HHHHHH", data, 0)
    offset = 12

    # Skip questions.
    for _ in range(qdcount):
        _qname, offset = _decode_dns_name(data, offset)
        offset += 4

    total_rr = ancount + nscount + arcount
    out: list[_DecodedRecord] = []
    for _ in range(total_rr):
        name, offset = _decode_dns_name(data, offset)
        if offset + 10 > len(data):
            break
        rtype, _rclass, ttl, rdlength = struct.unpack_from("!HHIH", data, offset)
        offset += 10
        rdata_offset = offset
        offset += rdlength
        if rdata_offset + rdlength > len(data):
            break

        decoded: Any = None
        if rtype == 12:  # PTR
            target, _ = _decode_dns_name(data, rdata_offset)
            decoded = target
        elif rtype == 33:  # SRV
            if rdlength >= 6:
                _pri, _w, port = struct.unpack_from("!HHH", data, rdata_offset)
                target, _ = _decode_dns_name(data, rdata_offset + 6)
                decoded = (target, int(port))
        elif rtype == 16:  # TXT
            raw = data[rdata_offset : rdata_offset + rdlength]
            decoded = _decode_txt(raw)
        elif rtype == 1 and rdlength == 4:  # A
            decoded = socket.inet_ntoa(data[rdata_offset : rdata_offset + 4])
        elif rtype == 28 and rdlength == 16:  # AAAA
            try:
                decoded = socket.inet_ntop(socket.AF_INET6, data[rdata_offset : rdata_offset + 16])
            except OSError:
                decoded = None

        out.append(_DecodedRecord(name=name, rtype=rtype, ttl=ttl, data=decoded))

    return out


def _decode_txt(raw: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    i = 0
    while i < len(raw):
        ln = raw[i]
        i += 1
        if ln == 0:
            continue
        if i + ln > len(raw):
            break
        entry = raw[i : i + ln].decode("utf-8", "replace")
        i += ln
        if "=" in entry:
            k, v = entry.split("=", 1)
            out[k] = v
        else:
            out[entry] = ""
    return out


def _decode_dns_name(data: bytes, offset: int) -> tuple[str, int]:
    """Decode a possibly-compressed DNS name. Returns (fqdn, new_offset)."""

    labels: list[str] = []
    jumped = False
    jump_offset = offset
    seen: set[int] = set()

    while True:
        if offset >= len(data):
            return "", offset
        if offset in seen:
            return "", offset
        seen.add(offset)

        length = data[offset]
        if length == 0:
            offset += 1
            break

        # Compression pointer
        if (length & 0xC0) == 0xC0:
            if offset + 1 >= len(data):
                return "", offset + 1
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if not jumped:
                jump_offset = offset + 2
                jumped = True
            offset = pointer
            continue

        offset += 1
        if offset + length > len(data):
            return "", offset + length
        labels.append(data[offset : offset + length].decode("utf-8", "replace"))
        offset += length

    name = ".".join(labels)
    if name:
        name += "."
    return name, (jump_offset if jumped else offset)
