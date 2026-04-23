from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import scripts.push_guarded as mod


@pytest.fixture(autouse=True)
def _presence_gate_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        mod.agent_presence, "evaluate_soft_gate", lambda **_: {"ok": True, "warnings": [], "conflicts": []}
    )


def test_fails_when_skip_reason_missing_for_dirty_worktree(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_git_status_porcelain", lambda _repo: [" M thomas/cli/main.py"])

    rc = mod.run(["--dry-run"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "reason is required when SKIP hooks are used" in out


def test_rejects_no_verify_passthrough(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_git_status_porcelain", lambda _repo: [])

    rc = mod.run(["--", "--no-verify"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "Do not pass --no-verify" in out


def test_dry_run_json_includes_audited_skip_payload(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_git_status_porcelain", lambda _repo: [" M thomas/cli/main.py"])
    monkeypatch.setenv("AGENT_ID", "Codex 1")

    rc = mod.run(
        [
            "--reason",
            "Scoped push for dirty repo state.",
            "--dry-run",
            "--json",
            "origin",
            "master",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["command"] == ["git", "push", "origin", "master"]
    assert payload["skip_hooks"] == ["thomas-repo-clean-worktree-gate"]
    assert payload["agent"] == "Codex 1"
    assert payload["reason"] == "Scoped push for dirty repo state."


def test_executes_git_push_with_skip_env(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_git_status_porcelain", lambda _repo: [" M thomas/cli/main.py"])
    monkeypatch.setattr(mod, "_resolve_agent", lambda _agent: "Codex 1")
    captured: dict[str, object] = {}

    def _fake_run_push(repo_root, command, env):
        captured["repo_root"] = str(repo_root)
        captured["command"] = list(command)
        captured["skip"] = env.get("SKIP")
        captured["reason"] = env.get("THOMAS_SKIP_REASON")
        captured["agent"] = env.get("AGENT_ID")
        return SimpleNamespace(returncode=0, stdout="push-ok\n", stderr="")

    monkeypatch.setattr(mod, "_run_push_command", _fake_run_push)

    rc = mod.run(["--reason", "Scoped push for dirty repo state.", "origin", "master"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "push-ok" in out
    assert captured["command"] == ["git", "push", "origin", "master"]
    assert captured["skip"] == "thomas-repo-clean-worktree-gate"
    assert captured["reason"] == "Scoped push for dirty repo state."
    assert captured["agent"] == "Codex 1"


def test_fails_for_broad_skip_token(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_git_status_porcelain", lambda _repo: [])

    rc = mod.run(
        [
            "--skip-hook",
            "*",
            "--reason",
            "Scoped push for dirty repo state.",
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "broad skip token is not allowed" in out


def test_fails_when_presence_gate_requires_override(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_git_status_porcelain", lambda _repo: [])
    monkeypatch.setattr(
        mod.agent_presence,
        "evaluate_soft_gate",
        lambda **_: {"ok": False, "message": "presence gate requires override"},
    )

    rc = mod.run(["--dry-run"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "presence gate requires override" in out
