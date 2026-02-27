"""Platform compatibility layer for cross-platform support.

Provides OS detection, feature flags, polyfills, and
platform-specific abstraction layers.
"""

from .core import (
    Architecture,
    FeatureFlag,
    FeatureFlagRegistry,
    OSType,
    PlatformAbstraction,
    PlatformDetector,
    Polyfill,
    PolyfillManager,
)

__all__ = [
    "OSType",
    "Architecture",
    "PlatformDetector",
    "FeatureFlag",
    "FeatureFlagRegistry",
    "Polyfill",
    "PolyfillManager",
    "PlatformAbstraction",
]

__version__ = "1.0.0"
