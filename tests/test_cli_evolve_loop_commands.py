"""CLI tests for the evolve loop commands: plan, loop, loop-status, approve, reject."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

import thomas.cli.commands.evolve as cli_evolve
from thomas.cli.commands.evolve import evolve
from thomas.forge.anvil.evolve_loop import EvolveLoopState, save_loop_state


def _scaffold(root: Path) -> None:
    thomas = root / "thomas"
    thomas.mkdir(parents=True, exist_ok=True)
    (thomas / "__init__.py").write_text("__version__ = '0.0.0'\n", encoding="utf-8")
    # An oversized file guarantees at least one refactor goal.
    (thomas / "big.py").write_text("\n".join(f"x_{i} = {i}" for i in range(1600)), encoding="utf-8")


def test_evolve_plan_lists_self_chosen_backlog(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    runner = CliRunner()
    result = runner.invoke(evolve, ["plan", "--repo-root", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] >= 1
    assert any(g["category"] == "refactor" for g in payload["goals"])


def test_evolve_json_output_is_console_encoding_safe(monkeypatch) -> None:
    captured = {}

    def cp1252_echo(text: str) -> None:
        text.encode("cp1252")
        captured["text"] = text

    monkeypatch.setattr(cli_evolve.click, "echo", cp1252_echo)

    cli_evolve._emit_json({"bad_char": "\ufffd", "plain": "ok"})

    assert "\\ufffd" in captured["text"]
    assert json.loads(captured["text"])["bad_char"] == "\ufffd"


def test_evolve_loop_command_wires_options(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def fake_run_loop(root, **kwargs):
        captured.update(kwargs)
        return {
            "status": "done",
            "posture": kwargs["posture"],
            "iteration": 1,
            "counters": {"promoted": 1, "held": 0, "rejected": 0, "failed": 0, "planned": 1},
            "pending_count": 0,
        }

    monkeypatch.setattr(cli_evolve, "run_evolve_loop", fake_run_loop)
    runner = CliRunner()
    result = runner.invoke(
        evolve,
        [
            "loop",
            "--repo-root",
            str(tmp_path),
            "--posture",
            "autonomous",
            "--focus",
            "hardening",
            "--max-iterations",
            "3",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["posture"] == "autonomous"
    assert captured["focus"] == "hardening"
    assert captured["max_iterations"] == 3
    assert "Evolve loop done" in result.output


def test_evolve_loop_status_reports_pending(tmp_path: Path) -> None:
    state = EvolveLoopState(status="done", posture="auto_safe")
    state.pending_approvals.append(
        {
            "id": "hold-abc123",
            "title": "Security hardening sweep",
            "category": "security",
            "risk_tier": "high",
            "status": "pending",
        }
    )
    save_loop_state(tmp_path, state)

    runner = CliRunner()
    result = runner.invoke(evolve, ["loop-status", "--repo-root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "hold-abc123" in result.output
    assert "Security hardening sweep" in result.output


def test_evolve_reject_marks_dismissed(tmp_path: Path) -> None:
    state = EvolveLoopState(status="done")
    state.pending_approvals.append(
        {"id": "hold-xyz", "title": "x", "category": "refactor", "risk_tier": "low", "status": "pending"}
    )
    save_loop_state(tmp_path, state)

    runner = CliRunner()
    result = runner.invoke(evolve, ["reject", "hold-xyz", "--repo-root", str(tmp_path), "--reason", "later"])
    assert result.exit_code == 0, result.output
    reloaded = cli_evolve.load_loop_state(tmp_path).to_dict()
    assert reloaded["pending_approvals"][0]["status"] == "rejected"


def test_evolve_plain_language_chat_command_is_not_registered() -> None:
    result = CliRunner().invoke(evolve, ["chat", "start evolving"])
    assert result.exit_code != 0
    assert "No such command 'chat'" in result.output
