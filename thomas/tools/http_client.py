"""HTTP/API Testing Tool for making HTTP requests and testing API endpoints.

Provides HTTP client functionality with support for various methods, auth types,
request/response handling, and endpoint testing with assertions.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib.parse import urlencode

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None  # type: ignore

from thomas.tools.base import Tool, ToolResult
from thomas.tools.url_safety import check_url


class HttpClientError(RuntimeError):
    """HTTP client error."""

    pass


class HttpClientTool(Tool):
    """Tool for making HTTP requests and testing API endpoints.

    Supports:
    - All HTTP methods (GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD)
    - Authentication (bearer token, basic auth, API key)
    - Various body types (JSON, form-data, raw text, binary)
    - Connection pooling and cookie jar
    - Request/response logging
    - Retry with backoff
    - Endpoint testing with status code and body assertions
    """

    name = "http.client"
    category = "http"
    description = (
        "Make HTTP requests with various methods, auth types, and body formats. "
        "Test API endpoints with status code and response body assertions. "
        "Supports connection pooling, cookies, retries, and logging."
    )
    parameters = {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "description": "HTTP method: GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD",
            },
            "url": {
                "type": "string",
                "description": "Target URL",
            },
            "headers": {
                "type": "object",
                "description": "Request headers as key-value pairs",
            },
            "body": {
                "type": "string",
                "description": "Request body (for POST/PUT/PATCH)",
            },
            "json": {
                "type": "object",
                "description": "JSON body (alternative to body parameter)",
            },
            "auth": {
                "type": "object",
                "description": "Authentication config: {type: 'bearer'|'basic'|'apikey', value: str, param?: str}",
            },
            "timeout": {
                "type": "integer",
                "description": "Request timeout in seconds (default: 30)",
            },
            "verify_ssl": {
                "type": "boolean",
                "description": "Verify SSL certificates (default: true)",
            },
            "expected_status": {
                "type": "integer",
                "description": "Expected status code for test_endpoint",
            },
            "expected_body_contains": {
                "type": "string",
                "description": "String that response body should contain for test_endpoint",
            },
        },
        "required": ["method", "url"],
    }

    def __init__(self):
        """Initialize HTTP client tool."""
        self._session: aiohttp.ClientSession | None = None
        self._connector: aiohttp.TCPConnector | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure aiohttp session is initialized."""
        if aiohttp is None:
            raise HttpClientError("aiohttp not installed")

        if self._session is None:
            self._connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300,
            )
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                cookie_jar=aiohttp.CookieJar(),
            )
        return self._session

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        """Execute HTTP request or test."""
        method = args.get("method", "GET").upper()
        url = args.get("url")

        if not url:
            return ToolResult(ok=False, error="url is required")

        # Check if this is a test request
        if "expected_status" in args or "expected_body_contains" in args:
            return await self.test_endpoint(
                url=url,
                method=method,
                expected_status=args.get("expected_status", 200),
                expected_body_contains=args.get("expected_body_contains"),
            )

        # Regular request
        return await self.request(
            method=method,
            url=url,
            headers=args.get("headers"),
            body=args.get("body"),
            json=args.get("json"),
            auth=args.get("auth"),
            timeout=args.get("timeout", 30),
            verify_ssl=args.get("verify_ssl", True),
        )

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        json: dict[str, Any] | None = None,
        auth: dict[str, str] | None = None,
        timeout: int = 30,
        verify_ssl: bool = True,
    ) -> ToolResult:
        """Make an HTTP request.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD)
            url: Target URL
            headers: Request headers
            body: Request body (raw or JSON string)
            json: Request body as dict (converted to JSON)
            auth: Auth config {type: 'bearer'|'basic'|'apikey', value: str, param?: str}
            timeout: Request timeout in seconds
            verify_ssl: Verify SSL certificates

        Returns:
            ToolResult with status_code, headers, body, elapsed_ms, size_bytes
        """
        # SSRF guard -- url_safety is the single source of tool fetch policy.
        # Refuse internal / link-local / cloud-metadata targets before opening
        # any connection. This tool is currently unregistered; the guard makes
        # it safe-by-default if it is ever wired into the live tool registry.
        url_error = check_url(url, allow_private=False)
        if url_error:
            return ToolResult(ok=False, error=f"Refused by SSRF guard: {url_error}")
        try:
            session = await self._ensure_session()

            # Prepare headers
            req_headers = dict(headers) if headers else {}

            # Prepare body
            req_body = None
            if json:
                req_body = json if isinstance(json, str) else json
                if "content-type" not in (k.lower() for k in req_headers.keys()):
                    req_headers["Content-Type"] = "application/json"
            elif body:
                req_body = body

            # Apply authentication
            if auth:
                auth_type = auth.get("type", "").lower()
                auth_value = auth.get("value", "")

                if auth_type == "bearer":
                    req_headers["Authorization"] = f"Bearer {auth_value}"
                elif auth_type == "basic":
                    import base64

                    creds = base64.b64encode(auth_value.encode()).decode()
                    req_headers["Authorization"] = f"Basic {creds}"
                elif auth_type == "apikey":
                    param_name = auth.get("param", "X-API-Key")
                    if param_name.startswith("?"):
                        # Query parameter
                        separator = "&" if "?" in url else "?"
                        url = f"{url}{separator}{param_name[1:]}={auth_value}"
                    else:
                        # Header
                        req_headers[param_name] = auth_value

            # Make request
            ssl_context = None if verify_ssl else False
            start = time.monotonic()

            async with session.request(
                method,
                url,
                data=req_body,
                headers=req_headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
                ssl=ssl_context,
                # Don't auto-follow redirects: a public URL could 3xx into an
                # internal target that bypasses the initial SSRF check. Following
                # redirects safely requires re-validating each hop via check_url.
                allow_redirects=False,
            ) as resp:
                resp_body = await resp.text()
                elapsed_ms = (time.monotonic() - start) * 1000

                # Try to parse as JSON
                try:
                    body_data = json.loads(resp_body) if resp_body else None
                except (json.JSONDecodeError, ValueError):
                    body_data = resp_body

                result_data = {
                    "status_code": resp.status,
                    "headers": dict(resp.headers),
                    "body": body_data,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "size_bytes": len(resp_body),
                }

                return ToolResult(ok=True, data=result_data)

        except asyncio.TimeoutError:
            return ToolResult(ok=False, error=f"Request timeout after {timeout}s")
        except Exception as e:
            return ToolResult(ok=False, error=f"{type(e).__name__}: {e}")

    async def get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ToolResult:
        """Convenience method for GET request.

        Args:
            url: Target URL
            params: Query parameters
            headers: Request headers

        Returns:
            ToolResult with response data
        """
        if params:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(params)}"

        return await self.request(method="GET", url=url, headers=headers)

    async def post(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        data: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> ToolResult:
        """Convenience method for POST request.

        Args:
            url: Target URL
            json: JSON body
            data: Form or raw body
            headers: Request headers

        Returns:
            ToolResult with response data
        """
        return await self.request(
            method="POST",
            url=url,
            json=json,
            body=data,
            headers=headers,
        )

    async def put(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ToolResult:
        """Convenience method for PUT request.

        Args:
            url: Target URL
            json: JSON body
            headers: Request headers

        Returns:
            ToolResult with response data
        """
        return await self.request(method="PUT", url=url, json=json, headers=headers)

    async def delete(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> ToolResult:
        """Convenience method for DELETE request.

        Args:
            url: Target URL
            headers: Request headers

        Returns:
            ToolResult with response data
        """
        return await self.request(method="DELETE", url=url, headers=headers)

    async def test_endpoint(
        self,
        url: str,
        method: str = "GET",
        expected_status: int = 200,
        expected_body_contains: str | None = None,
    ) -> ToolResult:
        """Test an API endpoint with assertions.

        Args:
            url: Target URL
            method: HTTP method
            expected_status: Expected status code
            expected_body_contains: String that response body should contain

        Returns:
            ToolResult with test results {passed, actual_status, expected_status, response_time_ms, details}
        """
        start = time.monotonic()
        req_result = await self.request(method=method, url=url)
        elapsed_ms = (time.monotonic() - start) * 1000

        if not req_result.ok:
            return ToolResult(
                ok=False,
                error=req_result.error,
                data={
                    "passed": False,
                    "actual_status": None,
                    "expected_status": expected_status,
                    "response_time_ms": round(elapsed_ms, 2),
                    "details": "Request failed",
                },
            )

        actual_status = req_result.data.get("status_code")
        status_match = actual_status == expected_status

        body = req_result.data.get("body")
        body_str = body if isinstance(body, str) else json.dumps(body)
        body_match = True

        if expected_body_contains:
            body_match = expected_body_contains in body_str

        passed = status_match and body_match

        result_data = {
            "passed": passed,
            "actual_status": actual_status,
            "expected_status": expected_status,
            "response_time_ms": round(req_result.data.get("elapsed_ms", 0), 2),
            "details": {
                "status_match": status_match,
                "body_contains_match": body_match if expected_body_contains else "not_checked",
                "response_size_bytes": req_result.data.get("size_bytes", 0),
            },
        }

        return ToolResult(ok=True, data=result_data)

    async def test_suite(
        self,
        tests: list[dict[str, Any]],
    ) -> ToolResult:
        """Run multiple endpoint tests.

        Args:
            tests: List of test definitions {url, method, expected_status, expected_body_contains}

        Returns:
            ToolResult with suite results {total, passed, failed, results, total_time_ms}
        """
        start = time.monotonic()
        results = []
        passed_count = 0
        failed_count = 0

        for test in tests:
            test_result = await self.test_endpoint(
                url=test.get("url", ""),
                method=test.get("method", "GET"),
                expected_status=test.get("expected_status", 200),
                expected_body_contains=test.get("expected_body_contains"),
            )

            results.append(
                {
                    "test": test,
                    "result": test_result.data,
                }
            )

            if test_result.data.get("passed"):
                passed_count += 1
            else:
                failed_count += 1

        total_time_ms = (time.monotonic() - start) * 1000

        result_data = {
            "total": len(tests),
            "passed": passed_count,
            "failed": failed_count,
            "results": results,
            "total_time_ms": round(total_time_ms, 2),
        }

        return ToolResult(ok=True, data=result_data)

    async def save_response(
        self,
        response: dict[str, Any],
        filepath: str,
    ) -> ToolResult:
        """Save HTTP response to file.

        Args:
            response: Response data from request/test
            filepath: Path to save to

        Returns:
            ToolResult with save status
        """
        try:
            import os

            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

            if filepath.endswith(".json"):
                with open(filepath, "w") as f:
                    json.dump(response, f, indent=2)
            else:
                body = response.get("body", "")
                content = body if isinstance(body, str) else json.dumps(body, indent=2)
                with open(filepath, "w") as f:
                    f.write(content)

            return ToolResult(ok=True, data={"saved_to": filepath, "size_bytes": os.path.getsize(filepath)})
        except Exception as e:
            return ToolResult(ok=False, error=f"{type(e).__name__}: {e}")

    def build_curl(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: str | None = None,
    ) -> ToolResult:
        """Generate equivalent cURL command.

        Args:
            method: HTTP method
            url: Target URL
            headers: Request headers
            body: Request body

        Returns:
            ToolResult with cURL command string
        """
        try:
            curl_cmd = f"curl -X {method}"

            if headers:
                for key, value in headers.items():
                    curl_cmd += f" -H '{key}: {value}'"

            if body:
                # Escape single quotes in body
                escaped_body = body.replace("'", "'\\''")
                curl_cmd += f" -d '{escaped_body}'"

            curl_cmd += f" '{url}'"

            return ToolResult(ok=True, data={"curl": curl_cmd})
        except Exception as e:
            return ToolResult(ok=False, error=f"{type(e).__name__}: {e}")

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session:
            await self._session.close()
        if self._connector:
            await self._connector.close()
