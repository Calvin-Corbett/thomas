from __future__ import annotations

import json
import subprocess
from pathlib import Path

import scripts.check_bulk_commit_guard as bulk_guard
import scripts.check_commit_growth_guard as growth_guard
import scripts.check_monolith_filename_guard as filename_guard
import scripts.check_monolith_guard as monolith_guard
import scripts.validate_agent_changes as validate_agent_changes


def test_monolith_filename_staged_scan_checks_index_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(filename_guard, "_git_changed_files", lambda _repo_root: ["thomas/probe_part01.css"])

    violations = filename_guard._run_staged_scan(tmp_path)

    assert violations == [
        {
            "path": "thomas/probe_part01.css",
            "reason": "legacy split filename pattern",
        }
    ]


def test_commit_growth_uses_staged_blob_lines(monkeypatch, capsys) -> None:
    monkeypatch.setattr(growth_guard, "_staged_files", lambda _repo_root: ["thomas/big_new.py"])
    monkeypatch.setattr(growth_guard, "_staged_lines", lambda _repo_root, _rel: 301)
    monkeypatch.setattr(growth_guard, "_head_lines", lambda _repo_root, _rel: 0)

    rc = growth_guard.run(Path.cwd(), max_growth=300, json_output=True)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["violations"][0]["path"] == "thomas/big_new.py"
    assert payload["violations"][0]["growth"] == 301


def test_commit_growth_env_disable_fails_closed(monkeypatch, capsys) -> None:
    monkeypatch.setenv("THOMAS_COMMIT_GROWTH_GUARD_DISABLE", "1")

    rc = growth_guard.run(Path.cwd(), json_output=True)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "no longer accepted" in payload["violations"][0]["reason"]


def test_bulk_commit_env_disable_fails_closed(monkeypatch, capsys) -> None:
    monkeypatch.setenv("THOMAS_BULK_COMMIT_GUARD_DISABLE", "1")

    rc = bulk_guard.run(Path.cwd(), json_output=True)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "no longer accepted" in payload["error"]


def test_javascript_syntax_missing_node_fails_closed(monkeypatch) -> None:
    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError("node")

    monkeypatch.setattr(validate_agent_changes.subprocess, "run", fake_run)

    ok, errors = validate_agent_changes.check_javascript_syntax(["thomas/server/web/js/runtime/probe.js"])

    assert ok is False
    assert any("JavaScript Syntax Check Unavailable" in line for line in errors)


def test_javascript_syntax_timeout_fails_closed(monkeypatch) -> None:
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["node", "--check"], timeout=5)

    monkeypatch.setattr(validate_agent_changes.subprocess, "run", fake_run)

    ok, errors = validate_agent_changes.check_javascript_syntax(["thomas/server/web/js/runtime/probe.js"])

    assert ok is False
    assert any("JavaScript Syntax Check Timed Out" in line for line in errors)


def test_monolith_guard_checks_index_only_staged_blob(monkeypatch, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["."],
                "hard_limits": {"css": 1200},
                "allowed_large_files": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(monolith_guard, "_git_ref_exists", lambda _repo_root, _ref: True)
    monkeypatch.setattr(monolith_guard, "_git_staged_files", lambda _repo_root: {"thomas/probe_part01.css"})
    monkeypatch.setattr(monolith_guard, "_git_tracked_files", lambda _repo_root: {"thomas/probe_part01.css"})
    monkeypatch.setattr(monolith_guard, "_git_blob_text", lambda *_args, **_kwargs: ".x { color: red; }\n")

    result = monolith_guard.run_guard(tmp_path, baseline, staged_only=True)

    assert result["ok"] is False
    assert result["violations"][0]["path"] == "thomas/probe_part01.css"
    assert "legacy .partNN.ext" in result["violations"][0]["reason"]
