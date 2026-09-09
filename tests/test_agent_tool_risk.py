from __future__ import annotations

from thomas.agent.tool_risk import (
    ToolActionCategory,
    ToolRiskControl,
    ToolRiskLevel,
    classify_tool_action,
)


def test_classifies_shell_actions_as_high_risk() -> None:
    profile = classify_tool_action("shell.run", {"command": "pytest tests/test_example.py"})

    assert profile.category == ToolActionCategory.SHELL
    assert profile.risk_level == ToolRiskLevel.HIGH
    assert ToolRiskControl.MANUAL_APPROVAL in profile.recommended_controls
    assert ToolRiskControl.PATH_SANDBOX in profile.recommended_controls
    assert profile.matched_rule == "shell_execution"


def test_escalates_destructive_shell_actions_to_critical() -> None:
    profile = classify_tool_action("powershell", {"command": "Remove-Item -Recurse runtime/cache"})

    assert profile.category == ToolActionCategory.SHELL
    assert profile.risk_level == ToolRiskLevel.CRITICAL
    assert ToolRiskControl.DENY_BY_DEFAULT in profile.recommended_controls


def test_classifies_secret_like_file_reads_with_secret_controls() -> None:
    profile = classify_tool_action("fs.read", {"path": ".env.local"})

    assert profile.category == ToolActionCategory.SECRET
    assert profile.risk_level == ToolRiskLevel.CRITICAL
    assert ToolRiskControl.SECRET_ISOLATION in profile.recommended_controls
    assert ToolRiskControl.REDACT_OUTPUT in profile.recommended_controls
    assert profile.matched_rule == "secret_access"


def test_classifies_network_and_browser_actions_with_host_policy() -> None:
    network_profile = classify_tool_action("web.fetch", {"url": "https://example.com"})
    browser_profile = classify_tool_action("browser.open", {"url": "https://example.com"})

    assert network_profile.category == ToolActionCategory.NETWORK
    assert network_profile.risk_level == ToolRiskLevel.MEDIUM
    assert ToolRiskControl.HOST_POLICY in network_profile.recommended_controls
    assert browser_profile.category == ToolActionCategory.BROWSER
    assert ToolRiskControl.HOST_POLICY in browser_profile.recommended_controls


def test_unknown_actions_fail_closed_as_high_risk() -> None:
    profile = classify_tool_action("new.autonomous.action", {"payload": "unmapped"})

    assert profile.category == ToolActionCategory.UNKNOWN
    assert profile.risk_level == ToolRiskLevel.HIGH
    assert profile.matched_rule == "unknown_fail_closed"
    assert profile.recommended_controls == (
        ToolRiskControl.DENY_BY_DEFAULT,
        ToolRiskControl.MANUAL_APPROVAL,
        ToolRiskControl.AUDIT_LOG,
    )


def test_classification_is_deterministic_and_immutable() -> None:
    first = classify_tool_action("plugin.install", {"name": "example"})
    second = classify_tool_action("plugin.install", {"name": "example"})

    assert first == second
    assert first.category == ToolActionCategory.TOOL_ADMIN
    assert isinstance(first.recommended_controls, tuple)
