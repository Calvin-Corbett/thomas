"""The caged Thomas can search the web and read what it found, without opening the cage.

You asked: "I don't want to give up anything. So find a solution." The network
fence lets the caged Thomas reach the model providers and nothing else, so
web.search, the browser shell's results page and page reading all failed inside
it. The search broker (scripts/cage/search_broker.py) runs as you beside the
egress proxy: it searches, and it reads a page only when that exact url came back
as a search result, from a public address it checked and then connected to.
These tests drive its real handlers with a stubbed search engine, resolver and
fetcher; nothing leaves this machine.
"""

from __future__ import annotations

import asyncio
import http.server
import ipaddress
import socket
import threading
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import pytest
from aiohttp.test_utils import TestClient, TestServer
from scripts.cage import search_broker as sb

PUBLIC = "93.184.216.34"  # a public address; nothing here ever connects to it
OWN = "93.184.216.99"  # stands in for a public address of this machine's own
OWN_V6 = "2601:600:8a00:1234::abcd"  # and its global IPv6 one: the LAN around it is global too
HTML = (
    b"<html><head><title>Cage notes</title></head><body><article><p>"
    + b"The fence holds. " * 40
    + b"</p></article></body></html>"
)


def _html(body: bytes = HTML, **headers: str) -> sb.Page:
    return sb.Page(200, {"content-type": "text/html; charset=utf-8", **headers}, body)


# --- What the broker connects to, and how it reads ------------------------------


@pytest.mark.parametrize(
    ("address", "reason"),
    [
        ("127.0.0.1", "loopback address"),
        ("::1", "loopback address"),
        ("::ffff:127.0.0.1", "loopback address"),
        ("10.0.0.8", "private address"),
        ("172.16.4.4", "private address"),
        ("192.168.1.1", "private address"),
        ("100.64.0.1", "private address"),
        ("fc00::5", "private address"),
        ("64:ff9b::a00:1", "private address"),  # NAT64 for 10.0.0.1
        ("2002:c0a8:101::1", "private address"),  # 6to4 for 192.168.1.1
        ("169.254.169.254", "link-local address"),
        ("fe80::1", "link-local address"),
        ("fec0::1", "site-local address"),  # deprecated, and Python counts it as global
        ("224.0.0.251", "multicast address"),
        ("ff02::1", "multicast address"),
        ("240.0.0.1", "reserved address"),
        ("0.0.0.0", "unspecified address"),
        ("::", "unspecified address"),
        (OWN, "this machine's own address"),
        (OWN_V6, "this machine's own address"),
        ("2601:600:8a00:1234::1", "an address on your own network"),
        ("2601:600:8a00:12ff::7", "an address on your own network"),
        ("localhost", "not an address"),
    ],
)
def test_an_address_inside_is_refused(address: str, reason: str) -> None:
    assert sb.address_refusal(address, frozenset({OWN, OWN_V6})) == reason


@pytest.mark.parametrize("address", [PUBLIC, "2606:4700:4700::1111", "2601:600:8a00:1300::1"])
def test_a_public_address_outside_your_network_is_allowed(address: str) -> None:
    assert sb.address_refusal(address, frozenset({OWN, OWN_V6})) is None


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("file:///C:/Windows/win.ini", "only http and https pages can be read"),
        ("ftp://example.com/x", "only http and https pages can be read"),
        ("http://user:pw@example.com/", "not a valid url"),
        ("http://example.com/a b", "not a valid url"),
        ("http://example.com:99999/", "not a valid url"),
        ("http:///no-host", "not a valid url"),
    ],
)
def test_only_a_plain_http_url_is_read(url: str, reason: str) -> None:
    with pytest.raises(sb.Refused) as refused:
        sb._checked_parts(url)

    assert refused.value.reason == reason


def test_the_real_fetcher_dials_the_checked_address_not_the_name(monkeypatch: pytest.MonkeyPatch) -> None:
    dialed: list[tuple[str, int]] = []

    def no_lookup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the fetcher looked the name up again")

    def dial(address: tuple[str, int], *_args: object, **_kwargs: object) -> None:
        dialed.append(address)
        raise ConnectionRefusedError("stub")

    monkeypatch.setattr(socket, "getaddrinfo", no_lookup)
    monkeypatch.setattr(socket, "create_connection", dial)
    for url in ("https://rebind.example/page", "http://rebind.example:8080/page"):
        with pytest.raises(ConnectionRefusedError):
            sb.pinned_get(url, PUBLIC, 1000)

    assert dialed == [(PUBLIC, 443), (PUBLIC, 8080)]


def test_the_real_fetcher_sends_a_bare_get_and_stops_reading_past_the_cap() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the stdlib's name
            seen.append((self.command, {k.lower(): v for k, v in self.headers.items()}))
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"x" * 300_000)

        def log_message(self, *_args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        page = sb.pinned_get(f"http://site.example:{port}/p?q=1", "127.0.0.1", 100_000)
    finally:
        server.shutdown()
        server.server_close()

    assert page.status == 200 and len(page.body) == 100_001
    method, headers = seen[0]
    assert method == "GET"
    assert headers["host"] == f"site.example:{port}"
    assert not {"cookie", "authorization", "content-length"} & set(headers)


def test_a_page_that_trickles_is_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    stop = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the stdlib's name
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "1000")
            self.end_headers()
            while not stop.wait(0.1):  # a byte at a time, never the whole body
                self.wfile.write(b"x")
                self.wfile.flush()

        def log_message(self, *_args: object) -> None:
            pass

    monkeypatch.setattr(sb, "_READ_DEADLINE_S", 0.6)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(sb.Refused) as refused:
            sb.pinned_get(f"http://slow.example:{server.server_address[1]}/", "127.0.0.1", 100_000)
    finally:
        stop.set()
        server.shutdown()
        server.server_close()

    assert refused.value.reason == "too slow"


@pytest.mark.parametrize(
    ("page", "status", "reason"),
    [
        (sb.Page(200, {"content-type": "text/plain"}, b"a" * (sb.MAX_BYTES + 1)), 413, "too large"),
        (sb.Page(200, {"content-type": "text/plain", "content-length": "5000000"}), 413, "too large"),
        (sb.Page(200, {"content-type": "image/png"}, b"\x89PNG"), 415, "not a text page"),
        (sb.Page(200, {}, b"no label"), 415, "not a text page"),
        (sb.Page(200, {"content-type": "text/html", "content-encoding": "gzip"}, b"\x1f\x8b"), 415, "not a text page"),
        (sb.Page(404, {"content-type": "text/html"}, b"gone"), 502, "the page answered HTTP 404"),
    ],
)
def test_only_a_text_page_within_the_cap_is_read(page: sb.Page, status: int, reason: str) -> None:
    with pytest.raises(sb.Refused) as refused:
        sb._page_answer("https://example.com/a", page, 0)

    assert (refused.value.status, refused.value.reason) == (status, reason)


def test_a_text_page_is_read_as_its_title_and_text() -> None:
    answer = sb._page_answer("https://example.com/a", _html(), 0)

    assert answer["title"] == "Cage notes"
    assert "The fence holds." in answer["text"]


@pytest.mark.parametrize("charset", ["rot13", "base64", "hex", "zlib", "bz2", "undefined", "idna"])
def test_a_charset_that_is_not_a_text_encoding_reads_as_utf8(charset: str) -> None:
    page = sb.Page(200, {"content-type": f"text/plain; charset={charset}"}, "café notes".encode())

    assert sb._page_answer("https://example.com/a", page, 0)["text"] == "café notes"


def test_this_machines_own_addresses_are_found(monkeypatch: pytest.MonkeyPatch) -> None:
    import psutil

    nic = SimpleNamespace(family=socket.AF_INET6, address=f"{OWN_V6}%12")
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {"Ethernet": [nic]})
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(socket.AF_INET, 1, 6, "", (OWN, 0))])

    assert {OWN, OWN_V6} <= sb.own_addresses()


# --- Searching and reading through the broker -----------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeWeb:
    """A search engine, DNS and web server in one, recording what the broker asked of each."""

    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []
        self.dns: dict[str, list[str]] = {}
        self.pages: dict[str, sb.Page] = {}
        self.queries: list[str] = []
        self.freshness: list[str | None] = []
        self.lookups: list[str] = []
        self.fetched: list[tuple[str, str]] = []

    async def search(self, query: str, count: int, freshness: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        self.queries.append(query)
        self.freshness.append(freshness)
        return "stub", list(self.results)

    def resolve(self, host: str, port: int) -> list[str]:
        self.lookups.append(host)
        if host in self.dns:
            return self.dns[host]
        try:
            return [str(ipaddress.ip_address(host))]
        except ValueError:
            raise socket.gaierror(f"{host} does not resolve") from None

    def fetch(self, url: str, address: str, max_bytes: int) -> sb.Page:
        self.fetched.append((url, address))
        return self.pages[url]

    def result(self, url: str, page: sb.Page | None = None, addresses: list[str] | None = None) -> None:
        self.results.append({"title": f"About {url}", "url": url, "description": "a result"})
        if page is not None:
            self.pages[url] = page
        if addresses is not None:
            self.dns[str(urlsplit(url).hostname)] = addresses


def _broker(web: FakeWeb, clock: Clock | None = None) -> sb.Broker:
    own = frozenset({OWN, OWN_V6})
    return sb.Broker(search=web.search, resolve=web.resolve, fetch=web.fetch, own=lambda: own, clock=clock or Clock())


def _searched(web: FakeWeb, clock: Clock | None = None) -> sb.Broker:
    broker = _broker(web, clock)
    assert asyncio.run(broker.search({"query": "q"}))[0] == 200
    return broker


def _read(broker: sb.Broker, url: str) -> tuple[int, dict[str, Any]]:
    return asyncio.run(broker.read({"url": url}))


def test_a_search_returns_rows_and_every_returned_url_becomes_a_ticket() -> None:
    web = FakeWeb()
    web.result("https://example.com/a")
    web.result("https://example.org/b?x=1")
    web.results.append({"title": "not a page", "url": "file:///C:/Windows/win.ini"})
    web.results.append({"title": "wrapped", "url": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.net%2Fc&rut=9"})
    broker = _broker(web)

    status, answer = asyncio.run(broker.search({"query": "  cage   notes ", "count": 5}))

    assert status == 200 and answer["ok"] is True
    assert [row["url"] for row in answer["results"]] == [
        "https://example.com/a",
        "https://example.org/b?x=1",
        "https://example.net/c",
    ]
    assert set(answer["results"][0]) == {"title", "url", "snippet"}
    assert web.queries == ["cage notes"]
    assert all(broker.is_ticketed(row["url"]) for row in answer["results"])
    assert not broker.is_ticketed("file:///C:/Windows/win.ini")


def test_a_query_cannot_send_the_search_engine_to_another_site() -> None:
    # DuckDuckGo turns "!bang" and a leading "\" into a redirect to another site,
    # which the search client, running as you and outside the fence, would follow.
    web = FakeWeb()
    broker = _broker(web)

    for query in ("!gh leaked-token", "\\ first result", "cats !w", "a!b"):
        asyncio.run(broker.search({"query": query}))

    assert web.queries == ["gh leaked-token", "first result", "cats w", "a b"]


def test_a_ticket_lasts_an_hour() -> None:
    clock = Clock()
    web = FakeWeb()
    web.result("https://example.com/a", _html(), [PUBLIC])
    broker = _searched(web, clock)

    clock.now += 3599
    assert _read(broker, "https://example.com/a")[0] == 200
    clock.now += 2
    assert _read(broker, "https://example.com/a") == (
        403,
        {"ok": False, "error": "not a search result", "detail": sb.NOT_A_RESULT_DETAIL},
    )


def test_a_ticketed_url_is_read_from_the_address_that_was_checked() -> None:
    web = FakeWeb()
    web.result("https://example.com/a", _html(), [PUBLIC])
    broker = _searched(web)

    status, answer = _read(broker, "https://example.com/a")

    assert status == 200, answer
    assert answer["title"] == "Cage notes"
    assert web.fetched == [("https://example.com/a", PUBLIC)]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/never-returned",
        "https://example.com/a?leak=secret",
        "https://example.com/a/secret",
        "https://example.com/a#secret",
        "https://EXAMPLE.com/a",
        " https://example.com/a",
        "http://example.com/a",
    ],
)
def test_a_url_that_was_not_returned_exactly_is_refused(url: str) -> None:
    web = FakeWeb()
    web.result("https://example.com/a", _html(), [PUBLIC])
    broker = _searched(web)

    status, answer = _read(broker, url)

    assert (status, answer["error"]) == (403, "not a search result")
    assert web.lookups == [] and web.fetched == []


@pytest.mark.parametrize(
    ("url", "addresses", "reason"),
    [
        ("http://127.0.0.1:8899/api/chat", None, "loopback address"),
        ("http://[::1]:8899/", None, "loopback address"),
        ("http://10.0.0.8/", None, "private address"),
        ("http://192.168.1.1/admin", None, "private address"),
        ("http://169.254.169.254/latest/meta-data/", None, "link-local address"),
        ("http://[fe80::1]/", None, "link-local address"),
        ("http://localtest.me:8899/", ["127.0.0.1"], "loopback address"),
        ("http://2130706433:8899/", ["127.0.0.1"], "loopback address"),
        ("https://mixed.example/", [PUBLIC, "192.168.1.20"], "private address"),
        ("https://router.example/", ["2601:600:8a00:1234::1"], "an address on your own network"),
    ],
)
def test_a_result_that_points_inside_is_refused(url: str, addresses: list[str] | None, reason: str) -> None:
    web = FakeWeb()
    web.result(url, _html(), addresses)
    broker = _searched(web)
    assert broker.is_ticketed(url)

    status, answer = _read(broker, url)

    assert (status, answer["error"]) == (403, reason), answer
    assert web.fetched == []


def test_the_real_resolver_refuses_localhost() -> None:
    web = FakeWeb()
    web.result("http://localhost:8899/api/chat", _html())
    broker = sb.Broker(search=web.search, fetch=web.fetch, own=frozenset, clock=Clock())
    assert asyncio.run(broker.search({"query": "q"}))[0] == 200

    status, answer = _read(broker, "http://localhost:8899/api/chat")

    assert (status, answer["error"]) == (403, "loopback address")
    assert web.fetched == []


def test_a_broker_left_to_itself_knows_this_machines_own_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    import psutil

    nic = SimpleNamespace(family=socket.AF_INET6, address=OWN_V6)
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {"Ethernet": [nic]})
    web = FakeWeb()
    web.result("https://own.example/", _html(), [OWN_V6])
    broker = sb.Broker(search=web.search, resolve=web.resolve, fetch=web.fetch, clock=Clock())
    assert asyncio.run(broker.search({"query": "q"}))[0] == 200

    assert _read(broker, "https://own.example/")[1]["error"] == "this machine's own address"
    assert web.fetched == []


def test_freshness_reaches_the_search_and_a_bad_one_is_refused() -> None:
    web = FakeWeb()
    broker = _broker(web)

    assert asyncio.run(broker.search({"query": "q", "freshness": "pw"}))[0] == 200
    status, answer = asyncio.run(broker.search({"query": "q", "freshness": "yesterday"}))

    assert (status, answer["error"]) == (400, "Invalid freshness. Allowed: pd, pw, pm, py.")
    assert web.freshness == ["pw"]


@pytest.mark.parametrize(
    ("location", "addresses", "reason"),
    [
        ("http://192.168.1.1/admin", None, "private address"),
        ("http://rebind.example:8899/", ["127.0.0.1"], "loopback address"),
        ("file:///C:/Windows/win.ini", None, "only http and https pages can be read"),
        ("http://[fec0::1]/", None, "site-local address"),
    ],
)
def test_a_redirect_is_checked_like_the_first_address(location: str, addresses: list[str] | None, reason: str) -> None:
    web = FakeWeb()
    web.result("https://example.com/go", sb.Page(302, {"location": location}), [PUBLIC])
    if addresses is not None:
        web.dns[str(urlsplit(location).hostname)] = addresses
    broker = _searched(web)

    status, answer = _read(broker, "https://example.com/go")

    assert (status, answer["error"]) == (403, reason), answer
    assert web.fetched == [("https://example.com/go", PUBLIC)]


def test_three_redirects_are_followed_and_a_fourth_is_refused() -> None:
    web = FakeWeb()
    web.result("https://example.com/r0", sb.Page(301, {"location": "/r1"}), [PUBLIC])
    web.pages["https://example.com/r1"] = sb.Page(302, {"location": "https://example.com/r2"})
    web.pages["https://example.com/r2"] = sb.Page(307, {"location": "r3"})
    web.pages["https://example.com/r3"] = _html()
    web.result("https://example.com/s0", sb.Page(301, {"location": "/r0"}))
    broker = _searched(web)

    status, answer = _read(broker, "https://example.com/r0")
    assert (status, answer["redirects"], answer["url"]) == (200, 3, "https://example.com/r3")

    status, answer = _read(broker, "https://example.com/s0")
    assert (status, answer["error"]) == (502, "too many redirects")


def test_the_connection_goes_to_the_address_that_was_checked() -> None:
    web = FakeWeb()
    web.result("https://rebind.example/", _html())
    answers = iter([[PUBLIC], ["127.0.0.1"]])  # a second lookup would come back home

    def rebinding(host: str, port: int) -> list[str]:
        web.lookups.append(host)
        return next(answers)

    web.resolve = rebinding  # type: ignore[method-assign]
    broker = _searched(web)

    assert _read(broker, "https://rebind.example/")[0] == 200
    assert web.lookups == ["rebind.example"]
    assert web.fetched == [("https://rebind.example/", PUBLIC)]


def test_a_result_over_2_mb_is_refused() -> None:
    web = FakeWeb()
    web.result("https://example.com/big", sb.Page(200, {"content-type": "text/plain"}, b"a" * (sb.MAX_BYTES + 1)))
    web.dns["example.com"] = [PUBLIC]
    broker = _searched(web)

    assert _read(broker, "https://example.com/big") == (413, {"ok": False, "error": "too large", "detail": "over 2 MB"})


def test_searches_and_reads_are_rate_limited() -> None:
    clock = Clock()
    web = FakeWeb()
    web.result("https://example.com/a", _html(), [PUBLIC])
    broker = _broker(web, clock)

    async def go() -> tuple[list[int], int, list[int], dict[str, Any]]:
        searches = [(await broker.search({"query": f"q{i}"}))[0] for i in range(sb.SEARCHES_PER_MINUTE + 1)]
        clock.now += 60
        again = (await broker.search({"query": "again"}))[0]
        reads = [(await broker.read({"url": "https://example.com/a"}))[0] for _ in range(sb.READS_PER_MINUTE)]
        return searches, again, reads, (await broker.read({"url": "https://example.com/a"}))[1]

    searches, again, reads, refused = asyncio.run(go())

    assert searches[:-1] == [200] * sb.SEARCHES_PER_MINUTE and searches[-1] == 429
    assert again == 200
    assert reads == [200] * sb.READS_PER_MINUTE and refused["error"] == "too many reads"


def test_only_a_local_program_can_call_it() -> None:
    web = FakeWeb()
    web.result("https://example.com/a", _html(), [PUBLIC])

    async def go() -> list[int]:
        async with TestClient(TestServer(sb.build_app(_broker(web)))) as client:
            calls = [
                client.post("/search", json={"query": "q"}),
                client.post("/search", json={"query": "q"}, headers={"Origin": "https://evil.example"}),
                client.post("/search", json={"query": "q"}, headers={"Host": "evil.example:8896"}),
                client.post("/search", data="query=q", headers={"Content-Type": "text/plain"}),
            ]
            return [(await call).status for call in calls]

    assert asyncio.run(go()) == [200, 403, 403, 415]
    assert web.queries == ["q"]


def test_it_listens_on_loopback_only() -> None:
    with pytest.raises(ValueError, match="loopback"):
        asyncio.run(sb.serve(host="0.0.0.0", port=0))


# --- The caged Thomas uses it ---------------------------------------------------


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _through_broker(web: FakeWeb, monkeypatch: pytest.MonkeyPatch, work: Any) -> Any:
    async with TestServer(sb.build_app(_broker(web))) as server:
        monkeypatch.setenv(sb.ENV_VAR, str(server.make_url("")).rstrip("/"))
        return await work()


def test_the_caged_web_search_goes_through_the_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.tools import web_search
    from thomas.tools.resilient_web_search import ResilientWebSearchTool, get_resilient_web_search_tool

    async def never(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("searched directly from inside the cage")

    for owner, name in ((web_search.WebSearchTool, "_search_ddg"), (web_search.WebSearchTool, "_search_brave")):
        monkeypatch.setattr(owner, name, never)
    monkeypatch.setattr(ResilientWebSearchTool, "_bing_search", never)
    # The caged server's model clients go through a proxy; the broker's client never does.
    dead = f"http://127.0.0.1:{_closed_port()}"
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(key, dead)
    monkeypatch.delenv("NO_PROXY", raising=False)
    web = FakeWeb()
    web.result("https://example.com/a")

    tool = get_resilient_web_search_tool()

    async def work() -> tuple[Any, Any]:
        return (
            await tool.execute({"query": "caged one", "count": 3, "freshness": "pm"}),
            await web_search.WebSearchTool().execute({"query": "caged two", "freshness": "yesterday"}),
        )

    result, stale = asyncio.run(_through_broker(web, monkeypatch, work))

    assert result.ok, result.error
    assert [(row["url"], row["description"]) for row in result.data["results"]] == [
        ("https://example.com/a", "a result")
    ]
    assert (web.queries, web.freshness) == (["caged one"], ["pm"])
    assert stale.error == "Invalid freshness. Allowed: pd, pw, pm, py."


def test_web_search_is_direct_when_no_broker_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.tools import web_search, web_search_broker

    async def never(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("asked the broker outside the cage")

    async def ddg(_self: object, *, query: str, count: int, **_kwargs: object) -> dict[str, Any]:
        row = {"title": "Direct", "url": "https://example.com/d", "description": "d", "published_date": None}
        return {"provider": "duckduckgo", "query": query, "count": count, "results": [row], "meta": {}}

    monkeypatch.delenv(sb.ENV_VAR, raising=False)
    monkeypatch.setattr(web_search_broker, "search", never)
    monkeypatch.setattr(web_search, "_get_brave_api_key", lambda: None)
    monkeypatch.setattr(web_search.WebSearchTool, "_search_ddg", ddg)

    result = asyncio.run(web_search.WebSearchTool().execute({"query": "uncaged direct 5c1e"}))

    assert result.ok and result.data["provider"] == "duckduckgo"


def test_web_fetch_reads_a_result_and_says_what_works_for_anything_else(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.tools.web_search import get_web_fetch_tool, get_web_search_tool

    web = FakeWeb()
    web.result("https://example.com/a", _html(), [PUBLIC])

    async def work() -> tuple[Any, Any]:
        assert (await get_web_search_tool().execute({"query": "fetch me"})).ok
        fetch = get_web_fetch_tool()
        return await fetch.execute({"url": "https://example.com/a"}), await fetch.execute({"url": "https://ex.com/"})

    read, refused = asyncio.run(_through_broker(web, monkeypatch, work))

    assert read.ok, read.error
    assert read.data["title"] == "Cage notes" and "The fence holds." in read.data["text"]
    assert not refused.ok
    assert "https://ex.com/ was not one of them" in refused.error
    assert "Search first with web.search" in refused.error
    assert web.fetched == [("https://example.com/a", PUBLIC)]


def test_a_broker_that_is_not_answering_is_named_for_what_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.tools import web_search_broker
    from thomas.tools.web_search import get_web_search_tool

    monkeypatch.setenv(sb.ENV_VAR, f"http://127.0.0.1:{_closed_port()}")
    monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{_closed_port()}")
    promoter_gone = asyncio.run(get_web_search_tool().execute({"query": "anyone there"}))
    with socket.socket() as proxy:
        proxy.bind(("127.0.0.1", 0))
        proxy.listen()
        monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{proxy.getsockname()[1]}")
        broker_only = asyncio.run(get_web_search_tool().execute({"query": "anyone there"}))

    assert promoter_gone.error == web_search_broker.PROMOTER_DOWN
    assert broker_only.error == web_search_broker.BROKER_DOWN
    assert "within a minute" in broker_only.error and "15 minutes" in promoter_gone.error


def test_the_browser_shell_results_page_gets_broker_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiohttp import web as aioweb

    from thomas.server.app_keys import APP_TOOLS
    from thomas.server.routes.search import register_search_routes
    from thomas.tools.resilient_web_search import get_resilient_web_search_tool

    class Registry:
        async def execute(self, name: str, args: dict[str, Any]) -> Any:
            assert name == "web.search"
            return await get_resilient_web_search_tool().execute(args)

    web = FakeWeb()
    web.result("https://example.com/a")
    web.result("https://example.org/b")
    app = aioweb.Application()
    register_search_routes(app, require_api_access=lambda _request: None)
    app[APP_TOOLS] = Registry()

    async def work() -> tuple[int, dict[str, Any]]:
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/search/web", params={"q": "shell search", "count": "5"})
            return resp.status, await resp.json()

    status, body = asyncio.run(_through_broker(web, monkeypatch, work))

    assert (status, body["ok"]) == (200, True), body
    assert [(row["url"], row["snippet"]) for row in body["results"]] == [
        ("https://example.com/a", "a result"),
        ("https://example.org/b", "a result"),
    ]


@pytest.mark.parametrize("claude", [False, True])
def test_the_caged_server_points_its_web_tools_at_the_broker(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, claude: bool
) -> None:
    import os
    import sys
    from unittest import mock

    from scripts.cage import caged_server, egress_proxy

    import thomas.cli.main as cli

    assert sb.broker_env(tmp_path) == {}
    (tmp_path / "egress.allow").write_text("api.openai.com\n", encoding="utf-8")
    assert sb.broker_env(tmp_path) == {sb.ENV_VAR: "http://127.0.0.1:8896"}
    monkeypatch.setattr(egress_proxy, "DEFAULT_PIN_ROOT", tmp_path)
    # Never the real C:\ProgramData\ThomasCage: no cage at all, or a cage whose
    # Claude folder makes main() write its Claude keys and PATH as well.
    cage = tmp_path / ("cage" if claude else "no-cage")
    if claude:
        (cage / "claude").mkdir(parents=True)
    monkeypatch.setattr(caged_server, "CAGE_ROOT", cage)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", list(sys.argv))
    monkeypatch.setattr(sys, "path", list(sys.path))
    seen: dict[str, str] = {}
    monkeypatch.setattr(cli, "main", lambda: seen.update(os.environ))
    before = dict(os.environ)

    # main() writes the process environment; every key it writes goes back afterwards.
    with mock.patch.dict(os.environ):
        assert caged_server.main(["--port", "0", "--codex-home", str(tmp_path / ".codex")]) == 0

    assert dict(os.environ) == before
    written = {key for key in seen if seen[key] != before.get(key)}
    assert written >= {sb.ENV_VAR, "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "THOMAS_OWNER_DESK", "CODEX_HOME"}
    claude_keys = {"CLAUDE_CONFIG_DIR", "PATH", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"}
    assert (claude_keys <= written) is claude and (claude or not claude_keys & written)
    assert (seen[sb.ENV_VAR], seen["HTTPS_PROXY"]) == ("http://127.0.0.1:8896", "http://127.0.0.1:8897")
