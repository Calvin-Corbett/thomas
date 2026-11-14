"""The caged Thomas's search broker: web search and page reading without opening the cage.

The network fence (enable_network_fence.ps1) lets the cage account reach loopback
and nothing else; the egress proxy (egress_proxy.py) tunnels it only to the hosts
in the admin pin, and no search engine is on that list. This broker runs inside
the promoter service as you, on 127.0.0.1:8896, and does two things for it:

* ``POST /search {"query", "count", "freshness"?}`` searches with the providers
  Thomas already has and returns only ``[{title, url, snippet}]``. Every returned
  url becomes a ticket for an hour.
* ``POST /read {"url"}`` reads a page only when that exact url holds a live
  ticket, so a caller cannot add anything to it and carry data out. The request
  is a bare GET: no body, and none of the caller's headers or cookies. The name
  is resolved here and every address checked -- loopback, private, link-local,
  site-local, multicast, reserved and this machine's own addresses are refused --
  and the connection goes to the address that was checked, so a name that answers
  differently a second time (DNS rebinding) cannot reach your machine or your
  network. At most three redirects, each checked the same way; 2 MB; text only.

Anything refused gets a plain reason: "not a search result", "private address",
"too large".

Not refused: your router's public IPv4 address, which this machine does not know.
A name resolving to it reaches, through the router's hairpin NAT, any port you
forward to a machine on your LAN and whatever the router answers on that address,
and some routers treat such a hairpinned connection as coming from inside.
"""

from __future__ import annotations

import asyncio
import codecs
import http.client
import ipaddress
import logging
import socket
import ssl
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from aiohttp import web
from scripts.cage import egress_proxy

PORT = 8896
ENV_VAR = "THOMAS_SEARCH_BROKER"
TICKET_TTL_S = 3600.0
MAX_TICKETS = 20_000
MAX_REDIRECTS = 3
MAX_BYTES = 2_000_000
SEARCHES_PER_MINUTE = 60
READS_PER_MINUTE = 120
NOT_A_RESULT_DETAIL = "only a url a search returned in the last hour, exactly as returned, can be read"
FRESHNESS = frozenset({None, "pd", "pw", "pm", "py"})  # web.search's own: past day, week, month, year
_MAX_QUERY_CHARS = 400
_MAX_URL_CHARS = 4096
_MAX_TEXT_CHARS = 200_000
_TIMEOUT_S = 10.0
_READ_DEADLINE_S = 30.0
_USER_AGENT = "Mozilla/5.0 (compatible; Thomas/1.0; search broker)"
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_TEXT_TYPES = frozenset({"application/json", "application/xml", "application/xhtml+xml"})
_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
_TLS = ssl.create_default_context()

log = logging.getLogger("thomas.search_broker")


@dataclass(frozen=True)
class Page:
    """What one GET returned: the status, lower-cased headers, and at most MAX_BYTES + 1 of the body."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


class Refused(Exception):
    """A request the broker will not carry out, with the plain reason it gives the caller."""

    def __init__(self, reason: str, detail: str = "", status: int = 403) -> None:
        super().__init__(reason)
        self.reason, self.detail, self.status = reason, detail, status


def address_refusal(address: str, own: frozenset[str] = frozenset()) -> str | None:
    """Why the broker will not connect to *address*; None only for a public address outside your network."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return "not an address"
    checks: list[Any] = [ip]
    if isinstance(ip, ipaddress.IPv6Address):
        # An IPv4 address carried inside IPv6 is judged as the IPv4 address it reaches.
        embedded = [ip.ipv4_mapped, ip.sixtofour, *(ip.teredo or ())]
        if any(ip in net for net in _NAT64):
            embedded.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        checks = [each for each in embedded if each is not None] + checks
    # On IPv6 your router and the devices behind it have global addresses too: the
    # /56 your provider delegated around this machine's own is your network.
    home = []
    for mine in own:
        try:
            home += [ipaddress.ip_network(f"{mine}/56", strict=False)] if ":" in mine else []
        except ValueError:
            continue
    for each in checks:
        for reason, hit in (
            ("loopback address", each.is_loopback),
            ("link-local address", each.is_link_local),
            ("site-local address", getattr(each, "is_site_local", False)),  # fec0::/10, which Python calls global
            ("multicast address", each.is_multicast),
            ("unspecified address", each.is_unspecified),
            ("reserved address", each.is_reserved),
            ("private address", each.is_private or not each.is_global),
            ("this machine's own address", each.compressed in own),
            ("an address on your own network", any(each in net for net in home if net.version == each.version)),
        ):
            if hit:
                return reason
    return None


def own_addresses() -> frozenset[str]:
    """Every address this machine answers on, so a public one of its own is refused too."""
    found: set[str] = set()
    try:
        import psutil

        for addrs in psutil.net_if_addrs().values():
            found.update(a.address for a in addrs if a.family in (socket.AF_INET, socket.AF_INET6))
    except (ImportError, OSError):
        pass
    try:
        found.update(str(info[4][0]) for info in socket.getaddrinfo(socket.gethostname(), None))
    except OSError:
        pass
    normal: set[str] = set()
    for address in found:
        try:
            normal.add(ipaddress.ip_address(address.split("%", 1)[0]).compressed)
        except ValueError:
            continue
    return frozenset(normal)


def resolve_host(host: str, port: int) -> list[str]:
    """Every address *host* resolves to, in the resolver's order."""
    return list(dict.fromkeys(str(info[4][0]) for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))


class _PinnedHTTP(http.client.HTTPConnection):
    pinned = ""
    live: socket.socket | None = None  # kept: http.client drops .sock once a closing response starts

    def connect(self) -> None:
        # The address the broker checked -- never a second lookup of the name.
        self.sock = self.live = socket.create_connection((self.pinned, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    pinned = ""
    live: socket.socket | None = None

    def connect(self) -> None:
        sock = socket.create_connection((self.pinned, self.port), self.timeout)
        self.sock = self.live = _TLS.wrap_socket(sock, server_hostname=self.host, do_handshake_on_connect=False)
        self.sock.do_handshake()


def pinned_get(url: str, address: str, max_bytes: int) -> Page:
    """GET *url* over a connection to *address*; never follows a redirect, reads at most max_bytes + 1."""
    parts = urlsplit(url)
    secure = parts.scheme == "https"
    port = parts.port or (443 if secure else 80)
    host = str(parts.hostname or "").encode("idna").decode("ascii")
    conn = (
        _PinnedHTTPS(host, port, timeout=_TIMEOUT_S, context=_TLS)
        if secure
        else _PinnedHTTP(host, port, timeout=_TIMEOUT_S)
    )
    conn.pinned = address
    # A page that sends a byte just inside every socket timeout would hold this
    # thread for days. At the deadline the socket's timeout drops to nothing:
    # Windows does not wake a read already waiting, but that one ends within a
    # socket timeout and the next fails at once.
    expired = threading.Event()

    def cut() -> None:
        expired.set()
        try:
            if conn.live is not None:
                conn.live.settimeout(0.001)
        except OSError:
            pass

    cutoff = threading.Timer(_READ_DEADLINE_S, cut)
    cutoff.start()
    try:
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        conn.request(
            "GET",
            target,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5",
                "Connection": "close",
            },
        )
        resp = conn.getresponse()
        headers = {key.lower(): value for key, value in resp.getheaders()}
        chunks: list[bytes] = []
        total = 0
        wanted = 200 <= resp.status < 300 and _is_text(headers) and _declared_size(headers) <= max_bytes
        while wanted and total <= max_bytes and (chunk := resp.read1(min(65536, max_bytes + 1 - total))):
            chunks.append(chunk)
            total += len(chunk)
        if expired.is_set():
            raise Refused("too slow", f"the page took over {_READ_DEADLINE_S:g}s", 504)
        return Page(resp.status, headers, b"".join(chunks))
    except (OSError, ValueError, http.client.HTTPException) as exc:
        if expired.is_set():
            raise Refused("too slow", f"the page took over {_READ_DEADLINE_S:g}s", 504) from exc
        raise
    finally:
        cutoff.cancel()
        conn.close()


def _mime(headers: Mapping[str, str]) -> str:
    return str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()


def _is_text(headers: Mapping[str, str]) -> bool:
    mime = _mime(headers)
    return mime.startswith("text/") or mime in _TEXT_TYPES or mime.endswith(("+xml", "+json"))


def _declared_size(headers: Mapping[str, str]) -> int:
    try:
        return int(str(headers.get("content-length") or "0").strip())
    except ValueError:
        return 0


def _charset(headers: Mapping[str, str]) -> str:
    """The page's charset when it names a text encoding; otherwise utf-8.

    A page chooses this name, and Python also knows codecs that are not text
    (rot13, base64, zlib): decoding with one of those would fail, not read."""
    for param in str(headers.get("content-type") or "").split(";")[1:]:
        key, _, value = param.partition("=")
        if key.strip().lower() == "charset":
            try:
                info = codecs.lookup(value.strip().strip("\"'"))
            except LookupError:
                break
            return info.name if getattr(info, "_is_text_encoding", False) else "utf-8"
    return "utf-8"


def _decoded(body: bytes, charset: str) -> str:
    try:
        return body.decode(charset, errors="replace")
    except (LookupError, UnicodeError):  # "undefined" and "idna" are text codecs that refuse a page
        return body.decode("utf-8", errors="replace")


def _unwrapped(url: str) -> str:
    """The destination of a DuckDuckGo /l/?uddg= wrapper, so the ticket is for the real page."""
    url = "https:" + url if url.startswith("//") else url
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.netloc.lower().endswith("duckduckgo.com") and parts.path.startswith("/l/"):
        return parse_qs(parts.query).get("uddg", [""])[0]
    return url


def _rows(raw: Any, count: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, Mapping):
            continue
        url = _unwrapped(str(item.get("url") or "").strip())
        title = " ".join(str(item.get("title") or "").split())
        if not title or not url.startswith(("http://", "https://")) or len(url) > _MAX_URL_CHARS:
            continue
        if any(row["url"] == url for row in rows):
            continue
        snippet = " ".join(str(item.get("snippet") or item.get("description") or "").split())
        rows.append({"title": title[:300], "url": url, "snippet": snippet[:1000]})
        if len(rows) >= count:
            break
    return rows


def _checked_parts(url: str) -> Any:
    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError as exc:
        raise Refused("not a valid url", str(exc), 400) from exc
    if parts.scheme not in ("http", "https"):
        raise Refused("only http and https pages can be read", f"not a {parts.scheme or 'scheme-less'} url")
    if "@" in parts.netloc or any(ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in url) or not parts.hostname:
        raise Refused("not a valid url", "a user name, a space or a control character, or no host", 400)
    return parts


def _page_answer(url: str, page: Page, hops: int) -> dict[str, Any]:
    if not 200 <= page.status < 300:
        raise Refused(f"the page answered HTTP {page.status}", url, 502)
    if not _is_text(page.headers):
        raise Refused("not a text page", f"it is {_mime(page.headers) or 'unlabelled'}", 415)
    encoding = str(page.headers.get("content-encoding") or "identity").strip().lower()
    if encoding != "identity":
        raise Refused("not a text page", f"it came {encoding}-compressed", 415)
    if _declared_size(page.headers) > MAX_BYTES or len(page.body) > MAX_BYTES:
        raise Refused("too large", f"over {MAX_BYTES // 1_000_000} MB", 413)
    text, title = _decoded(page.body, _charset(page.headers)), ""
    if "html" in _mime(page.headers):
        from thomas.tools.web_search_providers import _extract_html

        extracted = _extract_html(text)
        text, title = str(extracted.get("text") or ""), str(extracted.get("title") or "")
    return {
        "ok": True,
        "url": url,
        "title": title,
        "text": text[:_MAX_TEXT_CHARS],
        "content_type": _mime(page.headers),
        "status": page.status,
        "redirects": hops,
    }


class _Window:
    """At most *limit* events in any sixty seconds."""

    def __init__(self, limit: int) -> None:
        self.limit, self.hits = limit, deque[float]()

    def allow(self, now: float) -> bool:
        while self.hits and now - self.hits[0] >= 60.0:
            self.hits.popleft()
        if len(self.hits) >= self.limit:
            return False
        self.hits.append(now)
        return True


async def _default_search(query: str, count: int, freshness: str | None = None) -> tuple[str, list[Any]]:
    """Thomas's own web.search providers, run here as you: DuckDuckGo, Brave with a key, then Bing."""
    from thomas.tools.resilient_web_search import ResilientWebSearchTool
    from thomas.tools.web_search import WebSearchTool

    direct = WebSearchTool()
    direct.use_search_broker = False  # this is the broker: search for real, never ask itself
    args: dict[str, Any] = {"query": query, "count": count, **({"freshness": freshness} if freshness else {})}
    result = await ResilientWebSearchTool(primary=direct).execute(args)
    if not result.ok:
        raise RuntimeError(result.error or "no results")
    data = result.data if isinstance(result.data, dict) else {}
    return str(data.get("provider") or ""), list(data.get("results") or [])


class Broker:
    """The two operations, with every check; build_app puts them on HTTP."""

    def __init__(
        self,
        *,
        search: Callable[[str, int, str | None], Awaitable[tuple[str, list[Any]]]] | None = None,
        resolve: Callable[[str, int], list[str]] = resolve_host,
        fetch: Callable[[str, str, int], Page] = pinned_get,
        own: Callable[[], frozenset[str]] = own_addresses,
        clock: Callable[[], float] = time.monotonic,
        note: Callable[[str], object] | None = None,
    ) -> None:
        self._search, self._resolve, self._fetch, self._own, self._clock = (
            search or _default_search,
            resolve,
            fetch,
            own,
            clock,
        )
        self._note = note or log.info
        self._tickets: OrderedDict[str, float] = OrderedDict()
        self._searches, self._reads = _Window(SEARCHES_PER_MINUTE), _Window(READS_PER_MINUTE)

    def is_ticketed(self, url: str) -> bool:
        expires = self._tickets.get(url)
        return expires is not None and expires > self._clock()

    async def search(self, body: Any) -> tuple[int, dict[str, Any]]:
        return await self._answer(self._do_search, body)

    async def read(self, body: Any) -> tuple[int, dict[str, Any]]:
        return await self._answer(self._do_read, body)

    async def _answer(
        self, work: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]], body: Any
    ) -> tuple[int, dict[str, Any]]:
        try:
            return 200, await work(body if isinstance(body, dict) else {})
        except Refused as refusal:
            self._note(f"search broker refused: {refusal.reason} {refusal.detail}".rstrip())
            return refusal.status, {"ok": False, "error": refusal.reason, "detail": refusal.detail}

    async def _do_search(self, body: dict[str, Any]) -> dict[str, Any]:
        now = self._clock()
        if not self._searches.allow(now):
            raise Refused("too many searches", f"at most {SEARCHES_PER_MINUTE} a minute", 429)
        # DuckDuckGo turns "!bang" and a leading "\" into a redirect to another site,
        # and the search client follows redirects: neither character reaches it.
        query = str(body.get("query") or "").replace("!", " ").replace("\\", " ")
        query = " ".join(query.split())[:_MAX_QUERY_CHARS]
        if not query:
            raise Refused("no query", status=400)
        try:
            count = max(1, min(10, int(body.get("count") or 5)))
        except (TypeError, ValueError):
            count = 5
        freshness = body.get("freshness") or None
        if freshness not in FRESHNESS:
            raise Refused("Invalid freshness. Allowed: pd, pw, pm, py.", status=400)
        try:
            provider, raw = await self._search(query, count, freshness)
        except (OSError, RuntimeError, ValueError) as exc:
            raise Refused("the search failed", f"{type(exc).__name__}: {exc}", 502) from exc
        rows = _rows(raw, count)
        for row in rows:
            self._tickets.pop(row["url"], None)
            self._tickets[row["url"]] = now + TICKET_TTL_S
        # One lifetime for every ticket, so the oldest is always first.
        while self._tickets and (len(self._tickets) > MAX_TICKETS or next(iter(self._tickets.values())) <= now):
            self._tickets.popitem(last=False)
        return {"ok": True, "provider": provider, "query": query, "results": rows}

    async def _do_read(self, body: dict[str, Any]) -> dict[str, Any]:
        if not self._reads.allow(self._clock()):
            raise Refused("too many reads", f"at most {READS_PER_MINUTE} a minute", 429)
        url = body.get("url")
        if not isinstance(url, str) or not url or len(url) > _MAX_URL_CHARS:
            raise Refused("not a valid url", status=400)
        if not self.is_ticketed(url):
            raise Refused("not a search result", NOT_A_RESULT_DETAIL)
        current, hops = url, 0
        while True:
            address = await asyncio.to_thread(self._checked_address, current)
            try:
                page = await asyncio.to_thread(self._fetch, current, address, MAX_BYTES)
            except (OSError, ValueError, http.client.HTTPException) as exc:
                raise Refused("the page could not be read", f"{type(exc).__name__}: {exc}", 502) from exc
            location = str(page.headers.get("location") or "").strip()
            if page.status not in _REDIRECTS or not location:
                return _page_answer(current, page, hops)
            hops += 1
            if hops > MAX_REDIRECTS:
                raise Refused("too many redirects", f"more than {MAX_REDIRECTS}", 502)
            current = urljoin(current, location).split("#", 1)[0]

    def _checked_address(self, url: str) -> str:
        """Parse, resolve and check: the one address the connection will go to."""
        parts = _checked_parts(url)
        host = str(parts.hostname)
        try:
            addresses = self._resolve(host, parts.port or (443 if parts.scheme == "https" else 80))
        except (OSError, UnicodeError) as exc:
            raise Refused("the name did not resolve", f"{host}: {exc}", 502) from exc
        if not addresses:
            raise Refused("the name did not resolve", host, 502)
        own = self._own()
        for address in addresses:
            reason = address_refusal(address, own)
            if reason:
                raise Refused(reason, f"{host} is {address}")
        return addresses[0]


def build_app(broker: Broker) -> web.Application:
    """The HTTP face: two JSON POST routes, for local programs only."""

    @web.middleware
    async def local_only(request: web.Request, handler: Any) -> web.StreamResponse:
        # A web page in your browser can post to loopback too. It always sends an
        # Origin, it cannot send JSON without a preflight nothing here answers, and
        # after a DNS rebind its Host is its own name, not a loopback one.
        host = str(request.host or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in _LOOPBACK or "Origin" in request.headers:
            return web.json_response({"ok": False, "error": "not a local caller"}, status=403)
        if request.content_type != "application/json":
            return web.json_response({"ok": False, "error": "JSON only"}, status=415)
        return await handler(request)

    async def answer(
        request: web.Request, work: Callable[[Any], Awaitable[tuple[int, dict[str, Any]]]]
    ) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            body = None
        status, payload = await work(body)
        return web.json_response(payload, status=status)

    async def search(request: web.Request) -> web.Response:
        return await answer(request, broker.search)

    async def read(request: web.Request) -> web.Response:
        return await answer(request, broker.read)

    app = web.Application(client_max_size=16 * 1024, middlewares=[local_only])
    app.router.add_post("/search", search)
    app.router.add_post("/read", read)
    return app


async def serve(broker: Broker | None = None, host: str = "127.0.0.1", port: int = PORT) -> web.AppRunner:
    """Start listening. Loopback only: the broker serves this machine's cage, never the LAN."""
    if host not in _LOOPBACK:
        raise ValueError(f"the search broker listens on loopback only, not {host}")
    runner = web.AppRunner(build_app(broker or Broker()), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner


def serve_forever(
    *,
    stop: threading.Event | None = None,
    log: Callable[[str], object] | None = None,
    host: str = "127.0.0.1",
    port: int = PORT,
) -> None:
    """Serve on this thread's own event loop until *stop* is set.

    Raises when it cannot listen (an OSError when the port is taken). The
    promoter service runs this in a thread of its own and starts it again a
    minute later (promoter_service._BrokerKeeper), so the broker heals itself
    and nothing here can reach the egress proxy's thread.
    """
    say = log or globals()["log"].info
    stop = stop or threading.Event()

    async def main() -> None:
        runner = await serve(Broker(note=say), host, port)
        say(f"search broker listening on {host}:{port}")
        try:
            while not stop.is_set():
                await asyncio.sleep(0.5)
        finally:
            await runner.cleanup()

    asyncio.run(main())


def broker_env(pin_root: Path | None = None) -> dict[str, str]:
    """Where a caged process finds the broker, once the fence is pinned; else nothing."""
    return {ENV_VAR: f"http://127.0.0.1:{PORT}"} if egress_proxy.egress_env(pin_root) else {}


__all__ = [
    "ENV_VAR",
    "PORT",
    "Broker",
    "Page",
    "Refused",
    "address_refusal",
    "broker_env",
    "build_app",
    "pinned_get",
    "serve",
    "serve_forever",
]
