from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.research import research
from thomas.library import research_runner
from thomas.library.research_store import load_research_config, resolve_research_root


def test_research_init_and_status(tmp_path: Path) -> None:
    runner = CliRunner()

    init_result = runner.invoke(
        research,
        [
            "init",
            "--repo-root",
            str(tmp_path),
            "--objective",
            "Improve benchmark accuracy",
            "--metric-name",
            "val_bpb",
            "--metric-goal",
            "minimize",
            "--editable-path",
            "train.py",
            "--eval-cmd",
            "python eval.py",
            "--metric-path",
            "artifacts/metrics.json",
            "--metric-key",
            "metrics.val_bpb",
        ],
    )

    assert init_result.exit_code == 0, init_result.output
    research_root = resolve_research_root(tmp_path)
    assert (research_root / "config.json").exists()
    assert (research_root / "program.md").exists()

    status_result = runner.invoke(research, ["status", "--repo-root", str(tmp_path)])
    assert status_result.exit_code == 0, status_result.output
    assert "Improve benchmark accuracy" in status_result.output
    assert "val_bpb (minimize)" in status_result.output


def test_research_run_blocks_out_of_scope_changes(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    init_result = runner.invoke(
        research,
        [
            "init",
            "--repo-root",
            str(tmp_path),
            "--objective",
            "Keep edits inside train.py",
            "--metric-name",
            "score",
            "--editable-path",
            "train.py",
        ],
    )
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.setattr(research_runner, "_git_changed_files", lambda _root: ["train.py", "README.md"])
    monkeypatch.setattr(research_runner, "_git_head", lambda _root: "deadbeef")
    monkeypatch.setattr(research_runner, "_git_diff_patch", lambda _root: "diff --git a/README.md b/README.md\n")

    run_result = runner.invoke(
        research,
        ["run", "--repo-root", str(tmp_path), "--label", "scope-check", "--metric-value", "0.91", "--json"],
    )
    assert run_result.exit_code == 0, run_result.output
    payload = json.loads(run_result.output)
    assert payload["run"]["status"] == "blocked"
    assert payload["run"]["verdict"] == "blocked_scope"
    assert payload["run"]["disallowed_files"] == ["README.md"]


def test_research_accept_promotes_baseline_and_scoreboard(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    init_result = runner.invoke(
        research,
        [
            "init",
            "--repo-root",
            str(tmp_path),
            "--objective",
            "Raise accuracy",
            "--metric-name",
            "accuracy",
            "--metric-goal",
            "maximize",
            "--baseline-value",
            "0.8",
            "--editable-path",
            "src",
        ],
    )
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.setattr(research_runner, "_git_changed_files", lambda _root: ["src/model.py"])
    monkeypatch.setattr(research_runner, "_git_head", lambda _root: "cafebabe")
    monkeypatch.setattr(research_runner, "_git_diff_patch", lambda _root: "diff --git a/src/model.py b/src/model.py\n")

    run_result = runner.invoke(
        research,
        ["run", "--repo-root", str(tmp_path), "--label", "candidate-a", "--metric-value", "0.91", "--json"],
    )
    assert run_result.exit_code == 0, run_result.output
    run_payload = json.loads(run_result.output)
    run_id = run_payload["run"]["run_id"]
    assert run_payload["run"]["verdict"] == "candidate_promote"

    accept_result = runner.invoke(
        research,
        ["accept", run_id, "--repo-root", str(tmp_path), "--reason", "beats the frontier", "--json"],
    )
    assert accept_result.exit_code == 0, accept_result.output
    accept_payload = json.loads(accept_result.output)
    assert accept_payload["run"]["decision"] == "accepted"
    assert accept_payload["config"]["baseline_value"] == 0.91

    config = load_research_config(tmp_path)
    assert config.baseline_value == 0.91

    scoreboard_result = runner.invoke(research, ["scoreboard", "--repo-root", str(tmp_path), "--json"])
    assert scoreboard_result.exit_code == 0, scoreboard_result.output
    scoreboard_payload = json.loads(scoreboard_result.output)
    assert scoreboard_payload["rows"][0]["run_id"] == run_id
    assert scoreboard_payload["rows"][0]["decision"] == "accepted"
