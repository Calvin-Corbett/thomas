"""Tools for upgrade module - blue/green deployment and rollback."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult

from .doppelganger import (
    create_backup,
    ensure_green_venv,
    get_paths,
    latest_backup,
    promote_green_to_blue,
    rollback,
    run_green_tests,
    sync_blue_to_green,
    sync_green_to_blue,
)

log = logging.getLogger(__name__)


class UpgradeGetPathsTool(Tool):
    """Get Doppelganger paths for blue/green deployment."""

    name = "upgrade_get_paths"
    category = "upgrade"
    description = "Get the blue/green deployment folder structure paths."
    parameters = {
        "type": "object",
        "properties": {
            "project_root": {
                "type": "string",
                "description": "Project root directory (optional, auto-detected if not provided)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            project_root = args.get("project_root")
            if project_root:
                project_root = Path(project_root)

            paths = get_paths(project_root)
            return ToolResult(
                ok=True,
                data={
                    "blue_root": str(paths.blue_root),
                    "dg_root": str(paths.dg_root),
                    "green_root": str(paths.green_root),
                    "green_runtime": str(paths.green_runtime),
                    "green_venv": str(paths.green_venv),
                    "backups_root": str(paths.backups_root),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class UpgradeSyncBlueToGreenTool(Tool):
    """Sync code from blue (production) to green (staging)."""

    name = "upgrade_sync_blue_to_green"
    category = "upgrade"
    description = "Copy code from blue (active) to green (staging) instance."
    parameters = {
        "type": "object",
        "properties": {
            "project_root": {
                "type": "string",
                "description": "Project root directory (optional)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            project_root = args.get("project_root")
            if project_root:
                project_root = Path(project_root)

            paths = get_paths(project_root)
            sync_blue_to_green(paths)
            return ToolResult(ok=True, data={"synced": True, "green_root": str(paths.green_root)})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class UpgradeSyncGreenToBlueTool(Tool):
    """Sync code from green (staging) to blue (production)."""

    name = "upgrade_sync_green_to_blue"
    category = "upgrade"
    description = "Promote changes from green (staging) to blue (active) instance."
    parameters = {
        "type": "object",
        "properties": {
            "project_root": {
                "type": "string",
                "description": "Project root directory (optional)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            project_root = args.get("project_root")
            if project_root:
                project_root = Path(project_root)

            paths = get_paths(project_root)
            sync_green_to_blue(paths)
            return ToolResult(ok=True, data={"promoted": True, "blue_root": str(paths.blue_root)})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class UpgradeCreateBackupTool(Tool):
    """Create a backup of blue (production) before deployment."""

    name = "upgrade_create_backup"
    category = "upgrade"
    description = "Create a timestamped backup of the blue instance before promotion."
    parameters = {
        "type": "object",
        "properties": {
            "project_root": {
                "type": "string",
                "description": "Project root directory (optional)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            project_root = args.get("project_root")
            if project_root:
                project_root = Path(project_root)

            paths = get_paths(project_root)
            backup_path = create_backup(paths)
            return ToolResult(ok=True, data={"backup_path": str(backup_path)})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class UpgradeLatestBackupTool(Tool):
    """Get the latest backup directory."""

    name = "upgrade_latest_backup"
    category = "upgrade"
    description = "Retrieve the path to the most recent backup."
    parameters = {
        "type": "object",
        "properties": {
            "project_root": {
                "type": "string",
                "description": "Project root directory (optional)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            project_root = args.get("project_root")
            if project_root:
                project_root = Path(project_root)

            paths = get_paths(project_root)
            backup = latest_backup(paths)
            if backup is None:
                return ToolResult(ok=False, error="No backups found")

            return ToolResult(ok=True, data={"backup_path": str(backup)})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class UpgradeRollbackTool(Tool):
    """Rollback blue to a previous backup."""

    name = "upgrade_rollback"
    category = "upgrade"
    description = "Restore blue from a backup (latest by default)."
    parameters = {
        "type": "object",
        "properties": {
            "project_root": {
                "type": "string",
                "description": "Project root directory (optional)",
            },
            "backup_dir": {
                "type": "string",
                "description": "Specific backup directory to restore from (optional, uses latest if not provided)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            project_root = args.get("project_root")
            backup_dir = args.get("backup_dir")

            if project_root:
                project_root = Path(project_root)

            paths = get_paths(project_root)
            backup_path = None
            if backup_dir:
                backup_path = Path(backup_dir)

            restored_from = rollback(paths, backup_path)
            return ToolResult(ok=True, data={"restored_from": str(restored_from)})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class UpgradeEnsureGreenVenvTool(Tool):
    """Ensure green venv exists with dependencies."""

    name = "upgrade_ensure_green_venv"
    category = "upgrade"
    description = "Create/verify the green staging environment and install dependencies."
    parameters = {
        "type": "object",
        "properties": {
            "project_root": {
                "type": "string",
                "description": "Project root directory (optional)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            project_root = args.get("project_root")
            if project_root:
                project_root = Path(project_root)

            paths = get_paths(project_root)
            py = ensure_green_venv(paths)
            return ToolResult(ok=True, data={"python_path": str(py)})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class UpgradeRunGreenTestsTool(Tool):
    """Run tests in green environment."""

    name = "upgrade_run_green_tests"
    category = "upgrade"
    description = "Run pytest in the green staging environment to validate changes."
    parameters = {
        "type": "object",
        "properties": {
            "project_root": {
                "type": "string",
                "description": "Project root directory (optional)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            project_root = args.get("project_root")
            if project_root:
                project_root = Path(project_root)

            paths = get_paths(project_root)
            run_green_tests(paths)
            return ToolResult(ok=True, data={"tests_passed": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class UpgradePromoteGreenToBlutool(Tool):
    """Promote green to blue with automatic backup."""

    name = "upgrade_promote_green_to_blue"
    category = "upgrade"
    description = "Promote green to blue, automatically creating a backup first."
    parameters = {
        "type": "object",
        "properties": {
            "project_root": {
                "type": "string",
                "description": "Project root directory (optional)",
            },
            "stop_port": {
                "type": "integer",
                "description": "Port to stop Thomas server on before promotion (default: 8899)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            project_root = args.get("project_root")
            stop_port = args.get("stop_port", 8899)

            if project_root:
                project_root = Path(project_root)

            paths = get_paths(project_root)
            backup = promote_green_to_blue(paths, stop_port=stop_port)
            return ToolResult(ok=True, data={"backup_path": str(backup), "promoted": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_anvil_tools(registry):
    """Register Anvil (self-mod / blue-green / evolve) tools with the registry."""
    tools = [
        UpgradeGetPathsTool(),
        UpgradeSyncBlueToGreenTool(),
        UpgradeSyncGreenToBlueTool(),
        UpgradeCreateBackupTool(),
        UpgradeLatestBackupTool(),
        UpgradeRollbackTool(),
        UpgradeEnsureGreenVenvTool(),
        UpgradeRunGreenTestsTool(),
        UpgradePromoteGreenToBlutool(),
    ]
    for tool in tools:
        registry.register(tool)
