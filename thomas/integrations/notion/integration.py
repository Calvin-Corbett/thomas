"""Main Notion integration for Thomas.

Provides asynchronous Notion API client with database queries, page operations,
block management, and rich text support.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from thomas.integrations._circuit_breaker import CircuitBreaker
from thomas.integrations._health import get_health_checker
from thomas.integrations._rate_limiter import TokenBucketRateLimiter

from .blocks import BlockManager
from .databases import DatabaseManager
from .exceptions import NotionAPIError, NotionAuthError
from .pages import PageManager

log = logging.getLogger(__name__)

_NOTION_API_VERSION = "2022-06-28"
_NOTION_BASE_URL = "https://api.notion.com/v1"
_REQUEST_TIMEOUT = 30  # seconds
_RATE_LIMIT_DELAY = 0.5  # seconds between requests


class NotionIntegration:
    """Main integration class for Notion API.

    Provides high-level interface to Notion databases, pages, and blocks.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = _NOTION_BASE_URL,
        api_version: str = _NOTION_API_VERSION,
        timeout: float = _REQUEST_TIMEOUT,
        enable_rate_limiting: bool = True,
    ) -> None:
        """Initialize Notion integration.

        Args:
            api_key: Notion API key (Internal Integration Token)
            base_url: Notion API base URL
            api_version: Notion API version
            timeout: Request timeout in seconds
            enable_rate_limiting: Enable rate limiting (3 req/sec)
        """
        self.api_key = api_key
        self.base_url = base_url
        self.api_version = api_version
        self.timeout = timeout
        self.enable_rate_limiting = enable_rate_limiting

        self._connected = False
        self._rate_limit_lock = asyncio.Lock()
        self._last_request_time = 0.0

        # Initialize managers
        self.pages: PageManager | None = None
        self.databases: DatabaseManager | None = None
        self.blocks: BlockManager | None = None

        # Production hardening
        # Notion API limits to 3 requests per second
        self._rate_limiter = TokenBucketRateLimiter(
            rate=3.0,
            burst=10,
            name="notion",
        )
        self._circuit_breaker = CircuitBreaker(
            name="notion",
            failure_threshold=5,
            recovery_timeout=60,
        )
        self._health_checker = get_health_checker()

    def _get_headers(self) -> dict[str, str]:
        """Get HTTP headers for Notion API.

        Returns:
            Headers dict with auth and version

        Raises:
            NotionAuthError: No API key set
        """
        if not self.api_key:
            raise NotionAuthError("No Notion API key configured")

        return {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": self.api_version,
            "Content-Type": "application/json",
            "User-Agent": "Thomas/1.0 NotionIntegration",
        }

    async def _enforce_rate_limit(self) -> None:
        """Enforce rate limiting (3 requests per second)."""
        if not self.enable_rate_limiting:
            return

        async with self._rate_limit_lock:
            import time

            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < _RATE_LIMIT_DELAY:
                await asyncio.sleep(_RATE_LIMIT_DELAY - elapsed)
            self._last_request_time = time.time()

    async def connect(self) -> None:
        """Connect to Notion API and verify credentials.

        Raises:
            NotionAuthError: Authentication failed
            NotionAPIError: Connection failed
        """
        if self._connected:
            return

        try:
            # Register with health checker
            await self._health_checker.register("notion")

            headers = self._get_headers()
            await self._enforce_rate_limit()

            async with aiohttp.ClientSession() as session, session.get(
                f"{self.base_url}/users",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                if resp.status == 401:
                    raise NotionAuthError("Invalid Notion API key")
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to connect: {body}")

            headers = self._get_headers()
            self.pages = PageManager(self.base_url, headers)
            self.databases = DatabaseManager(self.base_url, headers)
            self.blocks = BlockManager(self.base_url, headers)
            self._connected = True
            log.info("Connected to Notion API")

        except NotionAuthError:
            raise
        except NotionAPIError:
            raise
        except Exception as e:
            raise NotionAPIError(f"Connection failed: {e}")

    async def disconnect(self) -> None:
        """Disconnect from Notion API."""
        self._connected = False
        self.pages = None
        self.databases = None
        self.blocks = None
        log.info("Disconnected from Notion API")

    async def health_check(self) -> bool:
        """Check if integration is healthy and connected.

        Returns:
            True if healthy, False otherwise
        """
        if not self._connected:
            return False

        try:
            if not self.api_key:
                return False

            headers = self._get_headers()
            await self._enforce_rate_limit()

            async with aiohttp.ClientSession() as session, session.get(
                f"{self.base_url}/users",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                return resp.status == 200

        except Exception as e:
            log.warning("Health check failed: %s", e)
            return False

    async def execute(
        self,
        operation: str,
        **kwargs: Any,
    ) -> Any:
        """Execute a Notion operation with hardening.

        Args:
            operation: Operation name (e.g., "get_page", "query_database")
            **kwargs: Operation arguments

        Returns:
            Operation result

        Raises:
            NotionAPIError: Operation failed
        """
        if not self._connected:
            raise NotionAPIError("Not connected to Notion API")

        # Apply rate limiting and circuit breaker
        await self._rate_limiter.acquire()

        start_time = time.time()
        try:
            await self._circuit_breaker.check()
            await self._enforce_rate_limit()

            # Page operations
            if operation == "get_page":
                result = await self.pages.get_page(kwargs.get("page_id", ""))
            elif operation == "create_page":
                result = await self.pages.create_page(
                    kwargs.get("parent_id", ""),
                    kwargs.get("properties", {}),
                    children=kwargs.get("children"),
                    is_database=kwargs.get("is_database", False),
                )
            elif operation == "update_page":
                result = await self.pages.update_page(
                    kwargs.get("page_id", ""),
                    kwargs.get("properties", {}),
                )
            elif operation == "archive_page":
                result = await self.pages.archive_page(kwargs.get("page_id", ""))
            elif operation == "get_page_content":
                result = await self.pages.get_page_content(
                    kwargs.get("page_id", ""),
                    page_size=kwargs.get("page_size", 100),
                    start_cursor=kwargs.get("start_cursor"),
                )
            elif operation == "append_blocks":
                result = await self.pages.append_blocks(
                    kwargs.get("page_id", ""),
                    kwargs.get("blocks", []),
                )
            elif operation == "search_pages":
                result = await self.pages.search_pages(
                    kwargs.get("query", ""),
                    filter_type=kwargs.get("filter_type"),
                    sort=kwargs.get("sort"),
                    page_size=kwargs.get("page_size", 100),
                    start_cursor=kwargs.get("start_cursor"),
                )
            # Database operations
            elif operation == "get_database":
                result = await self.databases.get_database(kwargs.get("database_id", ""))
            elif operation == "query_database":
                result = await self.databases.query_database(
                    kwargs.get("database_id", ""),
                    filter=kwargs.get("filter"),
                    sorts=kwargs.get("sorts"),
                    page_size=kwargs.get("page_size", 100),
                    start_cursor=kwargs.get("start_cursor"),
                )
            elif operation == "create_database":
                result = await self.databases.create_database(
                    kwargs.get("parent_id", ""),
                    kwargs.get("title", ""),
                    kwargs.get("properties", {}),
                    is_page_parent=kwargs.get("is_page_parent", True),
                )
            elif operation == "update_database":
                result = await self.databases.update_database(
                    kwargs.get("database_id", ""),
                    title=kwargs.get("title"),
                    properties=kwargs.get("properties"),
                )
            # Block operations
            elif operation == "get_block":
                result = await self.blocks.get_block(kwargs.get("block_id", ""))
            elif operation == "get_block_children":
                result = await self.blocks.get_block_children(
                    kwargs.get("block_id", ""),
                    page_size=kwargs.get("page_size", 100),
                    start_cursor=kwargs.get("start_cursor"),
                )
            elif operation == "update_block":
                result = await self.blocks.update_block(
                    kwargs.get("block_id", ""),
                    kwargs.get("content", {}),
                )
            elif operation == "delete_block":
                result = await self.blocks.delete_block(kwargs.get("block_id", ""))
            elif operation == "append_children":
                result = await self.blocks.append_children(
                    kwargs.get("block_id", ""),
                    kwargs.get("children", []),
                )
            else:
                raise NotionAPIError(f"Unknown operation: {operation}")

            # Record success
            latency_ms = (time.time() - start_time) * 1000
            await self._circuit_breaker.record_success()
            await self._health_checker.record_success("notion", latency_ms)

            return result

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            await self._circuit_breaker.record_failure()
            await self._health_checker.record_error("notion", e, latency_ms)
            raise

    async def __aenter__(self) -> NotionIntegration:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.disconnect()
