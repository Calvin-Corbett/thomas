"""Multi-cloud management for AWS, Azure, GCP, and Alibaba.

Provides cloud provider abstraction, multi-region resource
provisioning, cost optimization, and failover management.
"""

from .core import (
    AWSConnector,
    CloudConnector,
    CloudProvider,
    CloudRegion,
    CostMetrics,
    MultiCloudManager,
    ResourceConfig,
    ResourceType,
)

__all__ = [
    "CloudProvider",
    "ResourceType",
    "CloudRegion",
    "ResourceConfig",
    "CostMetrics",
    "CloudConnector",
    "AWSConnector",
    "MultiCloudManager",
]

__version__ = "1.0.0"
