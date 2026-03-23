"""
Query bus and query handling infrastructure.

Implements QueryBus for dispatching queries to handlers, caching with TTL,
middleware support, and pagination handling.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, Protocol, TypeVar

from ._exceptions import (
    QueryExecutionException,
    QueryTimeoutException,
)
from ._types import Query, QueryResult, T

TQuery = TypeVar("TQuery", bound=Query)
TQueryResult = TypeVar("TQueryResult")


class QueryHandler(Protocol[TQuery, TQueryResult]):
    """
    Protocol for query handlers.

    Handlers receive a query and return results.
    """

    async def handle(self, query: TQuery) -> QueryResult[TQueryResult]:
        """
        Handle a query.

        Args:
            query: Query to handle

        Returns:
            QueryResult with data
        """
        ...


class QueryMiddleware(ABC):
    """
    Base class for query middleware.

    Middleware can intercept queries for logging, caching,
    security, or other cross-cutting concerns.
    """

    @abstractmethod
    async def handle(
        self,
        query: Query,
        next_handler: Callable[[Query], Awaitable[QueryResult[Any]]],
    ) -> QueryResult[Any]:
        """
        Process a query through middleware.

        Args:
            query: The query to process
            next_handler: Next middleware in chain

        Returns:
            QueryResult from handler
        """
        pass


@dataclass
class CacheEntry(Generic[T]):
    """Entry in query cache."""

    data: T
    timestamp: datetime
    ttl_seconds: int

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        age = (datetime.utcnow() - self.timestamp).total_seconds()
        return age > self.ttl_seconds


@dataclass
class PaginationParams:
    """Parameters for paginated queries."""

    offset: int = 0
    limit: int = 10
    max_limit: int = 100

    def __post_init__(self) -> None:
        """Validate parameters."""
        if self.offset < 0:
            raise ValueError("offset must be non-negative")
        if self.limit < 1:
            raise ValueError("limit must be at least 1")
        if self.limit > self.max_limit:
            self.limit = self.max_limit


class QueryCache:
    """
    Cache for query results with TTL support.

    Stores query results and evicts based on time-to-live.
    """

    def __init__(self, max_entries: int = 1000) -> None:
        """
        Initialize query cache.

        Args:
            max_entries: Maximum cache entries before eviction
        """
        self.max_entries = max_entries
        self._cache: dict[str, CacheEntry[Any]] = {}
        self._lock = asyncio.Lock()

    def _make_key(self, query: Query, **kwargs: Any) -> str:
        """
        Generate cache key from query.

        Args:
            query: Query to key
            **kwargs: Additional parameters

        Returns:
            Cache key string
        """
        query_dict = vars(query).copy()
        query_dict.update(kwargs)

        # Sort for consistent ordering
        items = sorted(query_dict.items())
        key_str = str(items)
        return hashlib.md5(key_str.encode()).hexdigest()

    async def get(self, query: Query, **kwargs: Any) -> Any | None:
        """
        Retrieve cached query result.

        Args:
            query: Query to retrieve
            **kwargs: Additional parameters

        Returns:
            Cached data or None if expired/missing
        """
        async with self._lock:
            key = self._make_key(query, **kwargs)
            entry = self._cache.get(key)

            if entry is None:
                return None

            if entry.is_expired():
                del self._cache[key]
                return None

            return entry.data

    async def set(
        self,
        query: Query,
        data: Any,
        ttl_seconds: int = 300,
        **kwargs: Any,
    ) -> None:
        """
        Cache query result.

        Args:
            query: Query being cached
            data: Result data
            ttl_seconds: Time-to-live in seconds
            **kwargs: Additional parameters
        """
        async with self._lock:
            # Evict if at capacity
            if len(self._cache) >= self.max_entries:
                # Remove oldest entry
                oldest_key = min(
                    self._cache.keys(),
                    key=lambda k: self._cache[k].timestamp,
                )
                del self._cache[oldest_key]

            key = self._make_key(query, **kwargs)
            self._cache[key] = CacheEntry(
                data=data,
                timestamp=datetime.utcnow(),
                ttl_seconds=ttl_seconds,
            )

    async def invalidate(self, query: Query, **kwargs: Any) -> None:
        """
        Invalidate cached query result.

        Args:
            query: Query to invalidate
            **kwargs: Additional parameters
        """
        async with self._lock:
            key = self._make_key(query, **kwargs)
            self._cache.pop(key, None)

    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()

    async def size(self) -> int:
        """Get current cache size."""
        async with self._lock:
            return len(self._cache)


class CachingMiddleware(QueryMiddleware):
    """
    Middleware that caches query results.

    Checks cache before executing query handler.
    """

    def __init__(
        self,
        cache: QueryCache | None = None,
        ttl_seconds: int = 300,
    ) -> None:
        """
        Initialize caching middleware.

        Args:
            cache: Cache instance
            ttl_seconds: Default TTL for cached results
        """
        self.cache = cache or QueryCache()
        self.ttl_seconds = ttl_seconds

    async def handle(
        self,
        query: Query,
        next_handler: Callable[[Query], Awaitable[QueryResult[Any]]],
    ) -> QueryResult[Any]:
        """Check cache and execute if needed."""
        cached = await self.cache.get(query)
        if cached is not None:
            return QueryResult(data=cached, cached=True)

        result = await next_handler(query)

        # Cache result
        await self.cache.set(query, result.data, ttl_seconds=self.ttl_seconds)

        return result


class TimeoutMiddleware(QueryMiddleware):
    """
    Middleware that enforces query execution timeouts.

    Cancels query if it exceeds timeout.
    """

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        """
        Initialize timeout middleware.

        Args:
            timeout_seconds: Timeout limit
        """
        self.timeout_seconds = timeout_seconds

    async def handle(
        self,
        query: Query,
        next_handler: Callable[[Query], Awaitable[QueryResult[Any]]],
    ) -> QueryResult[Any]:
        """Execute with timeout."""
        try:
            return await asyncio.wait_for(
                next_handler(query),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise QueryTimeoutException(f"Query execution exceeded {self.timeout_seconds}s timeout")


class LoggingMiddleware(QueryMiddleware):
    """Middleware that logs query execution."""

    async def handle(
        self,
        query: Query,
        next_handler: Callable[[Query], Awaitable[QueryResult[Any]]],
    ) -> QueryResult[Any]:
        """Log query and pass to next handler."""
        start_time = time.time()
        result = await next_handler(query)
        duration = time.time() - start_time
        return result


class QueryBus:
    """
    Central dispatcher for query handling.

    Routes queries to registered handlers, applies middleware,
    and manages query execution lifecycle.
    """

    def __init__(self) -> None:
        """Initialize query bus."""
        self._handlers: dict[type, Callable[[Any], Awaitable[QueryResult[Any]]]] = {}
        self._middleware: list[QueryMiddleware] = []

    def register_handler(
        self,
        query_type: type[TQuery],
        handler: Callable[[TQuery], Awaitable[QueryResult[TQueryResult]]],
    ) -> None:
        """
        Register query handler.

        Args:
            query_type: Type of query to handle
            handler: Handler function
        """
        self._handlers[query_type] = handler

    def add_middleware(self, middleware: QueryMiddleware) -> None:
        """
        Add middleware to query pipeline.

        Middleware is applied in registration order.

        Args:
            middleware: Middleware to add
        """
        self._middleware.append(middleware)

    async def execute(self, query: Query) -> QueryResult[Any]:
        """
        Execute a query.

        Routes to registered handler and applies middleware chain.

        Args:
            query: Query to execute

        Returns:
            QueryResult with data

        Raises:
            QueryExecutionException: If no handler registered
        """
        handler = self._handlers.get(type(query))
        if not handler:
            raise QueryExecutionException(f"No handler registered for {type(query).__name__}")

        # Build middleware chain
        async def final_handler(q: Query) -> QueryResult[Any]:
            return await handler(q)

        async def apply_middleware(
            q: Query,
            middleware_list: list[QueryMiddleware],
        ) -> QueryResult[Any]:
            if not middleware_list:
                return await final_handler(q)

            current_middleware = middleware_list[0]
            remaining = middleware_list[1:]

            async def next_handler(query_inner: Query) -> QueryResult[Any]:
                return await apply_middleware(query_inner, remaining)

            return await current_middleware.handle(q, next_handler)

        return await apply_middleware(query, self._middleware)

    def get_handler(self, query_type: type) -> Callable | None:
        """
        Get handler for query type.

        Args:
            query_type: Type to look up

        Returns:
            Handler or None
        """
        return self._handlers.get(query_type)

    def handlers(self) -> dict[type, Callable]:
        """
        Get all registered handlers.

        Returns:
            Dictionary of query type to handler
        """
        return self._handlers.copy()

    def middleware(self) -> list[QueryMiddleware]:
        """
        Get all registered middleware.

        Returns:
            List of middleware in order
        """
        return self._middleware.copy()
