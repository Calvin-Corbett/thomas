"""OpenClaw compatibility layer for API translation and versioning.

Provides compatibility translation between OpenClaw and Thomas APIs,
version mapping, and legacy protocol support.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class APIVersion(Enum):
    """Supported API versions."""

    V1 = "1.0"
    V2 = "2.0"
    V3 = "3.0"


class OpenClawOperation(Enum):
    """OpenClaw operations for translation."""

    QUERY = "query"
    COMMAND = "command"
    BATCH = "batch"
    STREAM = "stream"


@dataclass
class APIRequest:
    """Unified API request format."""

    version: APIVersion
    operation: str
    parameters: dict[str, Any]
    context: dict[str, Any]
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class APIResponse:
    """Unified API response format."""

    status: str
    data: dict[str, Any]
    error: str | None = None
    metadata: dict[str, Any] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.metadata is None:
            self.metadata = {}


class CompatibilityTranslator(ABC):
    """Base compatibility translator."""

    @abstractmethod
    async def translate_request(self, openclaw_request: dict[str, Any]) -> APIRequest:
        """Translate OpenClaw request to Thomas format."""
        pass

    @abstractmethod
    async def translate_response(self, thomas_response: dict[str, Any]) -> dict[str, Any]:
        """Translate Thomas response to OpenClaw format."""
        pass


class OpenClawV1Translator(CompatibilityTranslator):
    """Translator for OpenClaw v1.0 API."""

    async def translate_request(self, openclaw_request: dict[str, Any]) -> APIRequest:
        """Translate v1 request to unified format."""
        return APIRequest(
            version=APIVersion.V1,
            operation=openclaw_request.get("op", "query"),
            parameters=openclaw_request.get("params", {}),
            context=openclaw_request.get("ctx", {}),
        )

    async def translate_response(self, thomas_response: dict[str, Any]) -> dict[str, Any]:
        """Translate unified response to v1 format."""
        return {
            "status": thomas_response.get("status"),
            "result": thomas_response.get("data"),
            "timestamp": thomas_response.get("timestamp"),
        }


class OpenClawV2Translator(CompatibilityTranslator):
    """Translator for OpenClaw v2.0 API."""

    async def translate_request(self, openclaw_request: dict[str, Any]) -> APIRequest:
        """Translate v2 request to unified format."""
        return APIRequest(
            version=APIVersion.V2,
            operation=openclaw_request.get("operation", "query"),
            parameters=openclaw_request.get("parameters", {}),
            context=openclaw_request.get("context", {}),
        )

    async def translate_response(self, thomas_response: dict[str, Any]) -> dict[str, Any]:
        """Translate unified response to v2 format."""
        return {
            "operation_status": thomas_response.get("status"),
            "data": thomas_response.get("data"),
            "metadata": thomas_response.get("metadata", {}),
        }


class VersionMappingRegistry:
    """Registry of API version mappings."""

    def __init__(self):
        self.translators: dict[APIVersion, CompatibilityTranslator] = {}
        self.operation_mappings: dict[str, str] = {}
        self.parameter_mappings: dict[str, dict[str, str]] = {}

    def register_translator(self, version: APIVersion, translator: CompatibilityTranslator) -> None:
        """Register version translator."""
        self.translators[version] = translator

    def register_operation_mapping(self, openclaw_op: str, thomas_op: str) -> None:
        """Register operation name mapping."""
        self.operation_mappings[openclaw_op] = thomas_op

    def register_parameter_mapping(self, version: str, openclaw_param: str, thomas_param: str) -> None:
        """Register parameter name mapping."""
        if version not in self.parameter_mappings:
            self.parameter_mappings[version] = {}
        self.parameter_mappings[version][openclaw_param] = thomas_param

    def get_translator(self, version: APIVersion) -> CompatibilityTranslator | None:
        """Get translator for version."""
        return self.translators.get(version)

    def map_operation(self, openclaw_op: str) -> str:
        """Map OpenClaw operation to Thomas operation."""
        return self.operation_mappings.get(openclaw_op, openclaw_op)

    def map_parameters(self, version: str, openclaw_params: dict[str, Any]) -> dict[str, Any]:
        """Map OpenClaw parameters to Thomas parameters."""
        mappings = self.parameter_mappings.get(version, {})
        return {mappings.get(k, k): v for k, v in openclaw_params.items()}


class CompatibilityLayer:
    """Main compatibility layer for OpenClaw/Thomas translation."""

    def __init__(self):
        self.registry = VersionMappingRegistry()
        self._setup_default_mappings()

    def _setup_default_mappings(self) -> None:
        """Setup default version mappings."""
        self.registry.register_translator(APIVersion.V1, OpenClawV1Translator())
        self.registry.register_translator(APIVersion.V2, OpenClawV2Translator())

        # Default operation mappings
        self.registry.register_operation_mapping("query", "query")
        self.registry.register_operation_mapping("execute", "command")
        self.registry.register_operation_mapping("stream", "stream")

    async def handle_openclaw_request(self, openclaw_request: dict[str, Any]) -> APIResponse:
        """Handle OpenClaw request with automatic version detection."""
        version = self._detect_version(openclaw_request)
        translator = self.registry.get_translator(version)

        if not translator:
            return APIResponse(status="error", data={}, error=f"Unsupported version: {version.value}")

        try:
            api_request = await translator.translate_request(openclaw_request)
            # Process request...
            return APIResponse(status="success", data={"processed": True})
        except Exception as e:
            return APIResponse(status="error", data={}, error=str(e))

    async def handle_thomas_response(
        self, openclaw_version: APIVersion, thomas_response: dict[str, Any]
    ) -> dict[str, Any]:
        """Convert Thomas response to OpenClaw format."""
        translator = self.registry.get_translator(openclaw_version)
        if not translator:
            return thomas_response

        return await translator.translate_response(thomas_response)

    def _detect_version(self, request: dict[str, Any]) -> APIVersion:
        """Auto-detect API version from request structure."""
        if "api_version" in request:
            version_str = request["api_version"]
            for v in APIVersion:
                if v.value == version_str:
                    return v

        # Default detection heuristics
        if "operation" in request:
            return APIVersion.V2
        elif "op" in request:
            return APIVersion.V1
        else:
            return APIVersion.V3

    def register_custom_mapping(
        self, openclaw_operation: str, thomas_operation: str, parameter_mappings: dict[str, str] | None = None
    ) -> None:
        """Register custom operation and parameter mappings."""
        self.registry.register_operation_mapping(openclaw_operation, thomas_operation)
        if parameter_mappings:
            for oclaw_param, thomas_param in parameter_mappings.items():
                self.registry.register_parameter_mapping("custom", oclaw_param, thomas_param)
