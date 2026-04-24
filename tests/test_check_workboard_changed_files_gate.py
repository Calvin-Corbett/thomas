from __future__ import annotations

import json
from pathlib import Path

import scripts.check_workboard_changed_files as mod


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
        "`- \\`agent=<id>; name=<callsign>; role=<solo|parent|worker>; parent=<id|none>; scope=<path[,path...]>; task=<short text>\\``\n\n"
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


def test_changed_files_gate_passes_when_file_is_claimed(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=solo; parent=none; scope=thomas/cli/main.py; task=main lane",
        active_tasks_block="- task_id=main-lane; agent=Codex 3; scope=thomas/cli/main.py; summary=main lane; status=active",
    )

    rc = mod.run(["--workboard", str(workboard), "--file", "thomas/cli/main.py"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Workboard changed-files gate: PASS" in out


def test_changed_files_gate_passes_for_literal_bracket_path(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=solo; parent=none; scope=thomas/server/web/js/[locale]/view.mjs; task=locale page",
        active_tasks_block=(
            "- task_id=locale-page; agent=Codex 3; scope=thomas/server/web/js/[locale]/view.mjs; "
            "summary=locale page; status=active"
        ),
    )

    rc = mod.run(["--workboard", str(workboard), "--file", "thomas/server/web/js/[locale]/view.mjs"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Workboard changed-files gate: PASS" in out


def test_changed_files_gate_fails_for_unclaimed_file(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=solo; parent=none; scope=thomas/cli/main.py; task=main lane",
        active_tasks_block="- task_id=main-lane; agent=Codex 3; scope=thomas/cli/main.py; summary=main lane; status=active",
    )

    rc = mod.run(["--workboard", str(workboard), "--file", "thomas/agent/loop.py"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "Workboard changed-files gate: FAIL" in out
    assert "thomas/agent/loop.py" in out


def test_changed_files_gate_ignores_workboard_file_by_default(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path, "- none")

    rc = mod.run(["--workboard", str(workboard), "--file", "plans/thomas/WORKBOARD.md"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Workboard changed-files gate: PASS" in out


def test_changed_files_gate_json_fail_payload(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=solo; parent=none; scope=thomas/cli/main.py; task=main lane",
        active_tasks_block="- task_id=main-lane; agent=Codex 3; scope=thomas/cli/main.py; summary=main lane; status=active",
    )

    rc = mod.run(["--workboard", str(workboard), "--file", "thomas/agent/loop.py", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["gate"] == "workboard_changed_files"
    assert payload["unclaimed_file_count"] == 1
    assert payload["unclaimed_files"] == ["thomas/agent/loop.py"]


def test_changed_files_gate_reports_invalid_workboard(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=solo; parent=none; task=broken claim",
        active_tasks_block="- none",
    )

    rc = mod.run(["--workboard", str(workboard), "--file", "thomas/cli/main.py", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "workboard claims invalid"
    assert any("missing required field(s): scope" in item for item in payload.get("violations") or [])


def test_changed_files_gate_can_require_identity_metadata(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/main.py; task=main lane",
        active_tasks_block="- task_id=main-lane; agent=Codex 3; scope=thomas/cli/main.py; summary=main lane; status=active",
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--file",
            "thomas/cli/main.py",
            "--require-identity-metadata",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["require_identity_metadata"] is True
    assert any("missing required field(s): name, role, parent" in item for item in payload.get("violations") or [])


def test_changed_files_gate_fails_when_changed_file_count_exceeds_max(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=solo; parent=none; scope=thomas/; task=bulk lane",
        active_tasks_block="- task_id=bulk-lane; agent=Codex 3; scope=thomas/; summary=bulk lane; status=active",
    )

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--file",
            "thomas/a.py,thomas/b.py,thomas/c.py",
            "--max-changed-files",
            "2",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["changed_file_count"] == 3
    assert payload["max_changed_files"] == 2
    assert "exceeds max 2" in payload["error"]


def test_changed_files_gate_allows_bulk_override_env(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=solo; parent=none; scope=thomas/; task=bulk lane",
        active_tasks_block="- task_id=bulk-lane; agent=Codex 3; scope=thomas/; summary=bulk lane; status=active",
    )
    monkeypatch.setenv("THOMAS_ALLOW_BULK_CHANGED_FILES", "1")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--file",
            "thomas/a.py,thomas/b.py,thomas/c.py",
            "--max-changed-files",
            "2",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["bulk_override"] is True
    assert payload["changed_file_count"] == 3


def test_changed_files_gate_accepts_explicit_fallback_scope(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=solo; parent=none; scope=docs/note.md; task=docs lane",
        active_tasks_block="- task_id=docs-lane; agent=Codex 3; scope=docs/note.md; summary=docs lane; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")
    monkeypatch.setenv("THOMAS_WORKBOARD_SCOPE_FALLBACK", "thomas/cli/main.py")
    monkeypatch.setenv("THOMAS_WORKBOARD_SCOPE_FALLBACK_REASON", "user approved scoped fallback")

    rc = mod.run(["--workboard", str(workboard), "--file", "thomas/cli/main.py", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["fallback_scope_count"] == 1
    assert payload["owner_by_file"] == {"thomas/cli/main.py": "Codex 2"}


def test_changed_files_gate_rejects_fallback_conflict_with_claimed_file(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=solo; parent=none; scope=thomas/cli/main.py; task=main lane",
        active_tasks_block="- task_id=main-lane; agent=Codex 3; scope=thomas/cli/main.py; summary=main lane; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")
    monkeypatch.setenv("THOMAS_WORKBOARD_SCOPE_FALLBACK", "thomas/cli/main.py")
    monkeypatch.setenv("THOMAS_WORKBOARD_SCOPE_FALLBACK_REASON", "user approved scoped fallback")

    rc = mod.run(["--workboard", str(workboard), "--file", "thomas/cli/main.py", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["fallback_conflict_count"] == 1
    assert payload["fallback_conflicts"][0]["owners"] == ["Codex 3"]


def test_changed_files_gate_rejects_explicit_fallback_without_reason(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; name=Prime; role=solo; parent=none; scope=docs/note.md; task=docs lane",
        active_tasks_block="- task_id=docs-lane; agent=Codex 3; scope=docs/note.md; summary=docs lane; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")
    monkeypatch.setenv("THOMAS_WORKBOARD_SCOPE_FALLBACK", "thomas/cli/main.py")

    rc = mod.run(["--workboard", str(workboard), "--file", "thomas/cli/main.py", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["scope_source"] == "explicit_fallback"
    assert "requires THOMAS_WORKBOARD_SCOPE_FALLBACK_REASON" in payload["error"]
