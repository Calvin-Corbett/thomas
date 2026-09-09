"""Infrastructure configuration management platform."""

__version__ = "0.1.0"

from thomas.config_mgmt._exceptions import (
    ConfigError,
    ExecutionError,
    InventoryError,
    ModuleError,
    PlaybookError,
    ValidationError,
)
from thomas.config_mgmt._types import (
    Connection,
    Credential,
    DiffResult,
    ExecutionResult,
    Fact,
    Handler,
    Host,
    HostGroup,
    Inventory,
    Module,
    Playbook,
    Role,
    State,
    Task,
    Template,
    Variable,
)
from thomas.config_mgmt.inventory import InventoryManager
from thomas.config_mgmt.modules import ModuleRegistry
from thomas.config_mgmt.playbook import PlaybookEngine

__all__ = [
    "Connection",
    "Credential",
    "DiffResult",
    "ExecutionResult",
    "Fact",
    "Handler",
    "Host",
    "HostGroup",
    "Inventory",
    "Module",
    "Playbook",
    "Role",
    "State",
    "Task",
    "Template",
    "Variable",
    "ConfigError",
    "ExecutionError",
    "ValidationError",
    "InventoryError",
    "PlaybookError",
    "ModuleError",
    "InventoryManager",
    "PlaybookEngine",
    "ModuleRegistry",
]
