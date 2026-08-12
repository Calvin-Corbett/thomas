"""Tests for deterministic plan re-approval triggers (CAP-050).

Acceptance: "Re-approval must trigger deterministically when execution discovers
a materially surprising action."
"""

from __future__ import annotations

from thomas.agent.plan_reapproval import (
    ApprovedPlan,
    ProposedAction,
    ReapprovalDecision,
    SurpriseKind,
    evaluate_action,
)
from thomas.agent.tool_risk import ToolRiskLevel


def _base_plan() -> ApprovedPlan:
    return ApprovedPlan.build(
        allowed_tools=["file.read", "file.write", "browser.*"],
        risk_ceiling=ToolRiskLevel.MEDIUM,
        write_globs=["src/**", "docs/*.md"],
        forbidden_operations=["force_push"],
        allow_destructive=False,
    )


def test_in_scope_action_does_not_trigger_reapproval() -> None:
    plan = _base_plan()
    action = ProposedAction(
        tool="file.write",
        risk_level=ToolRiskLevel.MEDIUM,
        write_paths=("src/module/a.py",),
    )

    decision = evaluate_action(plan, action)

    assert decision.requires_reapproval is False
    assert decision.triggers == ()
    assert decision.reasons == ()


def test_out_of_allowlist_tool_triggers_with_reason() -> None:
    plan = _base_plan()
    action = ProposedAction(tool="shell.exec", risk_level=ToolRiskLevel.LOW)

    decision = evaluate_action(plan, action)

    assert decision.requires_reapproval is True
    assert SurpriseKind.TOOL_OUT_OF_SCOPE in decision.kinds
    reason = next(t.reason for t in decision.triggers if t.kind is SurpriseKind.TOOL_OUT_OF_SCOPE)
    assert "shell.exec" in reason
    assert "allowlist" in reason


def test_risk_escalation_above_ceiling_triggers() -> None:
    plan = _base_plan()  # ceiling MEDIUM
    action = ProposedAction(
        tool="file.write",
        risk_level=ToolRiskLevel.CRITICAL,
        write_paths=("src/a.py",),
    )

    decision = evaluate_action(plan, action)

    assert decision.requires_reapproval is True
    assert SurpriseKind.RISK_ESCALATION in decision.kinds
    reason = next(t.reason for t in decision.triggers if t.kind is SurpriseKind.RISK_ESCALATION)
    assert "critical" in reason and "medium" in reason


def test_write_outside_approved_globs_triggers() -> None:
    plan = _base_plan()
    action = ProposedAction(
        tool="file.write",
        risk_level=ToolRiskLevel.MEDIUM,
        write_paths=("/etc/passwd",),
    )

    decision = evaluate_action(plan, action)

    assert decision.requires_reapproval is True
    assert SurpriseKind.WRITE_OUTSIDE_SCOPE in decision.kinds
    reason = next(t.reason for t in decision.triggers if t.kind is SurpriseKind.WRITE_OUTSIDE_SCOPE)
    assert "/etc/passwd" in reason


def test_windows_style_write_path_normalized_against_globs() -> None:
    plan = _base_plan()
    # Backslash path that logically lives under an approved glob must be in scope.
    action = ProposedAction(
        tool="file.write",
        risk_level=ToolRiskLevel.MEDIUM,
        write_paths=("src\\pkg\\mod.py",),
    )

    decision = evaluate_action(plan, action)

    assert decision.requires_reapproval is False


def test_newly_destructive_operation_triggers() -> None:
    plan = _base_plan()  # allow_destructive False
    action = ProposedAction(
        tool="file.write",
        risk_level=ToolRiskLevel.MEDIUM,
        write_paths=("src/a.py",),
        destructive=True,
    )

    decision = evaluate_action(plan, action)

    assert decision.requires_reapproval is True
    assert SurpriseKind.NEWLY_DESTRUCTIVE in decision.kinds


def test_destructive_allowed_when_plan_approves_it() -> None:
    plan = ApprovedPlan.build(
        allowed_tools=["file.write"],
        risk_ceiling=ToolRiskLevel.HIGH,
        write_globs=["src/**"],
        allow_destructive=True,
    )
    action = ProposedAction(
        tool="file.write",
        risk_level=ToolRiskLevel.HIGH,
        write_paths=("src/a.py",),
        destructive=True,
    )

    decision = evaluate_action(plan, action)

    assert decision.requires_reapproval is False


def test_explicit_forbidden_operation_triggers() -> None:
    plan = _base_plan()
    action = ProposedAction(
        tool="browser.click",
        risk_level=ToolRiskLevel.LOW,
        operations=frozenset({"force_push"}),
    )

    decision = evaluate_action(plan, action)

    assert decision.requires_reapproval is True
    assert SurpriseKind.CONSTRAINT_VIOLATION in decision.kinds


def test_multiple_surprises_all_reported_in_check_order() -> None:
    plan = _base_plan()
    action = ProposedAction(
        tool="shell.exec",  # out of allowlist
        risk_level=ToolRiskLevel.CRITICAL,  # escalation above MEDIUM
        write_paths=("/tmp/evil.sh",),  # outside globs
        destructive=True,  # newly destructive
        operations=frozenset({"force_push"}),  # forbidden constraint
    )

    decision = evaluate_action(plan, action)

    assert decision.requires_reapproval is True
    # Fixed, documented check order.
    assert decision.kinds == (
        SurpriseKind.TOOL_OUT_OF_SCOPE,
        SurpriseKind.RISK_ESCALATION,
        SurpriseKind.WRITE_OUTSIDE_SCOPE,
        SurpriseKind.NEWLY_DESTRUCTIVE,
        SurpriseKind.CONSTRAINT_VIOLATION,
    )


def test_determinism_same_action_same_decision() -> None:
    plan = _base_plan()
    action = ProposedAction(
        tool="shell.exec",
        risk_level=ToolRiskLevel.CRITICAL,
        write_paths=("/tmp/x",),
        destructive=True,
        operations=frozenset({"force_push"}),
    )

    first = evaluate_action(plan, action)
    results = [evaluate_action(plan, action) for _ in range(25)]

    assert all(r == first for r in results)
    assert all(r.to_dict() == first.to_dict() for r in results)
    assert all(r.kinds == first.kinds for r in results)


def test_injected_risk_level_is_authoritative() -> None:
    plan = ApprovedPlan.build(allowed_tools=["anytool"], risk_ceiling=ToolRiskLevel.LOW)
    # Injected LOW keeps it in scope regardless of what a classifier would say.
    action = ProposedAction(tool="anytool", risk_level=ToolRiskLevel.LOW)

    assert evaluate_action(plan, action).requires_reapproval is False


def test_derived_risk_used_when_not_injected() -> None:
    # No injected risk level: derived offline from the tool name. A shell tool
    # classifies as HIGH, which exceeds a LOW ceiling and triggers re-approval.
    plan = ApprovedPlan.build(allowed_tools=["shell"], risk_ceiling=ToolRiskLevel.LOW)
    action = ProposedAction(tool="shell", args={"cmd": "ls"})

    decision = evaluate_action(plan, action)

    assert decision.requires_reapproval is True
    assert SurpriseKind.RISK_ESCALATION in decision.kinds


def test_decision_is_frozen_and_reasons_aligned() -> None:
    plan = _base_plan()
    action = ProposedAction(tool="unknown.tool", risk_level=ToolRiskLevel.LOW)
    decision = evaluate_action(plan, action)

    assert isinstance(decision, ReapprovalDecision)
    assert len(decision.reasons) == len(decision.triggers)
    assert decision.reasons[0] == decision.triggers[0].reason
