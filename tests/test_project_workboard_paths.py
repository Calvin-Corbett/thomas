from __future__ import annotations

import json
from pathlib import Path

import scripts.init_project_workboard as init_mod
import scripts.workboard_paths as paths_mod
import scripts.workboard_swarm as swarm_mod
import scripts.workboard_task_manager as task_manager_mod


def _write_workboard(
    path: Path,
    *,
    claims_block: str = "- none",
    active_tasks_block: str = "- none",
    up_for_grabs_block: str = "- none",
    issues_block: str = "- none",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "# Project Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            f"{claims_block}\n\n"
            "## Active Tasks\n\n"
            f"{active_tasks_block}\n\n"
            "## Up For Grabs\n\n"
            f"{up_for_grabs_block}\n\n"
            "## Issues / Blockers\n\n"
            f"{issues_block}\n\n"
            "## Agent Message Traffic\n\n"
            "- none\n\n"
            "## Supporting Docs (Not Plan Sources)\n\n"
            "- none\n"
        ),
        encoding="utf-8",
    )
    return path


def _resolve_payload_path(raw: str) -> Path:
    candidate = Path(str(raw))
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path(swarm_mod.ROOT) / candidate).resolve()


def test_init_project_workboard_creates_project_local_scaffold(tmp_path: Path, capsys) -> None:
    rc = init_mod.run(["--repo-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    workboard = tmp_path / ".thomas" / "WORKBOARD.md"
    assert rc == 0
    assert payload["workboard"] == str(workboard)
    assert workboard.exists()
    assert (tmp_path / ".thomas" / "tasks").is_dir()
    assert (tmp_path / ".thomas" / "problems").is_dir()
    assert (tmp_path / ".thomas" / "swarm").is_dir()
    assert (tmp_path / ".thomas" / "coordination").is_dir()
    assert (tmp_path / ".thomas" / "workers").is_dir()
    assert (tmp_path / ".thomas" / "worker_command_catalog.json").exists()
    assert paths_mod.default_workboard_path(tmp_path) == workboard.resolve()


def test_workboard_swarm_uses_project_local_swarm_artifacts(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path / ".thomas" / "WORKBOARD.md",
        claims_block="- agent=Coordinator; scope=src/spec.md; task=swarm-target",
        active_tasks_block="- task_id=swarm-target; agent=Coordinator; scope=src/spec.md; summary=lane a; status=active",
    )

    rc = swarm_mod.run(
        [
            "--workboard",
            str(workboard),
            "--create",
            "--task-id",
            "swarm-target",
            "--agents",
            "Codex 11,Codex 12",
            "--spawn-command",
            "codex --help",
            "--no-summons",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    manifest_path = _resolve_payload_path(str(payload["session"]["manifest"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert rc == 0
    assert manifest_path.parent == (workboard.parent / "swarm").resolve()
    assert manifest["entry_count"] == 2
    assert (
        Path(manifest["entries"][1]["lane_note_path"]).resolve().is_relative_to((workboard.parent / "swarm").resolve())
    )
    assert "/.thomas/swarm/" in str(manifest["entries"][1]["lane_scope"]).replace("\\", "/")


def test_task_manager_sync_plans_uses_project_local_roots(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(tmp_path / ".thomas" / "WORKBOARD.md")
    captured: dict[str, object] = {}

    def _fake_sync_task_plans(**kwargs):
        captured.update(kwargs)
        return True, {
            "tracked_task_count": 0,
            "plan_entry_count": 0,
            "created_plan_count": 0,
            "problem_entry_count": 0,
            "created_problem_count": 0,
        }

    monkeypatch.setattr(task_manager_mod, "_sync_task_plans", _fake_sync_task_plans)

    rc = task_manager_mod.run(["--workboard", str(workboard), "--sync-plans", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert Path(str(captured["workboard_path"])).resolve() == workboard.resolve()
    assert Path(str(captured["plan_root"])).resolve() == (workboard.parent / "tasks").resolve()
    assert Path(str(captured["problem_root"])).resolve() == (workboard.parent / "problems").resolve()
