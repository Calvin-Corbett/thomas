from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_router_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "agent_startup_router.py"
    spec = importlib.util.spec_from_file_location("agent_startup_router", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_router_module()


def _write_workboard(tmp_path: Path, claims_block: str = "- none") -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "Last updated: 2026-03-18\n\n"
            "## Agent Claims\n\n"
            f"{claims_block}\n\n"
            "## Active Tasks\n\n"
            "- none\n"
        ),
        encoding="utf-8",
    )
    return path


def test_router_classifies_chat_lane(tmp_path: Path) -> None:
    payload = mod.classify_task(
        summary="Answer a repo question",
        paths=[],
        edit_intent=False,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_write_workboard(tmp_path),
    )

    assert payload["lane"] == "chat"
    assert payload["required_checks"] == []
    assert payload["workboard_required"] is False


def test_router_classifies_simple_edit_lane(tmp_path: Path) -> None:
    payload = mod.classify_task(
        summary="Patch a small bug",
        paths=["thomas/core/config.py"],
        edit_intent=True,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_write_workboard(tmp_path),
    )

    assert payload["lane"] == "simple-edit"
    assert payload["workboard_required"] is True
    assert ".thomas/WORKBOARD.md" in payload["required_reads"]
    assert payload["required_checks"][0] == "Bootstrap a workboard claim before implementation."
    assert "docs/AGENT_FILE_EDITING_RULES.md" in payload["required_reads"]


def test_router_classifies_ui_proof_lane(tmp_path: Path) -> None:
    payload = mod.classify_task(
        summary="Update the local web UI header",
        paths=["thomas/server/web/js/app_runtime_primary.mjs"],
        edit_intent=True,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_write_workboard(tmp_path),
    )

    assert payload["lane"] == "ui-proof"
    assert payload["workboard_required"] is True
    assert "docs/ai/CHECKLISTS/ui.md" in payload["required_reads"]


def test_router_escalates_claim_conflict_to_risky_lane(tmp_path: Path) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 7; scope=thomas/core/config.py; task=runtime lane",
    )
    payload = mod.classify_task(
        summary="Patch config flow",
        paths=["thomas/core/config.py"],
        edit_intent=True,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=workboard,
    )

    assert payload["lane"] == "risky-edit"
    assert payload["workboard_required"] is True
    assert payload["workboard"]["claim_conflict"] is True
    assert payload["workboard"]["matching_claims"][0]["agent"] == "Codex 7"


def test_router_classifies_benchmark_lane(tmp_path: Path) -> None:
    payload = mod.classify_task(
        summary="Run snake benchmark",
        paths=["output/benchmarks/snake/run-1/thomas/index.html"],
        edit_intent=True,
        benchmark_mode=True,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_write_workboard(tmp_path),
    )

    assert payload["lane"] == "benchmark"
    assert payload["flags"]["benchmark_mode"] is True
    assert "docs/ai/CHECKLISTS/agent-lane-benchmark.md" in payload["required_reads"]


def test_build_startup_payload_includes_preflight(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mod.agent_preflight,
        "evaluate_preflight",
        lambda **_: {
            "status": "degraded",
            "summary": "1 degraded, 2 ok",
            "checks": [
                {
                    "id": "rg",
                    "status": "degraded",
                    "message": "ripgrep unavailable",
                    "user_action": "Install rg.",
                }
            ],
            "policy": {
                "summary": "Tell the user the environment is degraded before using slower or lower-confidence fallbacks.",
                "can_edit": True,
                "report_before_fallback": True,
                "stop_before_edit": False,
            },
            "root": str(mod.ROOT),
            "cwd": str(mod.ROOT),
        },
    )

    payload = mod.build_startup_payload(
        summary="Patch a small bug",
        paths=["thomas/core/config.py"],
        edit_intent=True,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_write_workboard(tmp_path),
        cwd=mod.ROOT,
    )

    assert payload["lane"] == "simple-edit"
    assert payload["preflight"]["status"] == "degraded"
    assert payload["preflight"]["policy"]["report_before_fallback"] is True
    assert payload["gate_handling"]["auto_remediate"]
    assert payload["gate_handling"]["hard_stop"]


def test_router_text_output_surfaces_preflight(tmp_path: Path) -> None:
    payload = {
        "lane": "simple-edit",
        "workflow_mode": "guided",
        "edit_intent": True,
        "workboard_required": True,
        "workboard": {
            "path": str(tmp_path / "WORKBOARD.md"),
            "active_claims": 0,
            "matching_claims": [],
            "claim_conflict": False,
            "stale": False,
            "updated_at": "2026-03-18",
        },
        "bootstrap_command": 'python scripts/agent_bootstrap_claim.py --agent "<agent-id>" --scope "thomas/core/config.py" --task "Patch a small bug" --no-auto-dispatch',
        "gate_handling": {
            "summary": "Structural/quality gates should trigger remediation and retry; integrity/ownership/security gates remain hard stops.",
            "auto_remediate": ["monolith_guard"],
            "hard_stop": ["protected_files"],
        },
        "flags": {
            "ui_proof": False,
            "benchmark_mode": False,
            "tracked_work": False,
            "multi_agent": False,
            "long_running": False,
            "risky_paths": [],
        },
        "paths": ["thomas/core/config.py"],
        "required_reads": ["docs/AGENT_FILE_EDITING_RULES.md"],
        "required_checks": ["Run focused regression tests for changed behavior."],
        "escalation_triggers": ["Scope expands beyond a small isolated change."],
        "preflight": {
            "status": "degraded",
            "summary": "1 degraded, 3 ok",
            "checks": [
                {
                    "id": "cwd",
                    "status": "degraded",
                    "message": "Current working directory is outside repo root.",
                    "user_action": "Start commands from the repo root.",
                }
            ],
            "policy": {
                "summary": "Tell the user the environment is degraded before using slower or lower-confidence fallbacks.",
                "can_edit": True,
                "report_before_fallback": True,
                "stop_before_edit": False,
            },
            "root": str(mod.ROOT),
            "cwd": "C:/Windows/System32",
        },
    }

    text = mod._text_output(payload)

    assert "preflight_status: degraded" in text
    assert (
        "preflight_policy: Tell the user the environment is degraded before using slower or lower-confidence fallbacks."
        in text
    )
    assert "preflight_checks:" in text
    assert "bootstrap_command:" in text
    assert "gate_handling:" in text
    assert "auto_remediate_gates:" in text
    assert "hard_stop_gates:" in text
