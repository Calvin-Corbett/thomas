from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import scripts.workboard_claim_ops as ops
import scripts.workboard_claim_utils as utils


def _write_workboard(tmp_path: Path) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            "Use this section to announce active ownership and prevent conflicting edits.\n"
            "Claim format:\n"
            "`- \\`agent=<id>; name=<callsign>; role=<solo|parent|worker>; parent=<id|none>; scope=<path[,path...]>; task=<short text>\\``\n\n"
            "- none\n\n"
            "## Active Tasks\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; agent=<id>; scope=<path[,path...]>; summary=<short text>; status=<active|blocked>\\``\n\n"
            "- none\n\n"
            "## Issues / Blockers\n\n"
            "Issue format:\n"
            "`- \\`issue_id=<id>; task_id=<task_id>; reporter=<id>; owner=<id|unassigned>; state=<open|triaged|resolved>; summary=<short text>\\``\n\n"
            "- none\n\n"
            "## Up For Grabs\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; scope=<path[,path...]>; summary=<short text>; reported_by=<id>\\``\n\n"
            "- none\n"
        ),
        encoding="utf-8",
    )
    return path


def test_presence_gate_fails_closed_when_backend_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(utils, "agent_presence", None)

    ok, message = utils._presence_gate(
        workboard_path=tmp_path / "WORKBOARD.md",
        purpose="workboard_claim",
        agent="codex",
        requested_scope="src",
    )

    assert ok is False
    assert "presence gate unavailable" in message


def test_presence_gate_fails_closed_when_backend_raises(tmp_path: Path, monkeypatch) -> None:
    def _raise(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        utils,
        "agent_presence",
        SimpleNamespace(repo_root=lambda: tmp_path, evaluate_soft_gate=_raise),
    )

    ok, message = utils._presence_gate(
        workboard_path=tmp_path / "WORKBOARD.md",
        purpose="workboard_claim",
        agent="codex",
        requested_scope="src",
    )

    assert ok is False
    assert "presence gate failed: boom" in message


def test_claim_aborts_when_presence_gate_fails_closed(tmp_path: Path, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setattr(ops, "_presence_gate", lambda **_: (False, "presence gate failed: boom"))

    ok, message = ops.claim(
        workboard,
        agent="Codex Script",
        scope="scripts/workboard_claim_ops.py",
        task="script import claim",
    )

    assert ok is False
    assert message == "presence gate failed: boom"
    assert "agent=Codex Script;" not in workboard.read_text(encoding="utf-8")
