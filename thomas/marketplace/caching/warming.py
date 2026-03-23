"""Cache warming strategies with predictive loading."""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Generic, TypeVar

from ._types import CacheConfig, CacheStats

logger = logging.getLogger(__name__)

T = TypeVar("T")


class WarmingStrategy(ABC, Generic[T]):
    """Abstract base class for cache warming strategies."""

    @abstractmethod
    def get_warming_keys(self) -> list[tuple[str, T]]:
        """Get keys and values to warm into the cache.

        Returns:
            List of (key, value) tuples to load.
        """
        ...

    @abstractmethod
    def should_warm(self) -> bool:
        """Determine if warming should be triggered.

        Returns:
            True if warming should occur.
        """
        ...


class PatternBasedWarmer(WarmingStrategy[T]):
    """Warm cache based on access patterns.

    Tracks which keys are accessed together and preemptively
    loads related keys when one is accessed.

    Attributes:
        access_patterns: Map of key -> frequently accessed together keys.
    """

    def __init__(self, min_pattern_frequency: int = 3) -> None:
        """Initialize pattern-based warmer.

        Args:
            min_pattern_frequency: Minimum accesses to establish a pattern.
        """
        self.min_pattern_frequency = min_pattern_frequency
        self.access_patterns: dict[str, dict[str, int]] = {}
        self._lock = threading.Lock()

    def record_access(self, key: str, related_keys: list[str]) -> None:
        """Record an access pattern.

        Args:
            key: The key that was accessed.
            related_keys: Keys that were accessed in the same session.
        """
        with self._lock:
            if key not in self.access_patterns:
                self.access_patterns[key] = {}

            for related in related_keys:
                if related != key:
                    self.access_patterns[key][related] = self.access_patterns[key].get(related, 0) + 1

    def get_warming_keys(self) -> list[tuple[str, T]]:
        """Get keys based on strongest patterns.

        Returns:
            Empty list. Requires loader callback for actual values.
        """
        return []

    def should_warm(self) -> bool:
        """Patterns are warmed on demand, not periodically.

        Returns:
            False - warming triggered by access, not time.
        """
        return False

    def get_related_keys(self, key: str) -> list[str]:
        """Get keys that should be warmed based on a key access.

        Args:
            key: The accessed key.

        Returns:
            List of related keys that should be preloaded.
        """
        with self._lock:
            if key not in self.access_patterns:
                return []

            patterns = self.access_patterns[key]
            return [k for k, count in patterns.items() if count >= self.min_pattern_frequency]


class BatchWarmer(WarmingStrategy[T]):
    """Warm cache with a batch of key-value pairs."""

    def __init__(self, batch: dict[str, T]) -> None:
        """Initialize batch warmer.

        Args:
            batch: Dictionary of keys and values to warm.
        """
        self.batch = batch
        self._warmed = False

    def get_warming_keys(self) -> list[tuple[str, T]]:
        """Get the batch of keys to warm.

        Returns:
            List of (key, value) tuples.
        """
        return list(self.batch.items())

    def should_warm(self) -> bool:
        """Warm the batch once, then return False.

        Returns:
            True on first call, False afterward.
        """
        if not self._warmed:
            self._warmed = True
            return True
        return False


class ScheduledWarmer(WarmingStrategy[T]):
    """Warm cache on a regular schedule."""

    def __init__(
        self,
        interval: timedelta,
        loader: Callable[[], dict[str, T]],
    ) -> None:
        """Initialize scheduled warmer.

        Args:
            interval: How often to warm.
            loader: Function that returns keys/values to warm.
        """
        self.interval = interval
        self.loader = loader
        self._last_warm_time = datetime.utcnow()
        self._lock = threading.Lock()

    def get_warming_keys(self) -> list[tuple[str, T]]:
        """Load and return warming keys.

        Returns:
            List of (key, value) tuples from loader.
        """
        try:
            batch = self.loader()
            return list(batch.items())
        except Exception as e:
            logger.error("Error loading warming keys: %s", e)
            return []

    def should_warm(self) -> bool:
        """Check if enough time has passed since last warm.

        Returns:
            True if warming interval has elapsed.
        """
        with self._lock:
            now = datetime.utcnow()
            if now - self._last_warm_time >= self.interval:
                self._last_warm_time = now
                return True
            return False


class CacheWarmer(Generic[T]):
    """Manages cache warming strategies and execution.

    Coordinates multiple warming strategies and applies them
    to a cache. Monitors hit rates to trigger adaptive warming.

    Attributes:
        strategies: List of warming strategies.
    """

    def __init__(self, config: CacheConfig) -> None:
        """Initialize the cache warmer.

        Args:
            config: Cache configuration.
        """
        self.config = config
        self.strategies: list[WarmingStrategy[T]] = []
        self._cache_put_callback: Callable[[str, T], None] | None = None
        self._stats_callback: Callable[[], CacheStats] | None = None
        self._last_hit_rate = 0.0
        self._warming_thread: threading.Thread | None = None
        self._should_stop = False
        self._lock = threading.Lock()

        if config.enable_warming:
            self._start_warming_thread()

        logger.info("Initialized cache warmer")

    def add_strategy(self, strategy: WarmingStrategy[T]) -> None:
        """Add a warming strategy.

        Args:
            strategy: The warming strategy to add.
        """
        with self._lock:
            self.strategies.append(strategy)
            logger.debug("Added warming strategy: %s", type(strategy).__name__)

    def set_callbacks(
        self,
        put_callback: Callable[[str, T], None],
        stats_callback: Callable[[], CacheStats],
    ) -> None:
        """Set callbacks for cache operations.

        Args:
            put_callback: Function to call to put values in cache.
            stats_callback: Function to call to get current stats.
        """
        self._cache_put_callback = put_callback
        self._stats_callback = stats_callback

    def warm(self) -> int:
        """Execute all active warming strategies.

        Returns:
            The number of entries warmed.
        """
        if self._cache_put_callback is None or self._stats_callback is None:
            logger.warning("Warming requested but callbacks not set")
            return 0

        with self._lock:
            warmed_count = 0

            for strategy in self.strategies:
                if not strategy.should_warm():
                    continue

                try:
                    keys_and_values = strategy.get_warming_keys()
                    for key, value in keys_and_values:
                        self._cache_put_callback(key, value)
                        warmed_count += 1

                    if warmed_count > 0:
                        logger.debug(
                            "Warmed %d entries using %s",
                            warmed_count,
                            type(strategy).__name__,
                        )

                except Exception as e:
                    logger.error("Error during warming: %s", e)

            return warmed_count

    def check_hit_rate(self, threshold: float = 0.7) -> bool:
        """Check if hit rate has dropped below threshold.

        Triggers adaptive warming if hit rate declines.

        Args:
            threshold: Hit rate threshold (0.0-1.0).

        Returns:
            True if hit rate is below threshold.
        """
        if self._stats_callback is None:
            return False

        stats = self._stats_callback()
        current_hit_rate = stats.hit_rate

        if current_hit_rate < threshold:
            logger.warning(
                "Cache hit rate below threshold: %.2f%% < %.2f%%",
                current_hit_rate * 100,
                threshold * 100,
            )
            self._last_hit_rate = current_hit_rate
            return True

        self._last_hit_rate = current_hit_rate
        return False

    def shutdown(self) -> None:
        """Shutdown the warming thread."""
        self._stop_warming_thread()
        logger.info("Cache warmer shutdown")

    def _start_warming_thread(self) -> None:
        """Start the background warming thread."""
        if self._warming_thread is not None:
            return

        self._should_stop = False
        self._warming_thread = threading.Thread(
            target=self._warming_worker,
            daemon=True,
            name="CacheWarmer",
        )
        self._warming_thread.start()
        logger.debug("Started cache warming thread")

    def _stop_warming_thread(self) -> None:
        """Stop the background warming thread."""
        if self._warming_thread is None:
            return

        self._should_stop = True
        if self._warming_thread.is_alive():
            self._warming_thread.join(timeout=5.0)
        self._warming_thread = None

    def _warming_worker(self) -> None:
        """Background worker that periodically warms the cache."""
        interval = self.config.warming_interval.total_seconds()

        while not self._should_stop:
            try:
                time.sleep(interval)
                if not self._should_stop:
                    warmed = self.warm()
                    if warmed > 0:
                        logger.debug("Background warming completed: %d entries", warmed)
            except Exception as e:
                logger.error("Error in cache warming worker: %s", e)
