"""
Retry decorator with exponential backoff and jitter.

Features:
- Exponential backoff with random jitter
- Respects Retry-After headers
- Configurable retryable errors
- Detailed logging of retry attempts
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry(
    max_attempts: int = 3,
    backoff_factor: float = 1.5,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_errors: tuple[type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
    ),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Retry decorator with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (including initial)
        backoff_factor: Multiplier for exponential backoff
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        retryable_errors: Tuple of exception types to retry on

    Returns:
        Decorated function that retries on failure
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            last_error = None

            while attempt < max_attempts:
                try:
                    return await func(*args, **kwargs)

                except Exception as e:
                    last_error = e
                    attempt += 1

                    # Check if error is retryable
                    is_retryable = isinstance(e, retryable_errors)

                    # Also retry on 429 (rate limit), 500, 502, 503 if HTTP error
                    if hasattr(e, "status"):
                        is_retryable = is_retryable or e.status in (429, 500, 502, 503)

                    if not is_retryable:
                        logger.error(f"{func.__name__}: non-retryable error: {type(e).__name__}: {e}")
                        raise

                    if attempt >= max_attempts:
                        logger.error(
                            f"{func.__name__}: max retries ({max_attempts}) exhausted. "
                            f"Last error: {type(e).__name__}: {e}"
                        )
                        raise

                    # Calculate backoff with jitter
                    delay = min(
                        initial_delay * (backoff_factor ** (attempt - 1)),
                        max_delay,
                    )
                    # Add jitter (±20%)
                    jitter = delay * random.uniform(0.8, 1.2)

                    # Check for Retry-After header
                    retry_after = None
                    if hasattr(e, "retry_after"):
                        retry_after = e.retry_after
                    elif hasattr(e, "headers") and "Retry-After" in e.headers:
                        try:
                            retry_after = int(e.headers["Retry-After"])
                        except (ValueError, TypeError):
                            pass

                    if retry_after is not None:
                        jitter = float(retry_after)

                    logger.warning(
                        f"{func.__name__}: attempt {attempt}/{max_attempts} failed "
                        f"({type(e).__name__}: {e}), retrying in {jitter:.2f}s"
                    )

                    await asyncio.sleep(jitter)

            # All retries exhausted
            if last_error:
                raise last_error

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            last_error = None

            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    last_error = e
                    attempt += 1

                    is_retryable = isinstance(e, retryable_errors)
                    if hasattr(e, "status"):
                        is_retryable = is_retryable or e.status in (429, 500, 502, 503)

                    if not is_retryable:
                        logger.error(f"{func.__name__}: non-retryable error: {type(e).__name__}: {e}")
                        raise

                    if attempt >= max_attempts:
                        logger.error(
                            f"{func.__name__}: max retries ({max_attempts}) exhausted. "
                            f"Last error: {type(e).__name__}: {e}"
                        )
                        raise

                    delay = min(
                        initial_delay * (backoff_factor ** (attempt - 1)),
                        max_delay,
                    )
                    jitter = delay * random.uniform(0.8, 1.2)

                    logger.warning(
                        f"{func.__name__}: attempt {attempt}/{max_attempts} failed "
                        f"({type(e).__name__}: {e}), retrying in {jitter:.2f}s"
                    )

                    asyncio.run(asyncio.sleep(jitter))

            if last_error:
                raise last_error

        # Return appropriate wrapper
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
