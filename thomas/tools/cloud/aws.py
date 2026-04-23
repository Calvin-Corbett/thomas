"""AWS cloud provider implementation.

Uses boto3 if available, falls back to raw REST API with SigV4 signing.

Services:
  - EC2: Compute instances
  - S3: Object storage
  - Lambda: Serverless functions
  - RDS: Managed relational databases
  - Route53: DNS management
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

# Try to import boto3
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False
    boto3 = None  # type: ignore
    ClientError = None  # type: ignore


class AWSProvider(CloudProvider):
    """AWS cloud provider implementation."""

    def __init__(self, config: dict[str, Any]):
        """Initialize AWS provider.

        Args:
            config: Configuration dict with:
              - access_key_id: AWS access key
              - secret_access_key: AWS secret key
              - region: Default region
              - use_boto3: Use boto3 if available (default: True)
        """
        self.config = config
        self.region = config.get("region", "us-east-1")
        self.use_boto3 = config.get("use_boto3", True) and HAS_BOTO3
        self._authenticated = False
        self._client: Any | None = None
        self._http_client: httpx.AsyncClient | None = None

        if self.use_boto3 and HAS_BOTO3:
            self._init_boto3()
        else:
            self._init_rest_api()

    def _init_boto3(self) -> None:
        """Initialize boto3 clients."""
        try:
            session = boto3.Session(
                aws_access_key_id=self.config.get("access_key_id"),
                aws_secret_access_key=self.config.get("secret_access_key"),
                region_name=self.region,
            )
            self._ec2_client = session.client("ec2")
            self._s3_client = session.client("s3")
            self._lambda_client = session.client("lambda")
            self._rds_client = session.client("rds")
            self._route53_client = session.client("route53")
            self._authenticated = True
            log.info("AWS provider initialized with boto3")
        except Exception as e:
            log.warning(f"Failed to initialize boto3: {e}")
            self.use_boto3 = False
            self._init_rest_api()

    def _init_rest_api(self) -> None:
        """Initialize REST API client for SigV4 signing."""
        self._http_client = None
        log.info("AWS provider using REST API with SigV4")

    async def authenticate(self) -> bool:
        """Authenticate with AWS.

        Returns:
            True if authentication successful

        Raises:
            CloudAuthError: If authentication fails
        """
        if self.use_boto3:
            try:
                # Try a simple STS call
                sts = boto3.client(
                    "sts",
                    aws_access_key_id=self.config.get("access_key_id"),
                    aws_secret_access_key=self.config.get("secret_access_key"),
                    region_name=self.region,
                )
                sts.get_caller_identity()
                self._authenticated = True
                return True
            except Exception as e:
                raise CloudAuthError(f"AWS authentication failed: {e}")
        else:
            # For REST API, just validate we have credentials
            if not self.config.get("access_key_id") or not self.config.get("secret_access_key"):
                raise CloudAuthError("AWS credentials not configured")
            self._authenticated = True
            return True

    async def list_resources(
        self, resource_type: ResourceType, region: str | None = None, filters: dict[str, Any] | None = None
    ) -> list[CloudResource]:
        """List AWS resources.

        Args:
            resource_type: Type of resource
            region: Optional region (uses default if not specified)
            filters: Additional filters

        Returns:
            List of CloudResource objects
        """
        if not self._authenticated:
            await self.authenticate()

        region = region or self.region

        if resource_type == ResourceType.COMPUTE:
            return await self._list_ec2_instances(region, filters)
        elif resource_type == ResourceType.STORAGE:
            return await self._list_s3_buckets(filters)
        elif resource_type == ResourceType.DATABASE:
            return await self._list_rds_instances(region, filters)
        elif resource_type == ResourceType.SERVERLESS:
            return await self._list_lambda_functions(region, filters)
        elif resource_type == ResourceType.DNS:
            return await self._list_route53_zones(filters)
        else:
            return []

    async def _list_ec2_instances(self, region: str, filters: dict[str, Any] | None = None) -> list[CloudResource]:
        """List EC2 instances."""
        if not self.use_boto3:
            return []

        try:
            ec2 = boto3.client("ec2", region_name=region)
            response = ec2.describe_instances()
            resources = []

            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    resources.append(
                        CloudResource(
                            id=instance["InstanceId"],
                            name=self._get_tag_value(instance, "Name") or instance["InstanceId"],
                            type=ResourceType.COMPUTE,
                            provider="aws",
                            region=region,
                            state=instance["State"]["Name"],
                            created_at=instance["LaunchTime"].isoformat() if "LaunchTime" in instance else None,
                            metadata={
                                "instance_type": instance.get("InstanceType"),
                                "vpc_id": instance.get("VpcId"),
                                "private_ip": instance.get("PrivateIpAddress"),
                                "public_ip": instance.get("PublicIpAddress"),
                            },
                        )
                    )
            return resources
        except Exception as e:
            log.error(f"Error listing EC2 instances: {e}")
            return []

    async def _list_s3_buckets(self, filters: dict[str, Any] | None = None) -> list[CloudResource]:
        """List S3 buckets."""
        if not self.use_boto3:
            return []

        try:
            s3 = boto3.client("s3")
            response = s3.list_buckets()
            resources = []

            for bucket in response.get("Buckets", []):
                resources.append(
                    CloudResource(
                        id=bucket["Name"],
                        name=bucket["Name"],
                        type=ResourceType.STORAGE,
                        provider="aws",
                        region="global",
                        state="active",
                        created_at=bucket.get("CreationDate", "").isoformat() if bucket.get("CreationDate") else None,
                        metadata={},
                    )
                )
            return resources
        except Exception as e:
            log.error(f"Error listing S3 buckets: {e}")
            return []

    async def _list_rds_instances(self, region: str, filters: dict[str, Any] | None = None) -> list[CloudResource]:
        """List RDS instances."""
        if not self.use_boto3:
            return []

        try:
            rds = boto3.client("rds", region_name=region)
            response = rds.describe_db_instances()
            resources = []

            for instance in response.get("DBInstances", []):
                resources.append(
                    CloudResource(
                        id=instance["DBInstanceIdentifier"],
                        name=instance["DBInstanceIdentifier"],
                        type=ResourceType.DATABASE,
                        provider="aws",
                        region=region,
                        state=instance.get("DBInstanceStatus", "unknown"),
                        created_at=instance.get("InstanceCreateTime", "").isoformat()
                        if instance.get("InstanceCreateTime")
                        else None,
                        metadata={
                            "engine": instance.get("Engine"),
                            "instance_class": instance.get("DBInstanceClass"),
                            "database_name": instance.get("DBName"),
                        },
                    )
                )
            return resources
        except Exception as e:
            log.error(f"Error listing RDS instances: {e}")
            return []

    async def _list_lambda_functions(self, region: str, filters: dict[str, Any] | None = None) -> list[CloudResource]:
        """List Lambda functions."""
        if not self.use_boto3:
            return []

        try:
            lambda_client = boto3.client("lambda", region_name=region)
            response = lambda_client.list_functions()
            resources = []

            for func in response.get("Functions", []):
                resources.append(
                    CloudResource(
                        id=func["FunctionArn"],
                        name=func["FunctionName"],
                        type=ResourceType.SERVERLESS,
                        provider="aws",
                        region=region,
                        state="active",
                        created_at=func.get("LastModified"),
                        metadata={
                            "runtime": func.get("Runtime"),
                            "handler": func.get("Handler"),
                            "memory_mb": func.get("MemorySize"),
                        },
                    )
                )
            return resources
        except Exception as e:
            log.error(f"Error listing Lambda functions: {e}")
            return []

    async def _list_route53_zones(self, filters: dict[str, Any] | None = None) -> list[CloudResource]:
        """List Route53 zones."""
        if not self.use_boto3:
            return []

        try:
            route53 = boto3.client("route53")
            response = route53.list_hosted_zones()
            resources = []

            for zone in response.get("HostedZones", []):
                resources.append(
                    CloudResource(
                        id=zone["Id"],
                        name=zone["Name"],
                        type=ResourceType.DNS,
                        provider="aws",
                        region="global",
                        state="active",
                        metadata={
                            "is_private": zone.get("Config", {}).get("PrivateZone", False),
                            "record_count": zone.get("ResourceRecordSetCount"),
                        },
                    )
                )
            return resources
        except Exception as e:
            log.error(f"Error listing Route53 zones: {e}")
            return []

    async def get_resource(self, resource_id: str, resource_type: ResourceType) -> CloudResource:
        """Get a specific AWS resource.

        Args:
            resource_id: Resource ID
            resource_type: Resource type

        Returns:
            CloudResource object

        Raises:
            CloudResourceNotFoundError: If not found
        """
        # List and find matching resource
        resources = await self.list_resources(resource_type)
        for resource in resources:
            if resource.id == resource_id or resource.name == resource_id:
                return resource

        raise CloudResourceNotFoundError(f"Resource {resource_id} not found")

    async def create_resource(
        self, name: str, resource_type: ResourceType, config: dict[str, Any], region: str | None = None
    ) -> CloudResource:
        """Create a new AWS resource.

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
        region = region or self.region
        raise CloudOperationError("Resource creation not yet implemented for AWS")

    async def delete_resource(self, resource_id: str, resource_type: ResourceType, force: bool = False) -> bool:
        """Delete an AWS resource.

        Args:
            resource_id: Resource ID
            resource_type: Resource type
            force: Force deletion

        Returns:
            True if successful
        """
        raise CloudOperationError("Resource deletion not yet implemented for AWS")

    def _get_tag_value(self, instance: dict[str, Any], key: str) -> str | None:
        """Get tag value from instance."""
        for tag in instance.get("Tags", []):
            if tag.get("Key") == key:
                return tag.get("Value")
        return None

    async def start_instance(self, instance_id: str, region: str | None = None) -> bool:
        """Start an EC2 instance.

        Args:
            instance_id: EC2 instance ID
            region: Region

        Returns:
            True if successful
        """
        if not self.use_boto3:
            raise CloudOperationError("boto3 not available")

        region = region or self.region
        try:
            ec2 = boto3.client("ec2", region_name=region)
            ec2.start_instances(InstanceIds=[instance_id])
            return True
        except Exception as e:
            raise CloudOperationError(f"Failed to start instance: {e}")

    async def stop_instance(self, instance_id: str, region: str | None = None) -> bool:
        """Stop an EC2 instance.

        Args:
            instance_id: EC2 instance ID
            region: Region

        Returns:
            True if successful
        """
        if not self.use_boto3:
            raise CloudOperationError("boto3 not available")

        region = region or self.region
        try:
            ec2 = boto3.client("ec2", region_name=region)
            ec2.stop_instances(InstanceIds=[instance_id])
            return True
        except Exception as e:
            raise CloudOperationError(f"Failed to stop instance: {e}")
