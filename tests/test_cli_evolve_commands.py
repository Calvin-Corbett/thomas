from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.evolve import evolve
from thomas.upgrade import evolve as evolve_runtime


def _seed_repo(root: Path) -> None:
    (root / "thomas").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
    (root / "thomas" / "__init__.py").write_text('__version__ = "0.0.0"\n', encoding="utf-8")
    (root / "tests" / "test_architecture.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")


def test_evolve_init_and_status(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    runner = CliRunner()
    init_result = runner.invoke(
        evolve,
        [
            "init",
            "--repo-root",
            str(tmp_path),
            "--objective",
            "Improve Thomas reliability",
            "--verify-cmd",
            "python -m pytest tests/test_architecture.py -q",
        ],
    )
    assert init_result.exit_code == 0, init_result.output
    assert (tmp_path / ".thomas" / "evolve" / "charter.json").exists()
    assert (tmp_path / ".thomas" / "evolve" / "charter.md").exists()

    status_result = runner.invoke(evolve, ["status", "--repo-root", str(tmp_path), "--json"])
    assert status_result.exit_code == 0, status_result.output
    payload = json.loads(status_result.output)
    assert payload["initialized"] is True
    assert payload["charter"]["objective"] == "Improve Thomas reliability"
    assert payload["run_count"] == 0


def test_evolve_run_and_promote(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    runner = CliRunner()

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            return {
                "command": "chat",
                "returncode": 0,
                "stdout_tail": "updated",
                "stderr_tail": "",
                "timed_out": False,
            }
        return {
            "command": "verify",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)

    run_result = runner.invoke(evolve, ["run", "--repo-root", str(tmp_path), "--goal", "Tighten Thomas UX", "--json"])
    assert run_result.exit_code == 0, run_result.output
    payload = json.loads(run_result.output)
    session = payload["session"]
    assert session["status"] == "ready"
    assert "thomas/__init__.py" in session["changed_files"]
    assert session["promotable"] is True

    promote_result = runner.invoke(evolve, ["promote", "--repo-root", str(tmp_path), "--json"])
    assert promote_result.exit_code == 0, promote_result.output
    promote_payload = json.loads(promote_result.output)
    assert promote_payload["session"]["status"] == "promoted"
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.1.0"'
