"""Backward-compatible re-export. Module moved to thomas.marketplace.asset_studio."""

from thomas.marketplace.asset_studio import (
    ActionDefinition,
    AssetStudioRuntime,
    ConnectorCatalog,
    ConnectorDefinition,
    default_connector_catalog,
)

__all__ = [
    "ActionDefinition",
    "AssetStudioRuntime",
    "ConnectorCatalog",
    "ConnectorDefinition",
    "default_connector_catalog",
]
