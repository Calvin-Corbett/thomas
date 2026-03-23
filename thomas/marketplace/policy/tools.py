"""Tools for policy module - security policies and guardrails."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult

from .config import load_policy_config
from .policy import PolicyEngine
from .types import PolicyContext, PolicyDecisionType

log = logging.getLogger(__name__)


class PolicyLoadConfigTool(Tool):
    """Load policy configuration."""

    name = "policy_load_config"
    category = "policy"
    description = "Load policy configuration from runtime directory."
    parameters = {
        "type": "object",
        "properties": {
            "runtime_root": {
                "type": "string",
                "description": "Runtime root directory path",
            },
        },
        "required": ["runtime_root"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            runtime_root = args["runtime_root"]
            config = load_policy_config(runtime_root)

            return ToolResult(
                ok=True,
                data={
                    "guardrails_enabled": config.guardrails.enabled,
                    "approval_timeout_s": config.guardrails.approval_timeout_s,
                    "tools_require_approval": config.guardrails.tools_require_approval,
                    "deny_roots": config.deny_roots,
                    "deny_paths": config.deny_paths,
                    "approval_roots": config.approval_roots,
                    "allow_tools": config.allow_tools,
                    "deny_tools": config.deny_tools,
                    "deny_groups": config.deny_groups,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PolicyEvaluateTool(Tool):
    """Evaluate a tool call against policy."""

    name = "policy_evaluate"
    category = "policy"
    description = "Evaluate whether a tool call is allowed by policy."
    parameters = {
        "type": "object",
        "properties": {
            "runtime_root": {
                "type": "string",
                "description": "Runtime root directory path",
            },
            "tool_name": {
                "type": "string",
                "description": "Name of the tool being called",
            },
            "args": {
                "type": "object",
                "description": "Tool arguments",
            },
            "cwd": {
                "type": "string",
                "description": "Current working directory",
            },
            "sandbox_root": {
                "type": "string",
                "description": "Sandbox root directory",
            },
            "iteration": {
                "type": "integer",
                "description": "Conversation iteration number",
            },
            "conversation_summary": {
                "type": "string",
                "description": "Summary of conversation so far",
            },
            "run_id": {
                "type": "string",
                "description": "Run ID (optional)",
            },
            "session_id": {
                "type": "string",
                "description": "Session ID (optional)",
            },
        },
        "required": [
            "runtime_root",
            "tool_name",
            "args",
            "cwd",
            "sandbox_root",
            "iteration",
            "conversation_summary",
        ],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            runtime_root = args["runtime_root"]
            config = load_policy_config(runtime_root)
            engine = PolicyEngine.from_config(config)

            context = PolicyContext(
                tool_name=args["tool_name"],
                args=args.get("args", {}),
                cwd=args["cwd"],
                sandbox_root=args["sandbox_root"],
                iteration=args["iteration"],
                conversation_summary=args["conversation_summary"],
                run_id=args.get("run_id", ""),
                session_id=args.get("session_id", ""),
                tool_call_id=args.get("tool_call_id", ""),
                runtime_root=runtime_root,
                mode=args.get("mode", ""),
                model_id=args.get("model_id", ""),
                profile=args.get("profile", ""),
            )

            decision = engine.evaluate(context)

            return ToolResult(
                ok=True,
                data={
                    "decision_type": decision.type.value,
                    "allowed": decision.type == PolicyDecisionType.ALLOW,
                    "requires_approval": decision.type == PolicyDecisionType.REQUIRE_APPROVAL,
                    "reason": decision.reason,
                    "meta": decision.meta,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PolicyCreateConfigTool(Tool):
    """Create a policy configuration file."""

    name = "policy_create_config"
    category = "policy"
    description = "Create or update a policy configuration in the runtime directory."
    parameters = {
        "type": "object",
        "properties": {
            "runtime_root": {
                "type": "string",
                "description": "Runtime root directory path",
            },
            "guardrails_enabled": {
                "type": "boolean",
                "description": "Enable guardrails system",
            },
            "approval_timeout_s": {
                "type": "integer",
                "description": "Approval timeout in seconds",
            },
            "tools_require_approval": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tool names requiring approval",
            },
            "deny_roots": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths to deny access to",
            },
            "deny_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names to deny",
            },
            "deny_groups": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool groups to deny (shell, browser, git, etc)",
            },
        },
        "required": ["runtime_root"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            runtime_root = Path(args["runtime_root"])
            cfg_dir = runtime_root / ".thomas"
            cfg_dir.mkdir(parents=True, exist_ok=True)

            config = load_policy_config(str(runtime_root))

            if "guardrails_enabled" in args:
                config.guardrails.enabled = bool(args["guardrails_enabled"])
            if "approval_timeout_s" in args:
                config.guardrails.approval_timeout_s = int(args["approval_timeout_s"])
            if "tools_require_approval" in args:
                config.guardrails.tools_require_approval = list(args["tools_require_approval"])
            if "deny_roots" in args:
                config.deny_roots = list(args["deny_roots"])
            if "deny_tools" in args:
                config.deny_tools = list(args["deny_tools"])
            if "deny_groups" in args:
                config.deny_groups = list(args["deny_groups"])

            import json

            config_dict = {
                "guardrails": {
                    "enabled": config.guardrails.enabled,
                    "approval_timeout_s": config.guardrails.approval_timeout_s,
                    "tools_require_approval": config.guardrails.tools_require_approval,
                },
                "deny_roots": config.deny_roots,
                "deny_paths": config.deny_paths,
                "approval_roots": config.approval_roots,
                "allow_tools": config.allow_tools,
                "deny_tools": config.deny_tools,
                "deny_groups": config.deny_groups,
            }

            json_path = cfg_dir / "policy.json"
            json_path.write_text(json.dumps(config_dict, indent=2), encoding="utf-8")

            return ToolResult(ok=True, data={"config_path": str(json_path)})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_policy_tools(registry):
    """Register policy tools with the tool registry."""
    tools = [
        PolicyLoadConfigTool(),
        PolicyEvaluateTool(),
        PolicyCreateConfigTool(),
    ]
    for tool in tools:
        registry.register(tool)
