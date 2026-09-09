from __future__ import annotations

import json
from types import SimpleNamespace

import scripts.commit_guarded as mod
from scripts.breakglass_context import BREAKGLASS_CONTEXT_ENV


def test_commit_guarded_retries_with_contextual_breakglass(monkeypatch, capsys, tmp_path) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_command(repo_root, command, env):
        calls.append({"repo_root": str(repo_root), "command": list(command), "env": dict(env)})
        if "--no-verify" not in command:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=(
                    "Thomas Merge Readiness............................Failed\n"
                    "- uncommitted change budget exceeded: 1548 changed lines exceeds max_uncommitted_changed_lines=800\n"
                ),
            )
        return SimpleNamespace(returncode=0, stdout="commit-ok\n", stderr="")

    monkeypatch.setattr(mod, "_run_command", fake_run_command)

    rc = mod.run(
        [
            "--repo-root",
            str(tmp_path),
            "--agent",
            "codex-owner",
            "--ticket",
            "OPS-200",
            "--ai-recommendation",
            "This commit is large, but the files are related. I think it can continue after file-list review.",
            "-m",
            "Checkpoint",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Thomas commit blocker summary" in out
    assert len(calls) == 2
    retry = calls[1]
    assert "--no-verify" in retry["command"]
    retry_env = retry["env"]
    assert retry_env[mod.BREAKGLASS_ENV] == "1"
    assert retry_env[mod.BREAKGLASS_TICKET_ENV] == "OPS-200"
    payload = json.loads(retry_env[BREAKGLASS_CONTEXT_ENV])
    assert payload["title"] == "Thomas commit blocker"
    assert "1548 changed lines" in json.dumps(payload)


def test_commit_guarded_passes_model_guidance_to_breakglass_context(monkeypatch, capsys, tmp_path) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_command(repo_root, command, env):
        calls.append({"repo_root": str(repo_root), "command": list(command), "env": dict(env)})
        if "--no-verify" not in command:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=(
                    "Thomas Merge Readiness............................Failed\n"
                    "- uncommitted change budget exceeded: 1548 changed lines exceeds max_uncommitted_changed_lines=800\n"
                ),
            )
        return SimpleNamespace(returncode=0, stdout="commit-ok\n", stderr="")

    monkeypatch.setattr(mod, "_run_command", fake_run_command)

    guidance = json.dumps(
        {
            "recommendation": "This is 748 lines over the limit. Split it before committing.",
            "resolution_label": "Split commit",
            "resolution_prompt": "Split this work into two smaller commits and retry.",
            "issues": [
                {
                    "gate": "Thomas Merge Readiness",
                    "plain_reason": "The commit changes 1548 lines, but this guard allows 800.",
                    "impact": "A large commit is harder to review safely.",
                    "recommendation": "Split it unless everything must land together.",
                    "next_step": "Separate the UI change from unrelated cleanup.",
                }
            ],
        }
    )

    rc = mod.run(
        [
            "--repo-root",
            str(tmp_path),
            "--ticket",
            "OPS-201",
            "--ai-guidance-json",
            guidance,
            "-m",
            "Checkpoint",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "The commit changes 1548 lines" in out
    retry_env = calls[1]["env"]
    payload = json.loads(retry_env[BREAKGLASS_CONTEXT_ENV])
    assert payload["resolution_label"] == "Split commit"
    assert "two smaller commits" in payload["resolution_prompt"]
    assert payload["issues"][0]["plain_reason"] == "The commit changes 1548 lines, but this guard allows 800."


def test_commit_guarded_no_breakglass_reports_original_failure(monkeypatch, capsys, tmp_path) -> None:
    def fake_run_command(_repo_root, _command, _env):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Thomas Protected Files Gate................Failed\nYou modified 7 protected file(s):\n",
        )

    monkeypatch.setattr(mod, "_run_command", fake_run_command)

    rc = mod.run(["--repo-root", str(tmp_path), "--no-breakglass", "-m", "Checkpoint"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "Thomas commit blocker summary" in out
    assert "You modified 7 protected file(s)" in out
