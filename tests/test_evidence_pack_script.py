from __future__ import annotations

import json
import sys
from pathlib import Path

import scripts.evidence_pack as mod


def _py_cmd(code: str) -> str:
    exe = str(Path(sys.executable))
    return f'"{exe}" -c "{code}"'


def test_evidence_pack_success_writes_summary_and_logs(tmp_path: Path, capsys) -> None:
    rc = mod.run(
        [
            "--name",
            "quick-proof",
            "--output-root",
            str(tmp_path),
            "--command",
            _py_cmd("print('ok-proof')"),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["executed_count"] == 1
    pack_dir = Path(payload["output_dir"])
    assert pack_dir.exists()
    assert Path(payload["summary_path"]).exists()
    assert Path(payload["summary_markdown_path"]).exists()
    step = payload["steps"][0]
    assert Path(step["stdout_path"]).read_text(encoding="utf-8").strip() == "ok-proof"


def test_evidence_pack_stops_early_on_failure_by_default(tmp_path: Path, capsys) -> None:
    rc = mod.run(
        [
            "--name",
            "stop-early",
            "--output-root",
            str(tmp_path),
            "--command",
            _py_cmd("import sys; sys.exit(7)"),
            "--command",
            _py_cmd("print('should-not-run')"),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["command_count"] == 2
    assert payload["executed_count"] == 1
    assert payload["stopped_early"] is True


def test_evidence_pack_continue_on_fail_runs_all_steps(tmp_path: Path, capsys) -> None:
    rc = mod.run(
        [
            "--name",
            "continue-on-fail",
            "--output-root",
            str(tmp_path),
            "--continue-on-fail",
            "--command",
            _py_cmd("import sys; sys.stderr.write('boom\\n'); sys.exit(3)"),
            "--command",
            _py_cmd("print('second-ran')"),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["executed_count"] == 2
    assert payload["stopped_early"] is False
    assert payload["steps"][1]["ok"] is True
    assert "second-ran" in Path(payload["steps"][1]["stdout_path"]).read_text(encoding="utf-8")


def test_evidence_pack_requires_command(tmp_path: Path, capsys) -> None:
    rc = mod.run(
        [
            "--name",
            "missing-command",
            "--output-root",
            str(tmp_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "at least one --command is required" in payload["error"]


def test_evidence_pack_rejects_invalid_workdir(tmp_path: Path, capsys) -> None:
    bad_workdir = tmp_path / "not-a-dir"
    rc = mod.run(
        [
            "--name",
            "bad-workdir",
            "--output-root",
            str(tmp_path),
            "--workdir",
            str(bad_workdir),
            "--command",
            _py_cmd("print('x')"),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "invalid workdir:" in payload["error"]
