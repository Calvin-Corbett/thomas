"""Tools for codex module - ChatGPT-powered code completion and execution."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

from .bridge import CodexBridge

log = logging.getLogger(__name__)


class CodexCheckAuthTool(Tool):
    """Check Codex authentication status."""

    name = "codex_check_auth"
    category = "codex"
    description = "Check current authentication status with Codex (ChatGPT)."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, bridge: CodexBridge | None = None):
        self.bridge = bridge

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            if self.bridge is None:
                self.bridge = CodexBridge(cwd=None)
                await self.bridge.start()

            account = await self.bridge.check_auth()
            return ToolResult(
                ok=True,
                data={
                    "logged_in": account.logged_in,
                    "auth_type": account.auth_type,
                    "email": account.email,
                    "display_name": account.display_name,
                    "plan_type": account.plan_type,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CodexLoginTool(Tool):
    """Initiate ChatGPT OAuth login flow."""

    name = "codex_login"
    category = "codex"
    description = "Start ChatGPT OAuth login (opens browser). Use after checking auth status."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, bridge: CodexBridge | None = None):
        self.bridge = bridge

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            if self.bridge is None:
                self.bridge = CodexBridge(cwd=None)
                await self.bridge.start()

            account = await self.bridge.login_chatgpt()
            return ToolResult(
                ok=True,
                data={
                    "logged_in": account.logged_in,
                    "email": account.email,
                    "display_name": account.display_name,
                    "plan_type": account.plan_type,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CodexListModelsTool(Tool):
    """List available Codex models."""

    name = "codex_list_models"
    category = "codex"
    description = "List available LLM models accessible through Codex."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, bridge: CodexBridge | None = None):
        self.bridge = bridge

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            if self.bridge is None:
                self.bridge = CodexBridge(cwd=None)
                await self.bridge.start()

            models = await self.bridge.list_models()
            return ToolResult(
                ok=True,
                data={
                    "models": [
                        {
                            "id": m.id,
                            "display_name": m.display_name,
                            "is_default": m.is_default,
                        }
                        for m in models
                    ]
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CodexLogoutTool(Tool):
    """Log out of Codex."""

    name = "codex_logout"
    category = "codex"
    description = "Log out of the current Codex account."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, bridge: CodexBridge | None = None):
        self.bridge = bridge

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            if self.bridge is None:
                self.bridge = CodexBridge(cwd=None)
                await self.bridge.start()

            await self.bridge.logout()
            return ToolResult(ok=True, data={"logged_out": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_codex_tools(registry):
    """Register codex tools with the tool registry."""
    tools = [
        CodexCheckAuthTool(),
        CodexLoginTool(),
        CodexListModelsTool(),
        CodexLogoutTool(),
    ]
    for tool in tools:
        registry.register(tool)
