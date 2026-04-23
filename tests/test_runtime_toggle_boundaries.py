from __future__ import annotations

import json
import sys
from pathlib import Path

import scripts.check_commit_growth_guard as growth_guard
import scripts.check_deletions as deletion_guard
import scripts.check_monolith_filename_guard as monolith_filename_guard
import scripts.check_monolith_guard as monolith_guard
import scripts.check_workboard_agent_claim as agent_claim_gate
import scripts.check_workboard_changed_files as changed_files_gate


def _write_workboard(tmp_path: Path, claims_block: str) -> Path:
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
        "- task_id=app-lane; agent=Codex; scope=thomas/server/app.py; summary=app lane; status=active\n\n"
        "## Issues / Blockers\n\n"
        "Issue format:\n"
        "`- \\`issue_id=<id>; task_id=<task_id>; reporter=<id>; owner=<id|unassigned>; state=<open|triaged|resolved>; summary=<short text>\\``\n\n"
        "- none\n\n"
        "## Up For Grabs\n\n"
        "Task format:\n"
        "`- \\`task_id=<id>; scope=<path[,path...]>; summary=<short text>; reported_by=<id>\\``\n\n"
        "- none\n"
    )
    path = tmp_path / "WORKBOARD.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_growth_guard_still_runs_when_runtime_toggle_is_disabled(monkeypatch, capsys) -> None:
    monkeypatch.setattr(growth_guard, "_runtime_protection_disabled", lambda: True)
    monkeypatch.setattr(growth_guard, "_staged_files", lambda _repo_root: ["thomas/server/app.py"])
    monkeypatch.setattr(growth_guard, "_working_tree_lines", lambda _repo_root, _rel: 500)
    monkeypatch.setattr(growth_guard, "_head_lines", lambda _repo_root, _rel: 100)

    rc = growth_guard.run(Path.cwd(), max_growth=10, json_output=True)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["violations"][0]["path"] == "thomas/server/app.py"


def test_deletion_guard_still_runs_when_runtime_toggle_is_disabled(monkeypatch, capsys) -> None:
    monkeypatch.setattr(deletion_guard, "_runtime_protection_disabled", lambda: True)
    monkeypatch.setattr(deletion_guard, "_git_staged_name_status", lambda _repo_root: ["D\tthomas/agent/loop.py"])
    monkeypatch.setattr(deletion_guard, "_load_deletion_records", lambda _record_dir: (set(), []))

    rc = deletion_guard.run(["--staged-only", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "thomas/agent/loop.py" in payload["violations"]


def test_monolith_filename_guard_still_runs_when_runtime_toggle_is_disabled(monkeypatch, capsys) -> None:
    monkeypatch.setattr(monolith_filename_guard, "_runtime_protection_disabled", lambda: True)
    monkeypatch.setattr(
        monolith_filename_guard,
        "_scan",
        lambda _repo_root, staged_only: [
            {"path": "thomas/server/app.part01.py", "reason": "legacy split filename pattern"}
        ],
    )

    rc = monolith_filename_guard.run(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["violations"][0]["path"] == "thomas/server/app.part01.py"


def test_monolith_guard_still_runs_when_runtime_toggle_is_disabled(monkeypatch, capsys) -> None:
    monkeypatch.setattr(monolith_guard, "_runtime_protection_disabled", lambda: True)
    monkeypatch.setattr(
        monolith_guard,
        "run_guard",
        lambda *_args, **_kwargs: {
            "ok": False,
            "repo_root": str(Path.cwd()),
            "baseline_path": "docs/monolith_guard_baseline.json",
            "scan_roots": ["thomas"],
            "violations": [
                {
                    "path": "thomas/server/app.py",
                    "lines": 1500,
                    "hard_limit": 1200,
                    "reason": "exceeds hard limit",
                }
            ],
            "measured_count": 1,
            "growth_context": {},
        },
    )
    monkeypatch.setattr(sys, "argv", ["check_monolith_guard.py", "--json"])

    rc = monolith_guard.main()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["violations"][0]["path"] == "thomas/server/app.py"


def test_workboard_changed_files_still_runs_when_runtime_toggle_is_disabled(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex; name=Codex; role=solo; parent=none; scope=thomas/server/app.py; task=app lane",
    )
    monkeypatch.setattr(changed_files_gate, "_runtime_protection_disabled", lambda: True)

    rc = changed_files_gate.run(["--workboard", str(workboard), "--file", "thomas/agent/loop.py", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["unclaimed_files"] == ["thomas/agent/loop.py"]


def test_workboard_agent_claim_still_runs_when_runtime_toggle_is_disabled(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex; name=Codex; role=solo; parent=none; scope=thomas/server/app.py; task=app lane",
    )
    monkeypatch.setattr(agent_claim_gate, "_runtime_protection_disabled", lambda: True)
    monkeypatch.setattr(agent_claim_gate, "_staged_files", lambda: ["thomas/agent/loop.py"])

    rc = agent_claim_gate.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Codex",
            "--enforce-staged-scope",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "outside claimed scope" in payload["error"].lower()
