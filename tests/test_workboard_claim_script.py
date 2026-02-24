from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import scripts.check_workboard_claims as gate
import scripts.workboard_claim as mod


def _write_workboard(
    tmp_path: Path,
    claims_block: str = "- none",
    *,
    active_tasks_block: str = "- none",
    issues_block: str = "- none",
    up_for_grabs_block: str = "- none",
) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Current Priorities\n\n"
            "- Placeholder\n\n"
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
            f"{up_for_grabs_block}\n\n"
            "## Supporting Docs (Not Plan Sources)\n\n"
            "- docs/PROJECT_SCOPE.md\n"
        ),
        encoding="utf-8",
    )
    return path


def test_claim_adds_entry_and_removes_none_placeholder(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--claim",
            "--agent",
            "Codex 3",
            "--scope",
            "thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py,tests/prompt_pack",
            "--task",
            "dom snapshot runtime fix",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")
    lines = text.splitlines()
    claim_start, claim_end = mod._find_claim_section(lines)
    active_start, active_end = mod._find_active_tasks_section(lines)
    claim_block = "\n".join(lines[claim_start:claim_end])
    active_block = "\n".join(lines[active_start:active_end])

    assert rc == 0
    assert "Workboard claim tool: PASS" in out
    assert "- none" not in claim_block
    assert "- none" not in active_block
    assert "agent=Codex 3;" in text
    assert gate.evaluate(workboard) == []


def test_claim_updates_existing_agent_entry(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser; task=old task",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/cli/commands/browser; summary=old task; status=active",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--claim",
            "--agent",
            "codex 3",
            "--scope",
            "thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py",
            "--task",
            "new task",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")
    lines = text.splitlines()
    claim_start, claim_end = mod._find_claim_section(lines)
    active_start, active_end = mod._find_active_tasks_section(lines)
    claim_block = "\n".join(lines[claim_start:claim_end])
    active_block = "\n".join(lines[active_start:active_end])

    assert rc == 0
    assert "updated claim for `codex 3`" in out
    assert claim_block.count("agent=codex 3;") == 1
    assert active_block.count("agent=codex 3;") == 1
    assert "task=new task" in text
    assert gate.evaluate(workboard) == []


def test_release_restores_none_when_last_claim_removed(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot",
        active_tasks_block="- task_id=codex-3-task; agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot; status=active",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release",
            "--agent",
            "Codex 3",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "released claim for `Codex 3`" in out
    assert "- none" in text
    assert "agent=Codex 3;" not in text
    assert gate.evaluate(workboard) == []


def test_release_fails_when_agent_claim_missing(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path, "- none")
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release",
            "--agent",
            "Codex 9",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "no active claim found for `Codex 9`" in out


def test_list_shows_active_claims_only(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "\n".join(
            [
                "- none",
                "- agent=Codex 1; scope=thomas/cli/pack_bridge.py; task=no-op parity",
            ]
        ),
    )
    rc = mod.run(["--workboard", str(workboard), "--list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Workboard claim tool: PASS" in out
    assert "agent=Codex 1;" in out
    assert "- none" not in out


def test_claim_infers_agent_and_branch_task_when_omitted(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("THOMAS_AGENT_NAME", "Codex Auto")
    monkeypatch.setattr(mod, "_detect_branch_name", lambda: "feature/workboard-claims")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--claim",
            "--scope",
            "thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "Workboard claim tool: PASS" in out
    assert "agent=Codex Auto;" in text
    assert "task=branch feature/workboard-claims" in text
    assert gate.evaluate(workboard) == []


def test_release_infers_agent_from_environment(tmp_path: Path, capsys, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex Auto; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot",
        active_tasks_block="- task_id=codex-auto-task; agent=Codex Auto; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot; status=active",
    )
    monkeypatch.setenv("THOMAS_AGENT_NAME", "Codex Auto")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "released claim for `Codex Auto`" in out
    assert "- none" in text
    assert gate.evaluate(workboard) == []


def test_release_requires_agent_when_no_default_available(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    workboard = _write_workboard(tmp_path, "- none")
    monkeypatch.delenv("THOMAS_AGENT_NAME", raising=False)
    monkeypatch.delenv("CODEX_AGENT_NAME", raising=False)
    monkeypatch.delenv("AGENT_NAME", raising=False)
    monkeypatch.setattr(mod, "_detect_agent_default", lambda: None)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--release",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "agent is required" in out


def test_claim_prefers_explicit_agent_id_env_when_agent_omitted(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("AGENT_ID", "Codex ID")
    monkeypatch.delenv("THOMAS_AGENT_NAME", raising=False)
    monkeypatch.delenv("CODEX_AGENT_NAME", raising=False)
    monkeypatch.delenv("AGENT_NAME", raising=False)
    monkeypatch.setattr(mod, "_detect_branch_name", lambda: "feature/workboard-claims")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--claim",
            "--scope",
            "thomas/cli/main.py",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "Workboard claim tool: PASS" in out
    assert "agent=Codex ID;" in text


def test_claim_and_release_use_file_lock(tmp_path: Path, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    lock_calls: list[Path] = []

    @contextmanager
    def _fake_lock(lock_file: Path, timeout: float = 10.0):
        lock_calls.append(lock_file)
        yield

    monkeypatch.setattr(mod, "_file_lock", _fake_lock)

    ok_claim, _ = mod.claim(
        workboard,
        agent="Codex Lock",
        scope="thomas/cli/main.py",
        task="lock claim",
    )
    ok_release, _ = mod.release(workboard, agent="Codex Lock")

    assert ok_claim is True
    assert ok_release is True
    assert lock_calls == [mod.LOCK_FILE, mod.LOCK_FILE]
