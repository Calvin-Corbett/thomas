"""Minimal httpx-compatible shim using stdlib urllib.

Provides enough of the httpx API for Thomas's LLM client to function.
Only stdlib dependencies (urllib.request, json, asyncio, ssl).
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ─── Timeout ────────────────────────────────────────────────────────
@dataclass
class Timeout:
    """HTTP timeout configuration.

    Args:
        timeout: Default timeout for all operations
        connect: Connection timeout
        read: Read timeout
        write: Write timeout
        pool: Pool timeout
    """

    timeout: float = 30.0
    connect: float | None = None
    read: float | None = None
    write: float | None = None
    pool: float | None = None

    def __init__(
        self,
        timeout: float = 30.0,
        *,
        connect: float | None = None,
        read: float | None = None,
        write: float | None = None,
        pool: float | None = None,
    ) -> None:
        self.timeout = timeout
        self.connect = connect or timeout
        self.read = read or timeout
        self.write = write or timeout
        self.pool = pool or timeout


# ─── Response ───────────────────────────────────────────────────────
class Response:
    """HTTP response wrapper."""

    def __init__(
        self,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
        request: Any | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self.request = request
        self._text: str | None = None

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = self.content.decode("utf-8", errors="replace")
        return self._text

    def json(self) -> Any:
        return json.loads(self.text)

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def raise_for_status(self) -> None:
        if self.is_error:
            raise HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=self,
            )


# ─── Streaming response ────────────────────────────────────────────
class StreamResponse:
    """Streaming HTTP response for SSE/chunked responses."""

    def __init__(self, response: Any, raw_data: bytes = b"") -> None:
        self.status_code = getattr(response, "status", 200)
        self._raw = raw_data
        self._lines = raw_data.decode("utf-8", errors="replace").split("\n")

    def iter_lines(self) -> Iterator[str]:
        for line in self._lines:
            if line.strip():
                yield line

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            if line.strip():
                yield line

    async def aclose(self) -> None:
        pass

    async def __aenter__(self) -> StreamResponse:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()


# ─── Exceptions ─────────────────────────────────────────────────────
class HTTPError(Exception):
    """Base HTTP error."""

    pass


class ConnectError(HTTPError):
    """Connection error."""

    pass


class ReadError(HTTPError):
    """Read error."""

    pass


class ReadTimeout(HTTPError):
    """Read timeout."""

    pass


class TimeoutException(HTTPError):
    """General timeout."""

    pass


class HTTPStatusError(HTTPError):
    """HTTP status error (4xx/5xx)."""

    def __init__(
        self,
        message: str,
        *,
        request: Any = None,
        response: Any = None,
    ) -> None:
        super().__init__(message)
        self.request = request
        self.response = response


# ─── Client base ────────────────────────────────────────────────────
def _build_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json_data: Any | None = None,
    data: bytes | None = None,
    timeout: float = 30.0,
) -> urllib.request.Request:
    """Build a urllib Request object."""
    body = None
    if json_data is not None:
        body = json.dumps(json_data).encode("utf-8")
        headers = headers or {}
        headers.setdefault("Content-Type", "application/json")
    elif data is not None:
        body = data

    req = urllib.request.Request(url, data=body, method=method.upper())
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    return req


def _do_request(
    req: urllib.request.Request,
    timeout: float = 30.0,
) -> Response:
    """Execute a urllib request and return a Response."""
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            content = resp.read()
            headers = dict(resp.headers)
            return Response(
                status_code=resp.status,
                headers=headers,
                content=content,
                request=req,
            )
    except urllib.error.HTTPError as e:
        content = e.read() if e.fp else b""
        return Response(
            status_code=e.code,
            headers=dict(e.headers) if e.headers else {},
            content=content,
            request=req,
        )
    except urllib.error.URLError as e:
        raise ConnectError(str(e.reason)) from e
    except TimeoutError as e:
        raise TimeoutException(str(e)) from e
    except OSError as e:
        raise ConnectError(str(e)) from e


# ─── Async Client ──────────────────────────────────────────────────
class AsyncClient:
    """Async HTTP client wrapping urllib (runs in thread pool).

    Args:
        base_url: Base URL for all requests
        headers: Default headers
        timeout: Request timeout
    """

    def __init__(
        self,
        base_url: str = "",
        *,
        headers: dict[str, str] | None = None,
        timeout: Timeout | float | None = None,
        **kwargs: Any,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.headers = headers or {}
        if isinstance(timeout, Timeout):
            self._timeout = timeout.timeout
        elif isinstance(timeout, (int, float)):
            self._timeout = float(timeout)
        else:
            self._timeout = 30.0
        self._closed = False

    def _resolve_url(self, url: str) -> str:
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return self.base_url + url

    def _merge_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        merged = dict(self.headers)
        if extra:
            merged.update(extra)
        return merged

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Response:
        return await self.request("GET", url, headers=headers, **kwargs)

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
        data: bytes | None = None,
        **kwargs: Any,
    ) -> Response:
        return await self.request("POST", url, headers=headers, json=json, data=data, **kwargs)

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
        data: bytes | None = None,
        **kwargs: Any,
    ) -> Response:
        full_url = self._resolve_url(url)
        merged = self._merge_headers(headers)
        req = _build_request(method, full_url, merged, json, data, self._timeout)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_request, req, self._timeout)

    async def stream(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
        **kwargs: Any,
    ) -> StreamResponse:
        """Stream a request (simulated — reads full response then yields lines)."""
        full_url = self._resolve_url(url)
        merged = self._merge_headers(headers)
        req = _build_request(method, full_url, merged, json, None, self._timeout)

        loop = asyncio.get_event_loop()
        try:
            resp = await loop.run_in_executor(None, _do_request, req, self._timeout)
            return StreamResponse(resp, resp.content)
        except Exception as e:
            raise ConnectError(str(e)) from e

    async def aclose(self) -> None:
        self._closed = True

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()


# ─── Sync Client ────────────────────────────────────────────────────
class Client:
    """Synchronous HTTP client.

    Args:
        base_url: Base URL for all requests
        headers: Default headers
        timeout: Request timeout
    """

    def __init__(
        self,
        base_url: str = "",
        *,
        headers: dict[str, str] | None = None,
        timeout: Timeout | float | None = None,
        **kwargs: Any,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.headers = headers or {}
        if isinstance(timeout, Timeout):
            self._timeout = timeout.timeout
        elif isinstance(timeout, (int, float)):
            self._timeout = float(timeout)
        else:
            self._timeout = 30.0

    def _resolve_url(self, url: str) -> str:
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return self.base_url + url

    def _merge_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        merged = dict(self.headers)
        if extra:
            merged.update(extra)
        return merged

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post(
        self,
        url: str,
        *,
        json: Any | None = None,
        **kwargs: Any,
    ) -> Response:
        return self.request("POST", url, json=json, **kwargs)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
        **kwargs: Any,
    ) -> Response:
        full_url = self._resolve_url(url)
        merged = self._merge_headers(headers)
        req = _build_request(method, full_url, merged, json, None, self._timeout)
        return _do_request(req, self._timeout)
