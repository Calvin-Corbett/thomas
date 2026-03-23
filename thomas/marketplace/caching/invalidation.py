"""Cache invalidation strategies."""

from __future__ import annotations

import logging
import re
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable

logger = logging.getLogger(__name__)


class InvalidationStrategy(ABC):
    """Abstract base class for invalidation strategies."""

    @abstractmethod
    def should_invalidate(self, key: str) -> bool:
        """Determine if a key should be invalidated.

        Args:
            key: The cache key.

        Returns:
            True if the key should be invalidated.
        """
        ...


class TagBasedInvalidation(InvalidationStrategy):
    """Invalidate keys based on tags.

    Each key can have multiple tags, and invalidating a tag
    invalidates all keys with that tag.

    Attributes:
        key_tags: Maps keys to sets of tags.
    """

    def __init__(self) -> None:
        """Initialize tag-based invalidation."""
        self.key_tags: dict[str, set[str]] = {}
        self._invalid_tags: set[str] = set()
        self._lock = threading.RLock()

    def tag_key(self, key: str, *tags: str) -> None:
        """Tag a key with one or more tags.

        Args:
            key: The cache key.
            tags: Tags to apply.
        """
        with self._lock:
            if key not in self.key_tags:
                self.key_tags[key] = set()
            self.key_tags[key].update(tags)
            logger.debug("Tagged key %s with: %s", key, tags)

    def untag_key(self, key: str, tag: str | None = None) -> None:
        """Remove tags from a key.

        Args:
            key: The cache key.
            tag: Specific tag to remove, or None to remove all tags.
        """
        with self._lock:
            if key not in self.key_tags:
                return

            if tag is None:
                del self.key_tags[key]
            else:
                self.key_tags[key].discard(tag)
                if not self.key_tags[key]:
                    del self.key_tags[key]

            logger.debug("Untagged key: %s (tag=%s)", key, tag)

    def invalidate_tag(self, tag: str) -> int:
        """Invalidate all keys with a specific tag.

        Args:
            tag: The tag to invalidate.

        Returns:
            Number of keys that will be invalidated.
        """
        with self._lock:
            self._invalid_tags.add(tag)
            affected_keys = [key for key, tags in self.key_tags.items() if tag in tags]
            logger.info("Invalidated tag: %s (affects %d keys)", tag, len(affected_keys))
            return len(affected_keys)

    def invalidate_tags(self, *tags: str) -> int:
        """Invalidate multiple tags at once.

        Args:
            tags: The tags to invalidate.

        Returns:
            Total number of affected keys.
        """
        total = 0
        for tag in tags:
            total += self.invalidate_tag(tag)
        return total

    def should_invalidate(self, key: str) -> bool:
        """Check if a key should be invalidated.

        Args:
            key: The cache key.

        Returns:
            True if key has any invalid tags.
        """
        with self._lock:
            if key not in self.key_tags:
                return False

            key_tags = self.key_tags[key]
            return any(tag in self._invalid_tags for tag in key_tags)

    def reset_invalid_tags(self) -> None:
        """Clear the set of invalid tags."""
        with self._lock:
            self._invalid_tags.clear()

    def get_tags_for_key(self, key: str) -> set[str]:
        """Get all tags for a key.

        Args:
            key: The cache key.

        Returns:
            Set of tags, or empty set if key not found.
        """
        with self._lock:
            return self.key_tags.get(key, set()).copy()


class PatternBasedInvalidation(InvalidationStrategy):
    """Invalidate keys matching regex patterns.

    Attributes:
        invalid_patterns: Set of regex patterns for invalid keys.
    """

    def __init__(self) -> None:
        """Initialize pattern-based invalidation."""
        self.invalid_patterns: set[str] = set()
        self._compiled_patterns: list[re.Pattern] = []
        self._lock = threading.RLock()

    def add_pattern(self, pattern: str) -> None:
        """Add a regex pattern for invalidation.

        Args:
            pattern: A regex pattern string.

        Raises:
            re.error: If pattern is invalid regex.
        """
        with self._lock:
            try:
                compiled = re.compile(pattern)
                self.invalid_patterns.add(pattern)
                self._compiled_patterns.append(compiled)
                logger.debug("Added invalidation pattern: %s", pattern)
            except re.error as e:
                logger.error("Invalid invalidation pattern: %s - %s", pattern, e)
                raise

    def remove_pattern(self, pattern: str) -> bool:
        """Remove a pattern.

        Args:
            pattern: The pattern to remove.

        Returns:
            True if pattern was removed.
        """
        with self._lock:
            if pattern in self.invalid_patterns:
                self.invalid_patterns.discard(pattern)
                self._compiled_patterns = [re.compile(p) for p in self.invalid_patterns]
                logger.debug("Removed invalidation pattern: %s", pattern)
                return True
            return False

    def should_invalidate(self, key: str) -> bool:
        """Check if a key matches any invalid patterns.

        Args:
            key: The cache key.

        Returns:
            True if key matches any pattern.
        """
        with self._lock:
            return any(pattern.match(key) for pattern in self._compiled_patterns)

    def clear_patterns(self) -> None:
        """Clear all patterns."""
        with self._lock:
            self.invalid_patterns.clear()
            self._compiled_patterns.clear()


class CascadingInvalidation(InvalidationStrategy):
    """Invalidate keys based on dependencies.

    When a key is invalidated, all dependent keys are also invalidated.

    Attributes:
        dependencies: Maps keys to their dependent keys.
    """

    def __init__(self) -> None:
        """Initialize cascading invalidation."""
        self.dependencies: dict[str, set[str]] = {}
        self._invalid_keys: set[str] = set()
        self._lock = threading.RLock()

    def add_dependency(self, key: str, depends_on: str) -> None:
        """Add a dependency relationship.

        Args:
            key: The dependent key.
            depends_on: The key it depends on.
        """
        with self._lock:
            if depends_on not in self.dependencies:
                self.dependencies[depends_on] = set()
            self.dependencies[depends_on].add(key)
            logger.debug("Added dependency: %s depends on %s", key, depends_on)

    def invalidate_key(self, key: str) -> int:
        """Invalidate a key and cascade to dependents.

        Args:
            key: The key to invalidate.

        Returns:
            Total number of cascaded invalidations.
        """
        with self._lock:
            if key in self._invalid_keys:
                return 0

            direct_dependents = set(self.dependencies.get(key, set()))
            self._invalidate_recursive(key)
            cascaded_count = 1 + sum(1 for dependent in direct_dependents if dependent in self._invalid_keys)

            logger.info("Invalidated key with cascading: %s (total: %d)", key, cascaded_count)
            return cascaded_count

    def _invalidate_recursive(self, key: str) -> None:
        """Recursively invalidate a key and all transitive dependents.

        Callers must hold ``self._lock``.
        """
        if key in self._invalid_keys:
            return

        self._invalid_keys.add(key)
        for dependent in self.dependencies.get(key, set()):
            self._invalidate_recursive(dependent)

    def should_invalidate(self, key: str) -> bool:
        """Check if a key is invalid.

        Args:
            key: The cache key.

        Returns:
            True if the key is marked invalid.
        """
        with self._lock:
            return key in self._invalid_keys

    def get_dependents(self, key: str) -> set[str]:
        """Get all keys that depend on a key.

        Args:
            key: The cache key.

        Returns:
            Set of dependent keys.
        """
        with self._lock:
            return self.dependencies.get(key, set()).copy()

    def reset_invalid_keys(self) -> None:
        """Clear all invalid keys."""
        with self._lock:
            self._invalid_keys.clear()


class InvalidationBus:
    """Publish-subscribe bus for cache invalidation events.

    Allows multiple subscribers to be notified of invalidation events.
    """

    def __init__(self) -> None:
        """Initialize the invalidation bus."""
        self._subscribers: list[Callable[[str], None]] = []
        self._lock = threading.RLock()
        self._event_count = 0

    def subscribe(self, callback: Callable[[str], None]) -> None:
        """Subscribe to invalidation events.

        Args:
            callback: Function to call with invalidated keys.
        """
        with self._lock:
            self._subscribers.append(callback)
            logger.debug("Added subscriber to invalidation bus")

    def unsubscribe(self, callback: Callable[[str], None]) -> bool:
        """Unsubscribe from invalidation events.

        Args:
            callback: The callback to remove.

        Returns:
            True if callback was removed.
        """
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)
                logger.debug("Removed subscriber from invalidation bus")
                return True
            return False

    def publish(self, key: str) -> None:
        """Publish an invalidation event.

        Args:
            key: The key that was invalidated.
        """
        with self._lock:
            self._event_count += 1
            subscribers = self._subscribers.copy()

        # Notify subscribers outside the lock
        for callback in subscribers:
            try:
                callback(key)
            except Exception as e:
                logger.error("Error notifying invalidation subscriber: %s", e)

    def event_count(self) -> int:
        """Get the number of events published.

        Returns:
            Total event count.
        """
        with self._lock:
            return self._event_count


class InvalidationManager:
    """Manages multiple invalidation strategies.

    Combines tag-based, pattern-based, and cascading invalidation.
    """

    def __init__(self) -> None:
        """Initialize the invalidation manager."""
        self.tag_strategy = TagBasedInvalidation()
        self.pattern_strategy = PatternBasedInvalidation()
        self.cascading_strategy = CascadingInvalidation()
        self.bus = InvalidationBus()
        self._lock = threading.RLock()

    def should_invalidate(self, key: str) -> bool:
        """Check if a key should be invalidated by any strategy.

        Args:
            key: The cache key.

        Returns:
            True if any strategy marks it as invalid.
        """
        return (
            self.tag_strategy.should_invalidate(key)
            or self.pattern_strategy.should_invalidate(key)
            or self.cascading_strategy.should_invalidate(key)
        )

    def invalidate(self, key: str) -> None:
        """Invalidate a key using cascading strategy and publish event.

        Args:
            key: The key to invalidate.
        """
        with self._lock:
            self.cascading_strategy.invalidate_key(key)
            self.bus.publish(key)
            logger.info("Invalidated key via manager: %s", key)
