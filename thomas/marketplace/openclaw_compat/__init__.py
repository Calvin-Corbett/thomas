"""OpenClaw compatibility layer for API translation.

Provides backward compatibility with OpenClaw v1/v2 APIs,
version mapping, and protocol translation.
"""

from .core import (
    APIRequest,
    APIResponse,
    APIVersion,
    CompatibilityLayer,
    CompatibilityTranslator,
    OpenClawOperation,
    OpenClawV1Translator,
    OpenClawV2Translator,
    VersionMappingRegistry,
)

__all__ = [
    "APIVersion",
    "OpenClawOperation",
    "APIRequest",
    "APIResponse",
    "CompatibilityTranslator",
    "OpenClawV1Translator",
    "OpenClawV2Translator",
    "VersionMappingRegistry",
    "CompatibilityLayer",
]

__version__ = "1.0.0"
