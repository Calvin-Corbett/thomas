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
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_write_workboard(tmp_path),
    )

    assert payload["lane"] == "simple-edit"
    assert payload["workboard_required"] is False
    assert "docs/AGENT_FILE_EDITING_RULES.md" in payload["required_reads"]


def test_router_classifies_ui_proof_lane(tmp_path: Path) -> None:
    payload = mod.classify_task(
        summary="Update the website hero",
        paths=["apps/site/src/app/page.tsx"],
        edit_intent=True,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_write_workboard(tmp_path),
    )

    assert payload["lane"] == "ui-proof"
    assert payload["workboard_required"] is True
    assert ".codex/skills/ui-precision-guard/SKILL.md" in payload["required_reads"]


def test_router_escalates_claim_conflict_to_risky_lane(tmp_path: Path) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 7; scope=thomas/core/config.py; task=runtime lane",
    )
    payload = mod.classify_task(
        summary="Patch config flow",
        paths=["thomas/core/config.py"],
        edit_intent=True,
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
