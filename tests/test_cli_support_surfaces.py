from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

import thomas.cli.main_runtime_ops as cli_runtime_ops
from thomas.cli.main import cli
from thomas.observability.run_db import connect, ensure_schema


def _write_min_config(path: Path) -> Path:
    cfg = path / "thomas.toml"
    cfg.write_text(
        """
default_model = "local"

[memory]
root = "./runtime"

[models.local]
provider = "ollama"
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:7b"
""".strip(),
        encoding="utf-8",
    )
    return cfg


def test_cli_config_validate_json(tmp_path: Path) -> None:
    cfg = _write_min_config(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "config", "validate", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "summary" in payload
    assert payload["summary"]["error_count"] == 0, payload
    assert payload["config_path"] == str(cfg.resolve())


def test_cli_config_validate_ignores_unrelated_thomas_env(tmp_path: Path, monkeypatch) -> None:
    cfg = _write_min_config(tmp_path)
    monkeypatch.setenv("THOMAS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("THOMAS_SERVER_URL", "http://127.0.0.1:8080")
    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "config", "validate", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["summary"]["error_count"] == 0, payload


def test_cli_config_path_json(tmp_path: Path) -> None:
    cfg = _write_min_config(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "config", "path", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["config_path"] == str(cfg.resolve())
    assert payload["exists"] is True


def test_cli_status_json(tmp_path: Path) -> None:
    cfg = _write_min_config(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["config_path"] == str(cfg.resolve())
    assert payload["default_model"] == "local"
    assert payload["profile_count"] >= 1
    assert payload["summary"]["error_count"] == 0
    assert "worktree" in payload
    assert "worktree_clean" in payload
    if payload["worktree_clean"] is not None:
        summary = dict((payload.get("worktree") or {}).get("summary") or {})
        assert "staged_count" in summary
        assert "unstaged_count" in summary
        assert "untracked_count" in summary


def test_cli_library_group_help_surfaces_expected_subcommands(tmp_path: Path) -> None:
    cfg = _write_min_config(tmp_path)
    runner = CliRunner()
    root_help = runner.invoke(cli, ["-c", str(cfg), "--help"])
    assert root_help.exit_code == 0, root_help.output
    assert "library" in root_help.output

    library_help = runner.invoke(cli, ["-c", str(cfg), "library", "--help"])
    assert library_help.exit_code == 0, library_help.output
    for name in ("add", "curate", "list", "reindex", "show", "where"):
        assert name in library_help.output


def test_cli_config_validate_strict_exits_on_errors(tmp_path: Path) -> None:
    cfg = tmp_path / "thomas.toml"
    cfg.write_text(
        """
default_model = "cloud"

[memory]
root = "./runtime"

[server]
access_mode = "remote"

[models.cloud]
provider = "openai_compat"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
""".strip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "config", "validate", "--json", "--strict"])
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["summary"]["error_count"] >= 1


def test_cli_status_strict_exits_on_errors(tmp_path: Path) -> None:
    cfg = tmp_path / "thomas.toml"
    cfg.write_text(
        """
default_model = "cloud"

[memory]
root = "./runtime"

[server]
access_mode = "remote"

[models.cloud]
provider = "openai_compat"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "status", "--json", "--strict"])
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["summary"]["error_count"] >= 1


def test_cli_status_strict_worktree_exits_on_dirty(tmp_path: Path, monkeypatch) -> None:
    cfg = _write_min_config(tmp_path)
    monkeypatch.setattr(
        cli_runtime_ops,
        "git_status_porcelain_lines",
        lambda _repo_root: [" M thomas/core/config.py", "?? scratch/local.txt"],
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "status", "--json", "--strict-worktree"])
    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["worktree_clean"] is False
    summary = dict((payload.get("worktree") or {}).get("summary") or {})
    assert summary["unstaged_count"] == 1
    assert summary["untracked_count"] == 1


def test_cli_status_strict_worktree_passes_when_clean(tmp_path: Path, monkeypatch) -> None:
    cfg = _write_min_config(tmp_path)
    monkeypatch.setattr(cli_runtime_ops, "git_status_porcelain_lines", lambda _repo_root: [])
    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "status", "--json", "--strict-worktree"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["worktree_clean"] is True
    summary = dict((payload.get("worktree") or {}).get("summary") or {})
    assert summary["staged_count"] == 0
    assert summary["unstaged_count"] == 0
    assert summary["untracked_count"] == 0


def test_cli_repo_clean_json_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        cli_runtime_ops,
        "run_repo_cleanup",
        lambda **_: {
            "repo_root": "F:/DevHub/Thomas",
            "include_ignored": True,
            "patterns": [],
            "candidates": ["tmp_switch_test.py"],
            "removed": [],
            "failed": [],
            "_exit_code": 0,
        },
    )
    monkeypatch.setattr(cli_runtime_ops, "git_status_porcelain_lines", lambda _repo_root: [])

    runner = CliRunner()
    result = runner.invoke(cli, ["repo-clean", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["cleanup_summary"]["candidate_count"] == 1
    assert payload["cleanup_summary"]["removed_count"] == 0
    assert payload["worktree"]["summary"]["staged_count"] == 0
    assert payload["worktree"]["summary"]["unstaged_count"] == 0
    assert payload["worktree"]["summary"]["untracked_count"] == 0


def test_cli_repo_clean_strict_exits_on_dirty_worktree(monkeypatch) -> None:
    monkeypatch.setattr(
        cli_runtime_ops,
        "run_repo_cleanup",
        lambda **_: {
            "repo_root": "F:/DevHub/Thomas",
            "include_ignored": True,
            "patterns": [],
            "candidates": [],
            "removed": [],
            "failed": [],
            "_exit_code": 0,
        },
    )
    monkeypatch.setattr(
        cli_runtime_ops,
        "git_status_porcelain_lines",
        lambda _repo_root: [" M thomas/core/config.py", "?? scratch/local.txt"],
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["repo-clean", "--json", "--strict"])
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["cleanup_summary"]["failed_count"] == 0
    assert payload["worktree"]["summary"]["unstaged_count"] == 1
    assert payload["worktree"]["summary"]["untracked_count"] == 1


def test_cli_repo_clean_exits_on_cleanup_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        cli_runtime_ops,
        "run_repo_cleanup",
        lambda **_: {
            "repo_root": "F:/DevHub/Thomas",
            "include_ignored": True,
            "patterns": [],
            "candidates": ["tmp_switch_test.py"],
            "removed": [],
            "failed": [{"path": "tmp_switch_test.py", "error": "PermissionError"}],
            "_exit_code": 1,
        },
    )
    monkeypatch.setattr(cli_runtime_ops, "git_status_porcelain_lines", lambda _repo_root: [])

    runner = CliRunner()
    result = runner.invoke(cli, ["repo-clean", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["cleanup_summary"]["candidate_count"] == 1
    assert payload["cleanup_summary"]["failed_count"] == 1


def test_cli_onboarding_outcomes_json(tmp_path: Path) -> None:
    cfg = _write_min_config(tmp_path)
    db = tmp_path / "runs.sqlite3"
    ensure_schema(db)
    con = connect(db)
    try:
        con.execute(
            "INSERT OR REPLACE INTO runs(run_id, started_at, ok, meta_json, last_seq) VALUES (?, datetime('now'), ?, ?, ?)",
            ("r1", 1, "{}", 1),
        )
        con.execute(
            "INSERT INTO events(run_id, t_ms, seq, event_type, payload_json) VALUES (?, ?, ?, ?, ?)",
            ("r1", 1, 1, "onboarding.client.wizard.opened", '{"user_id":"u1"}'),
        )
        con.commit()
    finally:
        con.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-c", str(cfg), "onboarding-outcomes", "--db", str(db), "--days", "7", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["summary"]["events"] >= 1
    assert payload["summary"]["wizard_opened"] >= 1
    assert "completed_journeys_with_timing" in payload["summary"]
    assert "median_time_to_ready_seconds" in payload["summary"]
