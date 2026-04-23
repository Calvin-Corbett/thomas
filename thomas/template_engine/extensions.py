"""Extension system for template engine."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ._types import Context, Extension


class ExtensionRegistry:
    """Registry for template extensions."""

    def __init__(self) -> None:
        """Initialize extension registry."""
        self.extensions: dict[str, Extension] = {}
        self.filters: dict[str, Callable[..., Any]] = {}
        self.tests: dict[str, Callable[[Any, ...], bool]] = {}
        self.tags: dict[str, Callable[..., Any]] = {}
        self.hooks: dict[str, list[Callable[..., Any]]] = {
            "before_render": [],
            "after_render": [],
            "on_error": [],
        }

    def register(self, ext: Extension) -> None:
        """Register an extension."""
        self.extensions[ext.name] = ext
        self.filters.update(ext.filters)
        self.tests.update(ext.tests)
        self.tags.update(ext.tags)

        # Register hooks
        if hasattr(ext, "before_render"):
            self.hooks["before_render"].append(ext.before_render)
        if hasattr(ext, "after_render"):
            self.hooks["after_render"].append(ext.after_render)
        if hasattr(ext, "on_error"):
            self.hooks["on_error"].append(ext.on_error)

    def get_filter(self, name: str) -> Callable[..., Any] | None:
        """Get filter from registry."""
        return self.filters.get(name)

    def get_test(self, name: str) -> Callable[[Any, ...], bool] | None:
        """Get test function from registry."""
        return self.tests.get(name)

    def get_tag(self, name: str) -> Callable[..., Any] | None:
        """Get tag handler from registry."""
        return self.tags.get(name)

    def call_hook(self, hook: str, *args: Any, **kwargs: Any) -> Any | None:
        """Call extension hook."""
        result = None
        for handler in self.hooks.get(hook, []):
            result = handler(*args, **kwargs)
        return result


class I18nExtension(Extension):
    """Internationalization extension (gettext-compatible)."""

    def __init__(self, gettext_func: Callable[[str], str] | None = None) -> None:
        """
        Initialize i18n extension.

        Args:
            gettext_func: Translation function
        """
        super().__init__(name="i18n")

        # Default gettext function (identity)
        self._gettext = gettext_func or (lambda x: x)
        self._ngettext = self._default_ngettext

        # Add filters
        self.filters["gettext"] = self._filter_gettext
        self.filters["_"] = self._filter_gettext
        self.filters["ngettext"] = self._filter_ngettext

        # Add tests
        self.tests["marked"] = lambda x: hasattr(x, "_marked_for_translation")

        # Add globals
        self.globals["gettext"] = self._gettext
        self.globals["ngettext"] = self._ngettext

    def _filter_gettext(self, text: str) -> str:
        """Translate string."""
        return self._gettext(text)

    def _filter_ngettext(self, singular: str, plural: str, count: int) -> str:
        """Translate with plural form."""
        return self._ngettext(singular, plural, count)

    def _default_ngettext(self, singular: str, plural: str, count: int) -> str:
        """Default ngettext implementation."""
        return singular if count == 1 else plural


class DebugExtension(Extension):
    """Debug extension for profiling and inspection."""

    def __init__(self) -> None:
        """Initialize debug extension."""
        super().__init__(name="debug")

        self.timings: dict[str, float] = {}
        self.render_start: float | None = None

        # Add filters
        self.filters["debug"] = self._filter_debug
        self.filters["timing"] = self._filter_timing

        # Add globals
        self.globals["debug"] = self._debug_helper

    def _filter_debug(self, value: Any) -> str:
        """Debug filter - pretty print value."""
        import pprint

        return pprint.pformat(value)

    def _filter_timing(self, name: str) -> str:
        """Get timing information."""
        if name in self.timings:
            return f"{self.timings[name]:.4f}s"
        return "N/A"

    def _debug_helper(self) -> dict[str, Any]:
        """Debug helper object."""
        return {
            "timings": self.timings,
            "elapsed": time.time() - (self.render_start or time.time()),
        }

    def before_render(self, context: Context) -> None:
        """Hook: before rendering."""
        self.render_start = time.time()

    def after_render(self, output: str, context: Context) -> str:
        """Hook: after rendering."""
        elapsed = time.time() - (self.render_start or time.time())
        self.timings["total"] = elapsed
        return output


class CacheExtension(Extension):
    """Fragment caching extension."""

    def __init__(self, ttl: int = 3600) -> None:
        """
        Initialize cache extension.

        Args:
            ttl: Cache time-to-live in seconds
        """
        super().__init__(name="cache")

        self.ttl = ttl
        self.cache: dict[str, tuple[str, float]] = {}
        self.lock = None  # In real implementation, would use thread lock

        # Add filters
        self.filters["cache"] = self._filter_cache

        # Add tags
        self.tags["cache"] = self._tag_cache

    def _filter_cache(self, content: str, key: str, ttl: int | None = None) -> str:
        """Cache filter."""
        cache_ttl = ttl or self.ttl
        current_time = time.time()

        # Check cache
        if key in self.cache:
            cached_content, expires = self.cache[key]
            if current_time < expires:
                return cached_content

        # Store in cache
        self.cache[key] = (content, current_time + cache_ttl)
        return content

    def _tag_cache(self, key: str, ttl: int | None = None) -> Callable:
        """Cache tag handler."""

        def cache_tag(content: str) -> str:
            return self._filter_cache(content, key, ttl)

        return cache_tag

    def invalidate(self, key: str | None = None) -> None:
        """Invalidate cache entry or all cache."""
        if key:
            self.cache.pop(key, None)
        else:
            self.cache.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        current_time = time.time()
        valid_entries = sum(1 for _, expires in self.cache.values() if current_time < expires)
        return {
            "total_entries": len(self.cache),
            "valid_entries": valid_entries,
            "expired_entries": len(self.cache) - valid_entries,
        }


class AssetsExtension(Extension):
    """Assets management extension."""

    def __init__(self, asset_path: str = "/static") -> None:
        """
        Initialize assets extension.

        Args:
            asset_path: Base path for assets
        """
        super().__init__(name="assets")

        self.asset_path = asset_path
        self.assets: dict[str, list[str]] = {}

        # Add filters
        self.filters["asset"] = self._filter_asset
        self.filters["asset_url"] = self._filter_asset_url

    def _filter_asset(self, filename: str) -> str:
        """Get asset URL."""
        return f"{self.asset_path}/{filename}"

    def _filter_asset_url(self, name: str, filename: str) -> str:
        """Get asset URL with collection."""
        if name not in self.assets:
            self.assets[name] = []
        self.assets[name].append(filename)
        return f"{self.asset_path}/{filename}"

    def register_asset(self, collection: str, filename: str) -> None:
        """Register asset in collection."""
        if collection not in self.assets:
            self.assets[collection] = []
        self.assets[collection].append(filename)

    def get_assets(self, collection: str) -> list[str]:
        """Get assets in collection."""
        return self.assets.get(collection, [])


class SafetyExtension(Extension):
    """Security/safety extension."""

    DANGEROUS_ATTRS = {
        "__class__",
        "__dict__",
        "__bases__",
        "__subclasses__",
        "__globals__",
        "__code__",
        "__builtins__",
        "mro",
        "__import__",
        "eval",
        "exec",
        "compile",
    }

    def __init__(self) -> None:
        """Initialize safety extension."""
        super().__init__(name="safety")

        self.allowed_attrs: set[str] = set()

    def is_safe_attribute(self, obj: Any, attr: str) -> bool:
        """Check if attribute access is safe."""
        if attr in self.DANGEROUS_ATTRS:
            return False

        if attr.startswith("_"):
            return False

        return True

    def whitelist_attribute(self, attr: str) -> None:
        """Whitelist an attribute."""
        self.allowed_attrs.add(attr)

    def before_render(self, context: Context) -> None:
        """Hook: before rendering."""
        # Could add security checks to context here
        pass
