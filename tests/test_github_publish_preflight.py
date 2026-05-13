from __future__ import annotations

from pathlib import Path

import scripts.forge.publish.preflight as mod


def test_blocked_tracked_files_detected() -> None:
    tracked = ["README.md", ".env", "keys/prod.pem", "src/app.py"]
    violations = mod._check_blocked_tracked_files(tracked)
    assert ".env" in violations
    assert "keys/prod.pem" in violations


def test_scan_for_live_secrets_ignores_placeholders(tmp_path: Path) -> None:
    repo = tmp_path
    src = repo / "thomas" / "server"
    src.mkdir(parents=True)

    safe_file = src / "safe.py"
    safe_file.write_text(
        'TOKEN = "sk-EXAMPLEPLACEHOLDERTOKEN1234567890"\n',
        encoding="utf-8",
    )

    risky_file = src / "risky.py"
    risky_file.write_text(
        'TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"\n',
        encoding="utf-8",
    )

    findings = mod._scan_for_live_secrets(
        repo,
        [
            "thomas/server/safe.py",
            "thomas/server/risky.py",
        ],
    )

    assert any(item["file"] == "thomas/server/risky.py" for item in findings)
    assert not any(item["file"] == "thomas/server/safe.py" for item in findings)


def test_toml_safety_detects_unsafe_prod_config(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "thomas.prod.toml").write_text(
        """
[server]
access_mode = "remote"
api_token = "live-token"
allow_unauthenticated_version = true

[tools]
allow_shell = true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    errors = mod._check_toml_safety(repo)
    assert any("access_mode" in item for item in errors)
    assert any("allow_shell" in item for item in errors)
    assert any("api_token" in item for item in errors)


def test_run_optional_deep_checks_includes_claim_integrity(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, cwd=None, capture_output=None, text=None):  # type: ignore[no-untyped-def]
        commands.append(list(cmd))
        return _Proc()

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    failures = mod._run_optional_deep_checks(tmp_path)

    assert failures == []
    assert any(len(command) >= 2 and command[1] == "scripts/forge/gates/claim_integrity.py" for command in commands)
    assert any(
        len(command) >= 2 and command[1] == "scripts/check_repo_hygiene.py" and "--strict" in command
        for command in commands
    )
