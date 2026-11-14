"""A push of landed commits needs no claim, and the claim gate still stops a commit without one.

Proves: scripts.crew.brief.push_claim, scripts.forge.gates.workboard_agent_claim.

2026-11-03: the pre-push run stopped with "no active workboard claim found for 'claude'". The push step now hands the
gate its sanctioned explicit fallback. Everything the gate protects is checked here against the real gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import scripts.crew.brief.push_claim as push_claim
import scripts.forge.gates.workboard_agent_claim as gate

CLEAN = (
    "# Thomas Workboard\n\n## Agent Claims (Active)\n\n{claims}\n\n## Active Tasks\n\n{tasks}\n\n"
    "## Issues / Blockers\n\n{issues}\n\n## Up For Grabs\n\n- none\n"
)
OTHER_CLAIM = "- agent=codex; scope=.; task=everything"
OTHER_TASK = "- task_id=t1; agent=codex; scope=.; summary=s; status=active"


def _board(tmp_path: Path, *, claims="- none", tasks="- none", issues="- none") -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(CLEAN.format(claims=claims, tasks=tasks, issues=issues), encoding="utf-8")
    return path


def _run(board: Path, env: dict[str, str], monkeypatch, capsys, staged=()) -> tuple[int, dict]:
    for key in (
        "AGENT_ID",
        "THOMAS_AGENT_ID",
        "THOMAS_AGENT_NAME",
        "CLAUDE_AGENT_ID",
        push_claim.FALLBACK_SCOPE_ENV,
        push_claim.FALLBACK_REASON_ENV,
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(gate, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(gate, "_staged_files", lambda: list(staged))
    code = gate.run(["--workboard", str(board), "--enforce-staged-scope", "--json"])
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_without_the_push_env_the_gate_demands_a_claim(tmp_path, monkeypatch, capsys) -> None:
    code, payload = _run(_board(tmp_path), {"AGENT_ID": "claude"}, monkeypatch, capsys)
    assert code == 1
    assert "no active workboard claim" in payload["error"]


def test_a_push_of_landed_commits_passes_with_no_claim(tmp_path, monkeypatch, capsys) -> None:
    env = push_claim.landed_push_env("claude", {})
    code, payload = _run(_board(tmp_path), env, monkeypatch, capsys)
    assert code == 0, payload
    assert payload["scope_source"] == "explicit_fallback"
    assert payload["fallback_reason"] == push_claim.PUSH_REASON


def test_a_staged_file_cannot_ride_on_the_push_env(tmp_path, monkeypatch, capsys) -> None:
    env = push_claim.landed_push_env("claude", {})
    code, payload = _run(_board(tmp_path), env, monkeypatch, capsys, staged=["thomas/agent/loop.py"])
    assert code == 1
    assert payload["staged_files_outside_scope"] == ["thomas/agent/loop.py"]


def test_another_agents_overlapping_claim_still_stops_the_push(tmp_path, monkeypatch, capsys) -> None:
    board = _board(tmp_path, claims=OTHER_CLAIM, tasks=OTHER_TASK)
    env = push_claim.landed_push_env("claude", {})
    code, payload = _run(board, env, monkeypatch, capsys)
    assert code == 1
    assert payload["conflicting_agents"] == ["codex"]


def test_an_unresolved_issue_owned_by_the_agent_still_stops_the_push(tmp_path, monkeypatch, capsys) -> None:
    issue = "- issue_id=i1; task_id=t1; reporter=codex; owner=claude; state=open; summary=broken"
    task = "- task_id=t1; agent=codex; scope=thomas; summary=s; status=blocked"
    board = _board(tmp_path, claims="- agent=codex; scope=thomas; task=s", tasks=task, issues=issue)
    env = push_claim.landed_push_env("claude", {})
    code, payload = _run(board, env, monkeypatch, capsys)
    assert code == 1
    assert payload["unresolved_issue_ids"] == ["i1"]


def test_a_push_needs_an_agent_id() -> None:
    with pytest.raises(ValueError):
        push_claim.landed_push_env("  ", {})
