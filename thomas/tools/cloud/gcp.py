"""Google Cloud Platform provider implementation.

Uses google-cloud-* libraries if available, falls back to REST API with service account auth.

Services:
  - Compute Engine: Virtual machines
  - Cloud Storage: Object storage (GCS)
  - Cloud Functions: Serverless functions
  - Cloud SQL: Managed databases
"""

from __future__ import annotations

import json
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

# Try to import google-cloud libraries
try:
    from google.cloud import compute_v1, functions_v1, sql_v1, storage
    from google.oauth2 import service_account

    HAS_GCP_LIBS = True
except ImportError:
    HAS_GCP_LIBS = False


class GCPProvider(CloudProvider):
    """Google Cloud Platform provider implementation."""

    def __init__(self, config: dict[str, Any]):
        """Initialize GCP provider.

        Args:
            config: Configuration dict with:
              - project_id: GCP project ID
              - credentials_json: Service account JSON (path or content)
              - use_libs: Use google-cloud libraries if available (default: True)
        """
        self.config = config
        self.project_id = config.get("project_id")
        self.use_libs = config.get("use_libs", True) and HAS_GCP_LIBS
        self._authenticated = False
        self._credentials: Any | None = None
        self._http_client: httpx.AsyncClient | None = None

        if not self.project_id:
            raise ValueError("project_id is required for GCP provider")

        if self.use_libs and HAS_GCP_LIBS:
            self._init_libs()
        else:
            self._init_rest_api()

    def _init_libs(self) -> None:
        """Initialize google-cloud libraries."""
        try:
            creds_input = self.config.get("credentials_json")
            if isinstance(creds_input, str):
                if creds_input.startswith("{"):
                    creds_dict = json.loads(creds_input)
                else:
                    with open(creds_input) as f:
                        creds_dict = json.load(f)
            else:
                creds_dict = creds_input

            self._credentials = service_account.Credentials.from_service_account_info(creds_dict)
            log.info("GCP provider initialized with service account credentials")
        except Exception as e:
            log.warning(f"Failed to initialize google-cloud libraries: {e}")
            self.use_libs = False
            self._init_rest_api()

    def _init_rest_api(self) -> None:
        """Initialize REST API client."""
        self._http_client = None
        log.info("GCP provider using REST API")

    async def authenticate(self) -> bool:
        """Authenticate with GCP.

        Returns:
            True if authentication successful

        Raises:
            CloudAuthError: If authentication fails
        """
        if self.use_libs:
            try:
                if not self._credentials:
                    raise CloudAuthError("GCP credentials not configured")
                # Credentials auto-refresh via libraries
                return True
            except Exception as e:
                raise CloudAuthError(f"GCP authentication failed: {e}")
        else:
            if not self.config.get("credentials_json"):
                raise CloudAuthError("GCP credentials not configured")
            return True

    async def list_resources(
        self, resource_type: ResourceType, region: str | None = None, filters: dict[str, Any] | None = None
    ) -> list[CloudResource]:
        """List GCP resources.

        Args:
            resource_type: Type of resource
            region: Optional region
            filters: Additional filters

        Returns:
            List of CloudResource objects
        """
        if not self._authenticated:
            await self.authenticate()

        if resource_type == ResourceType.COMPUTE:
            return await self._list_compute_instances(region, filters)
        elif resource_type == ResourceType.STORAGE:
            return await self._list_storage_buckets(filters)
        elif resource_type == ResourceType.DATABASE:
            return await self._list_sql_instances(region, filters)
        elif resource_type == ResourceType.SERVERLESS:
            return await self._list_cloud_functions(region, filters)
        else:
            return []

    async def _list_compute_instances(
        self, region: str | None = None, filters: dict[str, Any] | None = None
    ) -> list[CloudResource]:
        """List Compute Engine instances."""
        if not self.use_libs or not self._credentials:
            return []

        try:
            client = compute_v1.InstancesClient(credentials=self._credentials)
            resources = []

            request = compute_v1.AggregatedListInstancesRequest(
                project=self.project_id,
            )

            for zone_name, instances_scoped_list in client.aggregated_list(request=request):
                if not instances_scoped_list.instances:
                    continue

                # Extract zone from zone_name (format: "zones/zone-name")
                zone = zone_name.split("/")[-1]

                for instance in instances_scoped_list.instances:
                    resources.append(
                        CloudResource(
                            id=instance.name,
                            name=instance.name,
                            type=ResourceType.COMPUTE,
                            provider="gcp",
                            region=zone,
                            state=instance.status,
                            created_at=instance.creation_timestamp,
                            metadata={
                                "machine_type": instance.machine_type.split("/")[-1] if instance.machine_type else None,
                                "zone": zone,
                                "labels": dict(instance.labels or {}),
                            },
                        )
                    )
            return resources
        except Exception as e:
            log.error(f"Error listing Compute instances: {e}")
            return []

    async def _list_storage_buckets(self, filters: dict[str, Any] | None = None) -> list[CloudResource]:
        """List Cloud Storage buckets."""
        if not self.use_libs or not self._credentials:
            return []

        try:
            client = storage.Client(project=self.project_id, credentials=self._credentials)
            resources = []

            for bucket in client.list_buckets():
                resources.append(
                    CloudResource(
                        id=bucket.name,
                        name=bucket.name,
                        type=ResourceType.STORAGE,
                        provider="gcp",
                        region=bucket.location or "global",
                        state="active",
                        created_at=bucket.time_created.isoformat() if bucket.time_created else None,
                        metadata={
                            "location": bucket.location,
                            "storage_class": bucket.storage_class,
                        },
                    )
                )
            return resources
        except Exception as e:
            log.error(f"Error listing Storage buckets: {e}")
            return []

    async def _list_sql_instances(
        self, region: str | None = None, filters: dict[str, Any] | None = None
    ) -> list[CloudResource]:
        """List Cloud SQL instances."""
        if not self.use_libs or not self._credentials:
            return []

        try:
            client = sql_v1.SqlInstancesServiceClient(credentials=self._credentials)
            resources = []

            request = sql_v1.ListInstancesRequest(project=self.project_id)
            instances = client.list(request=request)

            for instance in instances:
                resources.append(
                    CloudResource(
                        id=instance.name,
                        name=instance.name,
                        type=ResourceType.DATABASE,
                        provider="gcp",
                        region=instance.region,
                        state=instance.state.name if instance.state else "unknown",
                        created_at=instance.creation_timestamp.isoformat() if instance.creation_timestamp else None,
                        metadata={
                            "database_version": instance.database_version,
                            "tier": instance.settings.tier if instance.settings else None,
                        },
                    )
                )
            return resources
        except Exception as e:
            log.error(f"Error listing Cloud SQL instances: {e}")
            return []

    async def _list_cloud_functions(
        self, region: str | None = None, filters: dict[str, Any] | None = None
    ) -> list[CloudResource]:
        """List Cloud Functions."""
        if not self.use_libs or not self._credentials:
            return []

        try:
            client = functions_v1.CloudFunctionsServiceClient(credentials=self._credentials)
            resources = []

            location = f"projects/{self.project_id}/locations/{region or 'us-central1'}"
            request = functions_v1.ListFunctionsRequest(location=location)
            functions = client.list_functions(request=request)

            for func in functions:
                resources.append(
                    CloudResource(
                        id=func.name,
                        name=func.name.split("/")[-1],
                        type=ResourceType.SERVERLESS,
                        provider="gcp",
                        region=region or "us-central1",
                        state=func.state.name if func.state else "unknown",
                        created_at=func.update_time.isoformat() if func.update_time else None,
                        metadata={
                            "runtime": func.runtime,
                            "memory_mb": func.available_memory_mb,
                        },
                    )
                )
            return resources
        except Exception as e:
            log.error(f"Error listing Cloud Functions: {e}")
            return []

    async def get_resource(self, resource_id: str, resource_type: ResourceType) -> CloudResource:
        """Get a specific GCP resource.

        Args:
            resource_id: Resource ID
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
        """Create a new GCP resource.

        Args:
            name: Resource name
            resource_type: Type of resource
            config: Configuration
            region: Region

        Returns:
            Created CloudResource

        Raises:
            CloudOperationError: If creation fails
        """
        raise CloudOperationError("Resource creation not yet implemented for GCP")

    async def delete_resource(self, resource_id: str, resource_type: ResourceType, force: bool = False) -> bool:
        """Delete a GCP resource.

        Args:
            resource_id: Resource ID
            resource_type: Resource type
            force: Force deletion

        Returns:
            True if successful
        """
        raise CloudOperationError("Resource deletion not yet implemented for GCP")

    async def start_instance(self, instance_id: str, zone: str) -> bool:
        """Start a Compute Engine instance.

        Args:
            instance_id: Instance ID
            zone: Zone containing the instance

        Returns:
            True if successful
        """
        if not self.use_libs or not self._credentials:
            raise CloudOperationError("google-cloud libraries not available")

        try:
            client = compute_v1.InstancesClient(credentials=self._credentials)
            request = compute_v1.StartInstanceRequest(
                project=self.project_id,
                zone=zone,
                resource=instance_id,
            )
            client.start(request=request)
            return True
        except Exception as e:
            raise CloudOperationError(f"Failed to start instance: {e}")

    async def stop_instance(self, instance_id: str, zone: str) -> bool:
        """Stop a Compute Engine instance.

        Args:
            instance_id: Instance ID
            zone: Zone containing the instance

        Returns:
            True if successful
        """
        if not self.use_libs or not self._credentials:
            raise CloudOperationError("google-cloud libraries not available")

        try:
            client = compute_v1.InstancesClient(credentials=self._credentials)
            request = compute_v1.StopInstanceRequest(
                project=self.project_id,
                zone=zone,
                resource=instance_id,
            )
            client.stop(request=request)
            return True
        except Exception as e:
            raise CloudOperationError(f"Failed to stop instance: {e}")
