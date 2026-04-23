from __future__ import annotations

import json
from pathlib import Path

import scripts.check_workboard_claims as gate
import scripts.workboard_message as msg_mod
import scripts.workboard_swarm as mod


def _write_workboard(
    tmp_path: Path,
    *,
    claims_block: str = "- none",
    active_tasks_block: str = "- none",
    issues_block: str = "- none",
    up_for_grabs_block: str = "- none",
) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            "Claim format:\n"
            "`- \\`agent=<id>; scope=<path[,path...]>; task=<short text>\\``\n\n"
            f"{claims_block}\n\n"
            "## Active Tasks\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; agent=<id>; scope=<path[,path...]>; summary=<short text>; status=<active|blocked>\\``\n\n"
            f"{active_tasks_block}\n\n"
            "## Issues / Blockers\n\n"
            "Issue format:\n"
            "`- \\`issue_id=<id>; task_id=<task_id>; reporter=<id>; owner=<id|unassigned>; state=<open|triaged|resolved>; summary=<short text>\\``\n\n"
            f"{issues_block}\n\n"
            "## Up For Grabs\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; scope=<path[,path...]>; summary=<short text>; reported_by=<id>\\``\n\n"
            f"{up_for_grabs_block}\n\n"
            "## Supporting Docs (Not Plan Sources)\n\n"
            "- docs/PROJECT_SCOPE.md\n"
        ),
        encoding="utf-8",
    )
    return path


def test_create_swarm_plans_manifest_and_board_section(tmp_path: Path, capsys) -> None:
    target_scope = "runtime/workboard_swarm_scope_materialize_test/feature-a.mjs"
    target_path = Path(mod.ROOT) / target_scope
    assert not target_path.exists()
    workboard = _write_workboard(
        tmp_path,
        claims_block=f"- agent=Codex 1; scope={target_scope}; task=lane a",
        active_tasks_block=f"- task_id=swarm-target; agent=Codex 1; scope={target_scope}; summary=lane a; status=active",
    )
    rc = mod.run(
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
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "create"
    assert payload["session"]["state"] == "planned"
    assert payload["agent_count"] == 2
    assert "## Swarm Sessions" in text

    manifest_rel = str(payload["session"]["manifest"])
    manifest_path = (Path(mod.ROOT) / manifest_rel).resolve()
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["entry_count"] == 2
    first = dict((manifest.get("entries") or [])[0])
    assert "prompt_path" in first
    assert first["lane_scope"] == target_scope
    assert first["lane_task_id"].endswith(" lane codex-11")
    assert Path(str(first["lane_note_path"])).exists()
    assert not target_path.exists()
    assert "swarm-target" in str(first.get("bootstrap", ""))
    assert "terminal online" in str(first.get("bootstrap", ""))
    assert "if ($LASTEXITCODE -ne 0)" in str(first.get("bootstrap", ""))
    assert "--allow-presence-override" not in str(first.get("bootstrap", ""))
    assert gate.evaluate(workboard) == []


def test_create_swarm_uses_explicit_scopes_without_coordinator_overlap(tmp_path: Path, capsys) -> None:
    scopes_file = tmp_path / "scopes.txt"
    scopes_file.write_text(
        "\n".join(
            [
                "runtime/workboard_swarm_explicit_scope_test/feature-01.mjs",
                "runtime/workboard_swarm_explicit_scope_test/feature-02.mjs",
            ]
        ),
        encoding="utf-8",
    )
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Coordinator; scope=runtime/workboard_swarm_explicit_scope_test/SPEC.md; task=swarm-target",
        active_tasks_block="- task_id=swarm-target; agent=Coordinator; scope=runtime/workboard_swarm_explicit_scope_test/SPEC.md; summary=lane a; status=active",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--create",
            "--task-id",
            "swarm-target",
            "--agents",
            "Codex 11,Codex 12",
            "--scopes-file",
            str(scopes_file),
            "--spawn-command",
            "codex --help",
            "--no-summons",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    manifest_path = (Path(mod.ROOT) / str(payload["session"]["manifest"])).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = [dict(row) for row in manifest["entries"]]
    assert [row["lane_scope"] for row in entries] == scopes_file.read_text(encoding="utf-8").splitlines()
    assert [row["lane_task_id"].rsplit(" ", 1)[-1] for row in entries] == ["codex-11", "codex-12"]
    for row in entries:
        assert not (Path(mod.ROOT) / row["lane_scope"]).exists()
    assert gate.evaluate(workboard) == []


def test_create_swarm_bakes_worker_env_into_bootstrap(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Coordinator; scope=output/benchmarks/swarm/SPEC.md; task=swarm-target",
        active_tasks_block="- task_id=swarm-target; agent=Coordinator; scope=output/benchmarks/swarm/SPEC.md; summary=lane a; status=active",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--create",
            "--task-id",
            "swarm-target",
            "--agents",
            "Codex 11",
            "--spawn-command",
            "codex --help",
            "--env",
            "THOMAS_BENCHMARK_MODE=1",
            "--env",
            "THOMAS_BENCHMARK_RUN_ID=swarm-target",
            "--no-summons",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    manifest_path = (Path(mod.ROOT) / str(payload["session"]["manifest"])).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first = dict((manifest.get("entries") or [])[0])
    assert manifest["env"]["THOMAS_BENCHMARK_MODE"] == "1"
    assert first["env"]["THOMAS_BENCHMARK_RUN_ID"] == "swarm-target"
    assert "$env:THOMAS_BENCHMARK_MODE='1'" in str(first.get("bootstrap", ""))
    assert "$env:THOMAS_BENCHMARK_RUN_ID='swarm-target'" in str(first.get("bootstrap", ""))
    assert gate.evaluate(workboard) == []


def test_launch_swarm_dry_run_does_not_change_state(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=scripts/a.py; task=lane a",
        active_tasks_block="- task_id=swarm-target; agent=Codex 1; scope=scripts/a.py; summary=lane a; status=active",
    )
    assert (
        mod.run(
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
        == 0
    )
    create_payload = json.loads(capsys.readouterr().out)
    swarm_id = str(create_payload["session"]["swarm_id"])

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--launch",
            "--swarm-id",
            swarm_id,
            "--dry-run",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["launched_count"] == 2

    rc_status = mod.run(
        [
            "--workboard",
            str(workboard),
            "--status",
            "--swarm-id",
            swarm_id,
            "--json",
        ]
    )
    status_payload = json.loads(capsys.readouterr().out)
    assert rc_status == 0
    assert status_payload["session"]["state"] == "planned"
    assert gate.evaluate(workboard) == []


def test_create_swarm_sends_summon_messages(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=scripts/a.py; task=lane a",
        active_tasks_block="- task_id=swarm-target; agent=Codex 1; scope=scripts/a.py; summary=lane a; status=active",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--create",
            "--task-id",
            "swarm-target",
            "--agents",
            "Codex 21,Codex 22",
            "--spawn-command",
            "codex --help",
            "--priority",
            "p0",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["summon_count"] == 2
    assert "## Agent Message Traffic" in text
    assert "swarm summon" in text
    assert gate.evaluate(workboard) == []


def test_launch_missing_only_targets_agents_without_online_status(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        claims_block="- agent=Codex 1; scope=scripts/a.py; task=lane a",
        active_tasks_block="- task_id=swarm-target; agent=Codex 1; scope=scripts/a.py; summary=lane a; status=active",
    )
    assert (
        mod.run(
            [
                "--workboard",
                str(workboard),
                "--create",
                "--task-id",
                "swarm-target",
                "--agents",
                "Codex 31,Codex 32",
                "--spawn-command",
                "codex --help",
                "--no-summons",
                "--json",
            ]
        )
        == 0
    )
    create_payload = json.loads(capsys.readouterr().out)
    swarm_id = str(create_payload["session"]["swarm_id"])

    ok_msg, payload_msg = msg_mod.send_message(
        workboard,
        sender="Codex 31",
        recipient="thomas",
        summary=f"swarm {swarm_id} terminal online",
        task_id="swarm-target",
        kind="status",
        priority="p0",
        requested_action="none",
        decision="pending",
    )
    assert ok_msg is True, payload_msg

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--launch-missing",
            "--swarm-id",
            swarm_id,
            "--dry-run",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "launch_missing"
    assert payload["launched_count"] == 1
    assert payload["online_count"] == 1
    assert payload["missing_count"] == 1
    assert payload["online_agents"] == ["Codex 31"]
    assert payload["missing_agents"] == ["Codex 32"]

    rc_status = mod.run(
        [
            "--workboard",
            str(workboard),
            "--status",
            "--swarm-id",
            swarm_id,
            "--json",
        ]
    )
    status_payload = json.loads(capsys.readouterr().out)
    assert rc_status == 0
    assert status_payload["session"]["state"] == "planned"
    assert gate.evaluate(workboard) == []
