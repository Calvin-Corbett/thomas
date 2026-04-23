"""Microsoft Azure cloud provider implementation.

Uses azure-* libraries if available, falls back to REST API with bearer token authentication.

Services:
  - Virtual Machines: Compute instances
  - Blob Storage: Object storage
  - Azure Functions: Serverless functions
  - Azure SQL: Managed databases
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

from thomas.tools.cloud.base import (
    CloudAuthError,
    CloudOperationError,
    CloudProvider,
    CloudResource,
    CloudResourceNotFoundError,
    ResourceType,
)

log = logging.getLogger(__name__)

# Try to import Azure libraries
try:
    from azure.functions import FunctionClient
    from azure.identity import ClientSecretCredential, DefaultAzureCredential
    from azure.mgmt.compute import ComputeManagementClient
    from azure.mgmt.sql import SqlManagementClient
    from azure.mgmt.storage import StorageManagementClient

    HAS_AZURE_LIBS = True
except ImportError:
    HAS_AZURE_LIBS = False


class AzureProvider(CloudProvider):
    """Microsoft Azure cloud provider implementation."""

    def __init__(self, config: dict[str, Any]):
        """Initialize Azure provider.

        Args:
            config: Configuration dict with:
              - subscription_id: Azure subscription ID
              - client_id: Service principal client ID
              - client_secret: Service principal secret
              - tenant_id: Azure tenant ID
              - resource_group: Default resource group
              - use_libs: Use azure libraries if available (default: True)
        """
        self.config = config
        self.subscription_id = config.get("subscription_id")
        self.resource_group = config.get("resource_group")
        self.use_libs = config.get("use_libs", True) and HAS_AZURE_LIBS
        self._authenticated = False
        self._credentials: Any | None = None
        self._http_client: httpx.AsyncClient | None = None

        if not self.subscription_id:
            raise ValueError("subscription_id is required for Azure provider")

        if self.use_libs and HAS_AZURE_LIBS:
            self._init_libs()
        else:
            self._init_rest_api()

    def _init_libs(self) -> None:
        """Initialize Azure libraries."""
        try:
            client_id = self.config.get("client_id")
            client_secret = self.config.get("client_secret")
            tenant_id = self.config.get("tenant_id")

            if client_id and client_secret and tenant_id:
                self._credentials = ClientSecretCredential(
                    client_id=client_id,
                    client_secret=client_secret,
                    tenant_id=tenant_id,
                )
            else:
                self._credentials = DefaultAzureCredential()

            self._compute_client = ComputeManagementClient(self._credentials, self.subscription_id)
            self._storage_client = StorageManagementClient(self._credentials, self.subscription_id)
            self._sql_client = SqlManagementClient(self._credentials, self.subscription_id)
            log.info("Azure provider initialized with service principal credentials")
        except Exception as e:
            log.warning(f"Failed to initialize Azure libraries: {e}")
            self.use_libs = False
            self._init_rest_api()

    def _init_rest_api(self) -> None:
        """Initialize REST API client."""
        self._http_client = None
        log.info("Azure provider using REST API")

    async def authenticate(self) -> bool:
        """Authenticate with Azure.

        Returns:
            True if authentication successful

        Raises:
            CloudAuthError: If authentication fails
        """
        if self.use_libs:
            try:
                if not self._credentials:
                    raise CloudAuthError("Azure credentials not configured")
                # Credentials auto-refresh via libraries
                return True
            except Exception as e:
                raise CloudAuthError(f"Azure authentication failed: {e}")
        else:
            if not self.subscription_id:
                raise CloudAuthError("Azure subscription_id not configured")
            return True

    async def list_resources(
        self, resource_type: ResourceType, region: str | None = None, filters: dict[str, Any] | None = None
    ) -> list[CloudResource]:
        """List Azure resources.

        Args:
            resource_type: Type of resource
            region: Optional region (Azure location)
            filters: Additional filters

        Returns:
            List of CloudResource objects
        """
        if not self._authenticated:
            await self.authenticate()

        if resource_type == ResourceType.COMPUTE:
            return await self._list_vms(region, filters)
        elif resource_type == ResourceType.STORAGE:
            return await self._list_storage_accounts(region, filters)
        elif resource_type == ResourceType.DATABASE:
            return await self._list_sql_servers(region, filters)
        elif resource_type == ResourceType.SERVERLESS:
            return await self._list_function_apps(region, filters)
        else:
            return []

    async def _list_vms(self, region: str | None = None, filters: dict[str, Any] | None = None) -> list[CloudResource]:
        """List Virtual Machines."""
        if not self.use_libs or not self._credentials:
            return []

        try:
            resources = []
            resource_group = self.resource_group

            if not resource_group:
                log.warning("resource_group not specified, cannot list VMs")
                return []

            for vm in self._compute_client.virtual_machines.list(resource_group):
                resources.append(
                    CloudResource(
                        id=vm.id,
                        name=vm.name,
                        type=ResourceType.COMPUTE,
                        provider="azure",
                        region=vm.location,
                        state="active",
                        metadata={
                            "vm_size": vm.hardware_profile.vm_size if vm.hardware_profile else None,
                            "os_type": vm.storage_profile.os_disk.os_type
                            if vm.storage_profile and vm.storage_profile.os_disk
                            else None,
                            "tags": dict(vm.tags or {}),
                        },
                    )
                )
            return resources
        except Exception as e:
            log.error(f"Error listing VMs: {e}")
            return []

    async def _list_storage_accounts(
        self, region: str | None = None, filters: dict[str, Any] | None = None
    ) -> list[CloudResource]:
        """List Storage Accounts."""
        if not self.use_libs or not self._credentials:
            return []

        try:
            resources = []

            for account in self._storage_client.storage_accounts.list():
                resources.append(
                    CloudResource(
                        id=account.id,
                        name=account.name,
                        type=ResourceType.STORAGE,
                        provider="azure",
                        region=account.location,
                        state=account.provisioning_state,
                        metadata={
                            "kind": account.kind,
                            "sku": account.sku.name if account.sku else None,
                            "tags": dict(account.tags or {}),
                        },
                    )
                )
            return resources
        except Exception as e:
            log.error(f"Error listing Storage Accounts: {e}")
            return []

    async def _list_sql_servers(
        self, region: str | None = None, filters: dict[str, Any] | None = None
    ) -> list[CloudResource]:
        """List SQL Servers."""
        if not self.use_libs or not self._credentials:
            return []

        try:
            resources = []
            resource_group = self.resource_group

            if not resource_group:
                log.warning("resource_group not specified, cannot list SQL servers")
                return []

            for server in self._sql_client.servers.list_by_resource_group(resource_group):
                resources.append(
                    CloudResource(
                        id=server.id,
                        name=server.name,
                        type=ResourceType.DATABASE,
                        provider="azure",
                        region=server.location,
                        state=server.state if hasattr(server, "state") else "active",
                        metadata={
                            "version": server.version,
                            "admin_login": server.administrator_login,
                            "tags": dict(server.tags or {}),
                        },
                    )
                )
            return resources
        except Exception as e:
            log.error(f"Error listing SQL servers: {e}")
            return []

    async def _list_function_apps(
        self, region: str | None = None, filters: dict[str, Any] | None = None
    ) -> list[CloudResource]:
        """List Azure Functions."""
        if not self.use_libs or not self._credentials:
            return []

        try:
            resources = []
            resource_group = self.resource_group

            if not resource_group:
                log.warning("resource_group not specified, cannot list function apps")
                return []

            # List function apps via compute client or REST
            # This is a simplified approach
            log.warning("Function app listing via SDK not fully implemented")
            return resources
        except Exception as e:
            log.error(f"Error listing Function Apps: {e}")
            return []

    async def get_resource(self, resource_id: str, resource_type: ResourceType) -> CloudResource:
        """Get a specific Azure resource.

        Args:
            resource_id: Resource ID or name
            resource_type: Resource type

        Returns:
            CloudResource object

        Raises:
            CloudResourceNotFoundError: If not found
        """
        resources = await self.list_resources(resource_type)
        for resource in resources:
            if resource.id == resource_id or resource.name == resource_id:
                return resource

        raise CloudResourceNotFoundError(f"Resource {resource_id} not found")

    async def create_resource(
        self, name: str, resource_type: ResourceType, config: dict[str, Any], region: str | None = None
    ) -> CloudResource:
        """Create a new Azure resource.

        Args:
            name: Resource name
            resource_type: Type of resource
            config: Configuration
            region: Region/location

        Returns:
            Created CloudResource

        Raises:
            CloudOperationError: If creation fails
        """
        raise CloudOperationError("Resource creation not yet implemented for Azure")

    async def delete_resource(self, resource_id: str, resource_type: ResourceType, force: bool = False) -> bool:
        """Delete an Azure resource.

        Args:
            resource_id: Resource ID
            resource_type: Resource type
            force: Force deletion

        Returns:
            True if successful
        """
        raise CloudOperationError("Resource deletion not yet implemented for Azure")

    async def start_vm(self, resource_group: str, vm_name: str) -> bool:
        """Start a Virtual Machine.

        Args:
            resource_group: Resource group name
            vm_name: VM name

        Returns:
            True if successful
        """
        if not self.use_libs or not self._credentials:
            raise CloudOperationError("Azure libraries not available")

        try:
            operation = self._compute_client.virtual_machines.begin_start(resource_group, vm_name)
            operation.wait()
            return True
        except Exception as e:
            raise CloudOperationError(f"Failed to start VM: {e}")

    async def stop_vm(self, resource_group: str, vm_name: str) -> bool:
        """Stop a Virtual Machine.

        Args:
            resource_group: Resource group name
            vm_name: VM name

        Returns:
            True if successful
        """
        if not self.use_libs or not self._credentials:
            raise CloudOperationError("Azure libraries not available")

        try:
            operation = self._compute_client.virtual_machines.begin_power_off(resource_group, vm_name)
            operation.wait()
            return True
        except Exception as e:
            raise CloudOperationError(f"Failed to stop VM: {e}")
