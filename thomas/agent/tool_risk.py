"""Offline risk mapping for Thomas agent tool actions.

Destructive-command detection is delegated to the parsed-command policy in
``thomas.agent.command_analysis`` (tokenized argv analysis with chaining,
wrapper and obfuscation handling) instead of legacy substring markers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from thomas.agent.command_analysis import CommandFinding, analyze_command


class ToolActionCategory(str, Enum):
    """Governance categories used for agent action review and audit."""

    BROWSER = "browser"
    DELEGATION = "delegation"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    NETWORK = "network"
    SECRET = "secret"
    SHELL = "shell"
    TOOL_ADMIN = "tool_admin"
    UNKNOWN = "unknown"


class ToolRiskLevel(str, Enum):
    """Ordered risk levels for tool action preflight decisions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolRiskControl(str, Enum):
    """Recommended controls a caller can translate into runtime policy."""

    ALLOWLIST = "allowlist"
    AUDIT_LOG = "audit_log"
    DENY_BY_DEFAULT = "deny_by_default"
    HOST_POLICY = "host_policy"
    MANUAL_APPROVAL = "manual_approval"
    PATH_SANDBOX = "path_sandbox"
    RATE_LIMIT = "rate_limit"
    REDACT_OUTPUT = "redact_output"
    SECRET_ISOLATION = "secret_isolation"


@dataclass(frozen=True)
class ToolRiskProfile:
    """Deterministic risk classification for one agent tool action."""

    category: ToolActionCategory
    risk_level: ToolRiskLevel
    recommended_controls: tuple[ToolRiskControl, ...]
    reason: str
    matched_rule: str


@dataclass(frozen=True)
class _ToolRiskRule:
    name: str
    category: ToolActionCategory
    risk_level: ToolRiskLevel
    controls: tuple[ToolRiskControl, ...]
    tool_prefixes: tuple[str, ...]
    arg_markers: tuple[str, ...] = ()


_BASE_CONTROLS = (ToolRiskControl.AUDIT_LOG,)
_APPROVAL_CONTROLS = (ToolRiskControl.MANUAL_APPROVAL, ToolRiskControl.AUDIT_LOG)
_FAIL_CLOSED_CONTROLS = (
    ToolRiskControl.DENY_BY_DEFAULT,
    ToolRiskControl.MANUAL_APPROVAL,
    ToolRiskControl.AUDIT_LOG,
)

_SECRET_MARKERS = (
    ".env",
    "api_key",
    "auth_token",
    "credential",
    "oauth",
    "password",
    "private_key",
    "secret",
    "ssh_key",
    "token",
)

_RULES = (
    _ToolRiskRule(
        name="secret_access",
        category=ToolActionCategory.SECRET,
        risk_level=ToolRiskLevel.CRITICAL,
        controls=(
            ToolRiskControl.DENY_BY_DEFAULT,
            ToolRiskControl.MANUAL_APPROVAL,
            ToolRiskControl.SECRET_ISOLATION,
            ToolRiskControl.REDACT_OUTPUT,
            ToolRiskControl.AUDIT_LOG,
        ),
        tool_prefixes=("secret.", "secrets.", "vault.", "credential.", "credentials."),
        arg_markers=_SECRET_MARKERS,
    ),
    _ToolRiskRule(
        name="shell_execution",
        category=ToolActionCategory.SHELL,
        risk_level=ToolRiskLevel.HIGH,
        controls=(
            ToolRiskControl.MANUAL_APPROVAL,
            ToolRiskControl.PATH_SANDBOX,
            ToolRiskControl.REDACT_OUTPUT,
            ToolRiskControl.AUDIT_LOG,
        ),
        tool_prefixes=("cmd", "command.", "exec.", "powershell", "shell", "subprocess.", "terminal."),
    ),
    _ToolRiskRule(
        name="file_mutation",
        category=ToolActionCategory.FILE_WRITE,
        risk_level=ToolRiskLevel.HIGH,
        controls=(
            ToolRiskControl.MANUAL_APPROVAL,
            ToolRiskControl.PATH_SANDBOX,
            ToolRiskControl.AUDIT_LOG,
        ),
        tool_prefixes=(
            "file.delete",
            "file.move",
            "file.write",
            "filesystem.delete",
            "filesystem.move",
            "fs.delete",
            "fs.write",
        ),
    ),
    _ToolRiskRule(
        name="file_read",
        category=ToolActionCategory.FILE_READ,
        risk_level=ToolRiskLevel.LOW,
        controls=(ToolRiskControl.PATH_SANDBOX, ToolRiskControl.AUDIT_LOG),
        tool_prefixes=("file.read", "filesystem.read", "fs.read", "read_file"),
    ),
    _ToolRiskRule(
        name="network_access",
        category=ToolActionCategory.NETWORK,
        risk_level=ToolRiskLevel.MEDIUM,
        controls=(
            ToolRiskControl.HOST_POLICY,
            ToolRiskControl.RATE_LIMIT,
            ToolRiskControl.REDACT_OUTPUT,
            ToolRiskControl.AUDIT_LOG,
        ),
        tool_prefixes=("fetch.", "http.", "network.", "request.", "url.", "web.fetch", "web.search"),
    ),
    _ToolRiskRule(
        name="browser_automation",
        category=ToolActionCategory.BROWSER,
        risk_level=ToolRiskLevel.MEDIUM,
        controls=(
            ToolRiskControl.HOST_POLICY,
            ToolRiskControl.PATH_SANDBOX,
            ToolRiskControl.REDACT_OUTPUT,
            ToolRiskControl.AUDIT_LOG,
        ),
        tool_prefixes=("browser.", "playwright.", "selenium."),
    ),
    _ToolRiskRule(
        name="delegation",
        category=ToolActionCategory.DELEGATION,
        risk_level=ToolRiskLevel.HIGH,
        controls=_APPROVAL_CONTROLS,
        tool_prefixes=("agent.delegate", "codex.", "thread.", "workboard.claim", "workboard.dispatch"),
    ),
    _ToolRiskRule(
        name="tool_administration",
        category=ToolActionCategory.TOOL_ADMIN,
        risk_level=ToolRiskLevel.HIGH,
        controls=(
            ToolRiskControl.ALLOWLIST,
            ToolRiskControl.MANUAL_APPROVAL,
            ToolRiskControl.AUDIT_LOG,
        ),
        tool_prefixes=("mcp.", "plugin.", "skill.install", "tool.install", "tool.permission", "tools.register"),
    ),
)

_RISK_ORDER = {
    ToolRiskLevel.LOW: 1,
    ToolRiskLevel.MEDIUM: 2,
    ToolRiskLevel.HIGH: 3,
    ToolRiskLevel.CRITICAL: 4,
}


def classify_tool_action(tool_name: str, args: dict[str, Any] | None = None) -> ToolRiskProfile:
    """Classify a tool action for governance preflight without calling external services."""

    normalized_name = _normalize_tool_name(tool_name)
    normalized_args = _flatten_args(args or {})
    command_findings = _collect_command_findings(args or {})
    candidates = [rule for rule in _RULES if _matches_rule(rule, normalized_name, normalized_args, command_findings)]

    if not candidates:
        return ToolRiskProfile(
            category=ToolActionCategory.UNKNOWN,
            risk_level=ToolRiskLevel.HIGH,
            recommended_controls=_FAIL_CLOSED_CONTROLS,
            reason=f"Unknown tool action '{tool_name}' has no offline risk rule; require explicit review.",
            matched_rule="unknown_fail_closed",
        )

    rule = max(candidates, key=lambda item: _RISK_ORDER[item.risk_level])
    risk_level = rule.risk_level
    controls = rule.controls
    reason = f"Tool action '{tool_name}' matched {rule.name} risk rule."

    if rule.name == "file_read" and _contains_marker(normalized_args, _SECRET_MARKERS):
        risk_level = ToolRiskLevel.CRITICAL
        controls = (
            ToolRiskControl.DENY_BY_DEFAULT,
            ToolRiskControl.MANUAL_APPROVAL,
            ToolRiskControl.SECRET_ISOLATION,
            ToolRiskControl.REDACT_OUTPUT,
            ToolRiskControl.AUDIT_LOG,
        )
        reason = f"File read action '{tool_name}' targets secret-like arguments; treat as secret access."

    if rule.name == "shell_execution" and command_findings:
        trigger = command_findings[0]
        risk_level = ToolRiskLevel.CRITICAL
        controls = (
            ToolRiskControl.DENY_BY_DEFAULT,
            ToolRiskControl.MANUAL_APPROVAL,
            ToolRiskControl.PATH_SANDBOX,
            ToolRiskControl.REDACT_OUTPUT,
            ToolRiskControl.AUDIT_LOG,
        )
        reason = (
            f"Shell action '{tool_name}' includes destructive parsed command segment "
            f"'{trigger.segment}' ({trigger.reason}); require fail-closed controls."
        )

    return ToolRiskProfile(
        category=rule.category,
        risk_level=risk_level,
        recommended_controls=controls,
        reason=reason,
        matched_rule=rule.name,
    )


def _matches_rule(
    rule: _ToolRiskRule,
    normalized_name: str,
    normalized_args: str,
    command_findings: tuple[CommandFinding, ...],
) -> bool:
    if normalized_name.startswith(rule.tool_prefixes):
        return True
    if rule.name == "shell_execution":
        return bool(command_findings)
    return bool(rule.arg_markers and _contains_marker(normalized_args, rule.arg_markers))


def _collect_command_findings(args: dict[str, Any]) -> tuple[CommandFinding, ...]:
    """Run parsed-command danger analysis over every command-like argument value."""

    findings: list[CommandFinding] = []

    def _walk(value: Any) -> None:
        if isinstance(value, str):
            findings.extend(analyze_command(value).findings)
        elif isinstance(value, dict):
            for key in value:
                _walk(value[key])
        elif isinstance(value, (list, tuple)):
            if value and all(isinstance(item, str) for item in value):
                # argv-style command lists are analyzed as one command line
                findings.extend(analyze_command(" ".join(value)).findings)
            else:
                for item in value:
                    _walk(item)

    _walk(args)
    return tuple(findings)


def _contains_marker(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)


def _normalize_tool_name(tool_name: str) -> str:
    return str(tool_name or "").strip().lower().replace("_", ".")


def _flatten_args(args: dict[str, Any]) -> str:
    values: list[str] = []

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                values.append(str(key).lower())
                _walk(value[key])
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                _walk(item)
        else:
            values.append(str(value).lower())

    _walk(args)
    return " ".join(values)
