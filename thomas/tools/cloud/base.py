"""Cloud provider abstraction and unified SDK.

Provides abstract base classes and unified interface for cloud operations
across AWS, GCP, and Azure. Supports fallback to REST APIs when SDKs unavailable.

Resource types:
  - compute: Virtual machines/instances
  - storage: Object/blob storage
  - database: Managed databases
  - serverless: Functions/Lambda
  - dns: DNS management
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class CloudException(Exception):
    """Base exception for cloud operations."""

    pass


class CloudAuthError(CloudException):
    """Authentication/authorization error."""

    pass


class CloudResourceNotFoundError(CloudException):
    """Resource not found."""

    pass


class CloudQuotaError(CloudException):
    """Quota/limit exceeded."""

    pass


class CloudOperationError(CloudException):
    """Operation failed."""

    pass


class ResourceType(Enum):
    """Cloud resource types."""

    COMPUTE = "compute"
    STORAGE = "storage"
    DATABASE = "database"
    SERVERLESS = "serverless"
    DNS = "dns"


@dataclass
class CloudResource:
    """Normalized cloud resource representation.

    Same shape regardless of provider.
    """

    id: str
    name: str
    type: ResourceType
    provider: str
    region: str
    state: str
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "provider": self.provider,
            "region": self.region,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


@dataclass
class AsyncOperationResult:
    """Result of async cloud operation."""

    operation_id: str
    resource_id: str
    status: str  # "pending", "running", "succeeded", "failed"
    progress_percent: int = 0
    error: str | None = None
    result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "resource_id": self.resource_id,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "error": self.error,
            "result": self.result,
        }


class CloudProvider(ABC):
    """Abstract base class for cloud providers."""

    @abstractmethod
    async def authenticate(self) -> bool:
        """Authenticate with cloud provider.

        Returns:
            True if authentication successful

        Raises:
            CloudAuthError: If authentication fails
        """
        pass

    @abstractmethod
    async def list_resources(
        self, resource_type: ResourceType, region: str | None = None, filters: dict[str, Any] | None = None
    ) -> list[CloudResource]:
        """List resources of a given type.

        Args:
            resource_type: Type of resource to list
            region: Optional region filter
            filters: Optional additional filters

        Returns:
            List of CloudResource objects
        """
        pass

    @abstractmethod
    async def get_resource(self, resource_id: str, resource_type: ResourceType) -> CloudResource:
        """Get details of a specific resource.

        Args:
            resource_id: ID of resource
            resource_type: Type of resource

        Returns:
            CloudResource object

        Raises:
            CloudResourceNotFoundError: If resource not found
        """
        pass

    @abstractmethod
    async def create_resource(
        self, name: str, resource_type: ResourceType, config: dict[str, Any], region: str | None = None
    ) -> CloudResource:
        """Create a new resource.

        Args:
            name: Name for the resource
            resource_type: Type of resource to create
            config: Configuration dict (provider/resource specific)
            region: Region for the resource

        Returns:
            Created CloudResource

        Raises:
            CloudOperationError: If creation fails
            CloudQuotaError: If quota exceeded
        """
        pass

    @abstractmethod
    async def delete_resource(self, resource_id: str, resource_type: ResourceType, force: bool = False) -> bool:
        """Delete a resource.

        Args:
            resource_id: ID of resource to delete
            resource_type: Type of resource
            force: Force deletion if applicable

        Returns:
            True if deletion successful

        Raises:
            CloudResourceNotFoundError: If resource not found
            CloudOperationError: If deletion fails
        """
        pass


class CloudSDK:
    """Unified cloud SDK facade.

    Routes operations to the correct provider based on configuration.
    """

    def __init__(self):
        """Initialize CloudSDK."""
        self._providers: dict[str, CloudProvider] = {}
        self._provider_types: dict[str, type[CloudProvider]] = {}

    def register_provider(self, name: str, provider_class: type[CloudProvider], config: dict[str, Any]) -> None:
        """Register a cloud provider.

        Args:
            name: Provider name (aws, gcp, azure)
            provider_class: Provider class
            config: Provider configuration
        """
        self._provider_types[name] = provider_class
        try:
            provider = provider_class(config)
            self._providers[name] = provider
            log.info(f"Registered cloud provider: {name}")
        except Exception as e:
            log.warning(f"Failed to initialize {name} provider: {e}")

    async def authenticate_provider(self, name: str) -> bool:
        """Authenticate a specific provider.

        Args:
            name: Provider name

        Returns:
            True if authentication successful

        Raises:
            CloudAuthError: If authentication fails
        """
        if name not in self._providers:
            raise CloudAuthError(f"Provider {name} not registered")

        return await self._providers[name].authenticate()

    async def list_resources(
        self,
        provider: str,
        resource_type: ResourceType,
        region: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[CloudResource]:
        """List resources from a provider.

        Args:
            provider: Provider name
            resource_type: Type of resource
            region: Optional region filter
            filters: Optional additional filters

        Returns:
            List of CloudResource objects
        """
        if provider not in self._providers:
            raise CloudOperationError(f"Provider {provider} not available")

        return await self._providers[provider].list_resources(resource_type, region=region, filters=filters)

    async def get_resource(self, provider: str, resource_id: str, resource_type: ResourceType) -> CloudResource:
        """Get a specific resource from a provider.

        Args:
            provider: Provider name
            resource_id: Resource ID
            resource_type: Resource type

        Returns:
            CloudResource object
        """
        if provider not in self._providers:
            raise CloudOperationError(f"Provider {provider} not available")

        return await self._providers[provider].get_resource(resource_id, resource_type)

    async def create_resource(
        self, provider: str, name: str, resource_type: ResourceType, config: dict[str, Any], region: str | None = None
    ) -> CloudResource:
        """Create a resource on a provider.

        Args:
            provider: Provider name
            name: Resource name
            resource_type: Resource type
            config: Configuration
            region: Region

        Returns:
            Created CloudResource
        """
        if provider not in self._providers:
            raise CloudOperationError(f"Provider {provider} not available")

        return await self._providers[provider].create_resource(name, resource_type, config, region=region)

    async def delete_resource(
        self, provider: str, resource_id: str, resource_type: ResourceType, force: bool = False
    ) -> bool:
        """Delete a resource from a provider.

        Args:
            provider: Provider name
            resource_id: Resource ID
            resource_type: Resource type
            force: Force deletion if applicable

        Returns:
            True if successful
        """
        if provider not in self._providers:
            raise CloudOperationError(f"Provider {provider} not available")

        return await self._providers[provider].delete_resource(resource_id, resource_type, force=force)

    def get_available_providers(self) -> list[str]:
        """Get list of registered providers.

        Returns:
            List of provider names
        """
        return list(self._providers.keys())
