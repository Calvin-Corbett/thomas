from __future__ import annotations

import json
from pathlib import Path

import scripts.check_workboard_agent_claim as mod


def _write_workboard(
    tmp_path: Path,
    claims_block: str,
    *,
    active_tasks_block: str = "- none",
    issues_block: str = "- none",
    up_for_grabs_block: str = "- none",
) -> Path:
    text = (
        "# Thomas Workboard\n\n"
        "## Agent Claims (Active)\n\n"
        "Use this section to announce active ownership and prevent conflicting edits.\n"
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
        f"{up_for_grabs_block}\n"
    )
    path = tmp_path / "WORKBOARD.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_gate_passes_with_matching_agent_claim(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py,tests/test_models_cli_scan_alias.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py,tests/test_models_cli_scan_alias.py; summary=models scan; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "codex 2")

    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Workboard agent claim gate: PASS" in out
    assert "matching claims: 1" in out


def test_gate_fails_when_agent_id_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(tmp_path, "- none")
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("THOMAS_AGENT_ID", raising=False)
    monkeypatch.delenv("THOMAS_AGENT_NAME", raising=False)
    monkeypatch.delenv("CODEX_AGENT_NAME", raising=False)
    monkeypatch.delenv("AGENT_NAME", raising=False)

    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "agent id is required" in out


def test_gate_fails_when_agent_has_no_claim(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 1; scope=thomas/cli/parity_compat.py; task=browser parity",
        active_tasks_block="- task_id=browser-parity; agent=Codex 1; scope=thomas/cli/parity_compat.py; summary=browser parity; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")

    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "no active workboard claim found for 'Codex 2'" in out


def test_gate_json_pass_payload(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py,tests/test_models_cli_scan_alias.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py,tests/test_models_cli_scan_alias.py; summary=models scan; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")

    rc = mod.run(["--workboard", str(workboard), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["gate"] == "workboard_agent_claim"
    assert payload["matching_claim_count"] == 1
    assert "thomas/cli/main.py" in payload["scopes"]


def test_gate_json_fail_payload_for_missing_claim(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 1; scope=thomas/cli/parity_compat.py; task=browser parity",
        active_tasks_block="- task_id=browser-parity; agent=Codex 1; scope=thomas/cli/parity_compat.py; summary=browser parity; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")

    rc = mod.run(["--workboard", str(workboard), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["gate"] == "workboard_agent_claim"
    assert payload["matching_claim_count"] == 0
    assert "no active workboard claim found" in payload["error"]


def test_gate_accepts_codex_agent_id_env(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex ID; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex ID; scope=thomas/cli/main.py; summary=models scan; status=active",
    )
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("THOMAS_AGENT_ID", raising=False)
    monkeypatch.setenv("CODEX_AGENT_ID", "codex id")

    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Workboard agent claim gate: PASS" in out


def test_gate_fails_when_agent_owns_unresolved_issue(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=blocked",
        issues_block=(
            "- issue_id=ISS-9; task_id=models-scan; reporter=qa; owner=Codex 2; " "state=open; summary=scan traceback"
        ),
    )
    monkeypatch.setenv("AGENT_ID", "codex 2")

    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "owns unresolved workboard issue(s): ISS-9" in out


def test_gate_passes_when_owned_issue_is_resolved(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=active",
        issues_block=(
            "- issue_id=ISS-9; task_id=models-scan; reporter=qa; owner=Codex 2; "
            "state=resolved; summary=scan traceback fixed"
        ),
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")

    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Workboard agent claim gate: PASS" in out


def test_gate_json_reports_unresolved_owned_issues(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=blocked",
        issues_block=(
            "\n".join(
                [
                    "- issue_id=ISS-9; task_id=models-scan; reporter=qa; owner=Codex 2; state=open; summary=scan traceback",
                    "- issue_id=ISS-10; task_id=models-scan; reporter=qa; owner=codex 2; state=triaged; summary=retry bug",
                ]
            )
        ),
    )
    monkeypatch.setenv("AGENT_ID", "codex 2")

    rc = mod.run(["--workboard", str(workboard), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["unresolved_issue_count"] == 2
    assert payload["unresolved_issue_ids"] == ["ISS-10", "ISS-9"]
    assert "owns unresolved workboard issue(s)" in payload["error"]


def test_gate_enforce_staged_scope_passes_when_staged_files_are_claimed(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py,tests/test_models_cli_scan_alias.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py,tests/test_models_cli_scan_alias.py; summary=models scan; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")
    monkeypatch.setattr(mod, "_staged_files", lambda: ["thomas/cli/main.py"])

    rc = mod.run(["--workboard", str(workboard), "--enforce-staged-scope"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Workboard agent claim gate: PASS" in out


def test_gate_enforce_staged_scope_fails_when_staged_files_are_outside_scope(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")
    monkeypatch.setattr(mod, "_staged_files", lambda: ["thomas/agent/loop.py"])

    rc = mod.run(["--workboard", str(workboard), "--enforce-staged-scope"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "staged files outside claimed scope" in out
    assert "thomas/agent/loop.py" in out


def test_gate_enforce_staged_scope_json_fail_payload(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")
    monkeypatch.setattr(mod, "_staged_files", lambda: ["thomas/agent/loop.py", "thomas/cli/main.py"])

    rc = mod.run(["--workboard", str(workboard), "--enforce-staged-scope", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["enforce_staged_scope"] is True
    assert payload["staged_file_count"] == 2
    assert payload["staged_files_outside_scope_count"] == 1
    assert payload["staged_files_outside_scope"] == ["thomas/agent/loop.py"]


def test_gate_enforce_clean_claimed_scope_fails_when_unstaged_in_scope(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")
    monkeypatch.setattr(
        mod,
        "_claimed_scope_dirty_paths",
        lambda scopes, enforce_untracked=False, ignore_patterns=(): {
            "unstaged": ["thomas/cli/main.py"],
            "untracked": [],
        },
    )

    rc = mod.run(["--workboard", str(workboard), "--enforce-clean-claimed-scope"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "dirty files in claimed scope" in out
    assert "thomas/cli/main.py" in out


def test_gate_enforce_clean_claimed_scope_json_reports_untracked_when_enabled(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")
    monkeypatch.setattr(
        mod,
        "_claimed_scope_dirty_paths",
        lambda scopes, enforce_untracked=False, ignore_patterns=(): {
            "unstaged": [],
            "untracked": ["thomas/cli/new_module.py"] if enforce_untracked else [],
        },
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--enforce-clean-claimed-scope",
            "--enforce-untracked-claimed-scope",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["enforce_clean_claimed_scope"] is True
    assert payload["enforce_untracked_claimed_scope"] is True
    assert payload["claimed_scope_untracked_count"] == 1
    assert payload["claimed_scope_untracked_files"] == ["thomas/cli/new_module.py"]


def test_gate_parent_throughput_fails_when_ready_tasks_exist_without_workers(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/agent; task=coord lane",
        active_tasks_block="- task_id=coord-lane; agent=Codex 3; scope=thomas/agent; summary=coord lane; status=active",
        up_for_grabs_block="- task_id=server-lane; scope=thomas/server/routes; summary=server lane; reported_by=bot",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 3")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--enforce-parent-throughput",
            "--parent-target-workers",
            "1",
            "--parent-min-ready-suggestions",
            "1",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "parent agent 'Codex 3' has 0 active worker claim(s)" in out


def test_gate_parent_throughput_passes_with_active_worker(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "\n".join(
            [
                "- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/agent; task=coord lane",
                "- agent=Codex 3-Worker-1; name=Prime-worker-1; role=worker; parent=Codex 3; scope=thomas/server/routes; task=worker lane",
            ]
        ),
        active_tasks_block="\n".join(
            [
                "- task_id=coord-lane; agent=Codex 3; scope=thomas/agent; summary=coord lane; status=active",
                "- task_id=worker-lane; agent=Codex 3-Worker-1; scope=thomas/server/routes; summary=worker lane; status=active",
            ]
        ),
        up_for_grabs_block="- task_id=core-lane; scope=thomas/core; summary=core lane; reported_by=bot",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 3")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--enforce-parent-throughput",
            "--parent-target-workers",
            "1",
            "--parent-min-ready-suggestions",
            "1",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Workboard agent claim gate: PASS" in out
    assert "parent throughput: 1/1 workers" in out


def test_gate_parent_throughput_json_fail_payload(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=parent; parent=none; scope=thomas/agent; task=coord lane",
        active_tasks_block="- task_id=coord-lane; agent=Codex 3; scope=thomas/agent; summary=coord lane; status=active",
        up_for_grabs_block="- task_id=server-lane; scope=thomas/server/routes; summary=server lane; reported_by=bot",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 3")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--enforce-parent-throughput",
            "--parent-target-workers",
            "1",
            "--parent-min-ready-suggestions",
            "1",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    parent_payload = dict(payload.get("parent_throughput") or {})
    assert parent_payload.get("applied") is True
    assert int(parent_payload.get("ready_suggestion_count") or 0) == 1
    assert int(parent_payload.get("required_worker_count") or 0) == 1
