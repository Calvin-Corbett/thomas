"""Platform compatibility layer for OS detection and feature flags.

Provides cross-platform abstractions, feature flag management,
and polyfill implementations.
"""

import platform
import sys
from abc import ABC
from collections.abc import Callable
from enum import Enum
from typing import Any


class OSType(Enum):
    """Supported operating systems."""

    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"
    FREEBSD = "freebsd"
    ANDROID = "android"
    IOS = "ios"


class Architecture(Enum):
    """CPU architectures."""

    X86_64 = "x86_64"
    ARM64 = "arm64"
    ARM32 = "arm32"
    PPC64 = "ppc64"
    MIPS = "mips"


class PlatformDetector:
    """Detect platform characteristics."""

    @staticmethod
    def get_os() -> OSType:
        """Detect operating system."""
        system = platform.system()
        if system == "Linux":
            return OSType.LINUX
        elif system == "Windows":
            return OSType.WINDOWS
        elif system == "Darwin":
            return OSType.MACOS
        elif system == "FreeBSD":
            return OSType.FREEBSD
        else:
            return OSType.LINUX

    @staticmethod
    def get_architecture() -> Architecture:
        """Detect CPU architecture."""
        machine = platform.machine()
        if machine in ["x86_64", "AMD64"]:
            return Architecture.X86_64
        elif machine in ["arm64", "aarch64"]:
            return Architecture.ARM64
        elif machine.startswith("arm"):
            return Architecture.ARM32
        elif machine.startswith("ppc"):
            return Architecture.PPC64
        else:
            return Architecture.X86_64

    @staticmethod
    def get_python_version() -> str:
        """Get Python version."""
        return platform.python_version()

    @staticmethod
    def is_64bit() -> bool:
        """Check if 64-bit system."""
        return sys.maxsize > 2**32

    @staticmethod
    def get_platform_string() -> str:
        """Get platform string."""
        return platform.platform()


class FeatureFlag:
    """Feature flag."""

    def __init__(self, name: str, enabled: bool, platforms: list | None = None, description: str = ""):
        self.name = name
        self.enabled = enabled
        self.platforms = platforms or []
        self.description = description

    def is_available(self, os_type: OSType) -> bool:
        """Check if available on OS."""
        if not self.enabled:
            return False
        if not self.platforms:
            return True
        return os_type in self.platforms


class FeatureFlagRegistry:
    """Registry for feature flags."""

    def __init__(self):
        self.flags: dict[str, FeatureFlag] = {}
        self.detector = PlatformDetector()

    def register(self, flag: FeatureFlag) -> None:
        """Register feature flag."""
        self.flags[flag.name] = flag

    def is_enabled(self, flag_name: str) -> bool:
        """Check if flag is enabled."""
        flag = self.flags.get(flag_name)
        if not flag:
            return False
        os_type = self.detector.get_os()
        return flag.is_available(os_type)

    def get_all_flags(self) -> dict[str, FeatureFlag]:
        """Get all flags."""
        return self.flags.copy()


class Polyfill(ABC):
    """Base polyfill."""

    def __init__(self, name: str):
        self.name = name

    def apply(self) -> None:
        """Apply polyfill."""
        pass


class PolyfillManager:
    """Manage polyfills."""

    def __init__(self):
        self.polyfills: dict[str, Polyfill] = {}

    def register(self, polyfill: Polyfill) -> None:
        """Register polyfill."""
        self.polyfills[polyfill.name] = polyfill

    def apply_all(self) -> None:
        """Apply all polyfills."""
        for polyfill in self.polyfills.values():
            polyfill.apply()

    def apply_by_name(self, name: str) -> bool:
        """Apply specific polyfill."""
        polyfill = self.polyfills.get(name)
        if polyfill:
            polyfill.apply()
            return True
        return False


class PlatformAbstraction:
    """Platform abstraction layer."""

    def __init__(self):
        self.detector = PlatformDetector()
        self.features = FeatureFlagRegistry()
        self.polyfills = PolyfillManager()
        self.implementations: dict[str, dict[OSType, Callable]] = {}

    def register_implementation(self, name: str, os_type: OSType, implementation: Callable) -> None:
        """Register OS-specific implementation."""
        if name not in self.implementations:
            self.implementations[name] = {}
        self.implementations[name][os_type] = implementation

    def execute(self, name: str, *args, **kwargs) -> Any:
        """Execute OS-specific implementation."""
        os_type = self.detector.get_os()
        impls = self.implementations.get(name, {})
        impl = impls.get(os_type, impls.get(OSType.LINUX))

        if not impl:
            raise RuntimeError(f"No implementation for {name} on {os_type.value}")

        return impl(*args, **kwargs)

    async def execute_async(self, name: str, *args, **kwargs) -> Any:
        """Execute async OS-specific implementation."""
        os_type = self.detector.get_os()
        impls = self.implementations.get(name, {})
        impl = impls.get(os_type, impls.get(OSType.LINUX))

        if not impl:
            raise RuntimeError(f"No implementation for {name} on {os_type.value}")

        return await impl(*args, **kwargs)

    def get_platform_info(self) -> dict[str, str]:
        """Get platform information."""
        return {
            "os": self.detector.get_os().value,
            "architecture": self.detector.get_architecture().value,
            "python_version": self.detector.get_python_version(),
            "is_64bit": str(self.detector.is_64bit()),
            "platform_string": self.detector.get_platform_string(),
        }
