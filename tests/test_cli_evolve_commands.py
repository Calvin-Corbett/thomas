from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from tests._cli_evolve_fakes import _seed_repo
from thomas.cli.commands.evolve import evolve
from thomas.forge.anvil import evolve as evolve_runtime
from thomas.forge.anvil.doppelganger import (
    get_paths,
)
from thomas.forge.anvil.refactor_pass import RefactorTarget, build_refactor_plan, build_refactor_prompt


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
            "--acceptance-check",
            "status-verifier-panel",
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
    assert payload["charter"]["acceptance_checks"] == ["evolve_status_verifier_panel"]
    assert payload["run_count"] == 0
    charter_markdown = (tmp_path / ".thomas" / "evolve" / "charter.md").read_text(encoding="utf-8")
    assert "## Acceptance Checks" in charter_markdown
    assert "`evolve_status_verifier_panel`" in charter_markdown


def test_evolve_corpus_cli_runs_locked_corpus(tmp_path: Path) -> None:
    _seed_repo(tmp_path)

    result = CliRunner().invoke(evolve, ["corpus", "--repo-root", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["case_count"] == 1
    assert payload["cases"][0]["case_id"] == "known_good_minimal"


def test_evolve_status_prints_verification_repair_summary(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    evolve_runtime.ensure_evolve_charter(tmp_path, overwrite=True)
    session_dir = tmp_path / ".thomas" / "evolve" / "sessions" / "semantic-repair"
    session_dir.mkdir(parents=True)
    (session_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": "semantic-repair",
                "status": "ready",
                "delta": {"changed_count": 1},
                "promotable": True,
                "promoted": False,
                "verification_repair_attempted": True,
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(evolve, ["status", "--repo-root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Verification repair: attempted" in result.output
    assert "Verification repair artifacts:" not in result.output


def test_evolve_status_prints_verification_repair_artifact_count(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    evolve_runtime.ensure_evolve_charter(tmp_path, overwrite=True)
    session_dir = tmp_path / ".thomas" / "evolve" / "sessions" / "semantic-repair-artifacts"
    artifact_dir = session_dir / "verification-repair"
    artifact_dir.mkdir(parents=True)
    artifact_path = artifact_dir / "failure-01.txt"
    artifact_path.write_text("stderr:\nmissing repair detail\n", encoding="utf-8")
    (session_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": "semantic-repair-artifacts",
                "status": "ready",
                "delta": {"changed_count": 1},
                "promotable": True,
                "promoted": False,
                "verification_repair_attempted": True,
                "verification_repair_artifacts": [{"path": str(artifact_path)}],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(evolve, ["status", "--repo-root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Verification repair: attempted" in result.output
    assert "Verification repair artifacts: 1" in result.output
    assert "Verification repair artifact: verification-repair/failure-01.txt" in result.output


def test_evolve_status_prints_verification_output_artifact_count(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    evolve_runtime.ensure_evolve_charter(tmp_path, overwrite=True)
    session_dir = tmp_path / ".thomas" / "evolve" / "sessions" / "verification-output-artifacts"
    output_dir = session_dir / "verification-output" / "initial"
    output_dir.mkdir(parents=True)
    stdout_path = output_dir / "01-acceptance.stdout.txt"
    stderr_path = output_dir / "01-acceptance.stderr.txt"
    stdout_path.write_text("full stdout\n", encoding="utf-8")
    stderr_path.write_text("full stderr\n", encoding="utf-8")
    (session_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": "verification-output-artifacts",
                "status": "ready",
                "delta": {"changed_count": 1},
                "promotable": True,
                "promoted": False,
                "verification": [
                    {
                        "source": "acceptance",
                        "returncode": 0,
                        "stdout_artifact": {"path": str(stdout_path), "bytes": 12, "sha256": "stdout"},
                        "stderr_artifact": {"path": str(stderr_path), "bytes": 12, "sha256": "stderr"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(evolve, ["status", "--repo-root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Verification output artifacts: 2" in result.output


def test_evolve_run_cli_skips_refactor_first_for_explicit_goal_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run_evolve_session(repo_root, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "session": {"session_id": "s1", "status": "ready", "delta": {"changed_count": 0}}}

    monkeypatch.setattr("thomas.cli.commands.evolve.run_evolve_session", fake_run_evolve_session)

    result = CliRunner().invoke(
        evolve,
        [
            "run",
            "--repo-root",
            str(tmp_path),
            "--goal",
            "Make one targeted improvement",
            "--acceptance-check",
            "evolve-corpus-summary",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["goal"] == "Make one targeted improvement"
    assert captured["refactor_first"] is False
    assert captured["acceptance_checks"] == ["evolve-corpus-summary"]


def test_evolve_run_cli_keeps_refactor_first_for_default_goal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_evolve_session(repo_root, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "session": {"session_id": "s1", "status": "ready", "delta": {"changed_count": 0}}}

    monkeypatch.setattr("thomas.cli.commands.evolve.run_evolve_session", fake_run_evolve_session)

    result = CliRunner().invoke(evolve, ["run", "--repo-root", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    assert captured["goal"] == ""
    assert captured["refactor_first"] is True


def test_evolve_run_cli_refactor_first_override_for_explicit_goal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run_evolve_session(repo_root, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "session": {"session_id": "s1", "status": "ready", "delta": {"changed_count": 0}}}

    monkeypatch.setattr("thomas.cli.commands.evolve.run_evolve_session", fake_run_evolve_session)

    result = CliRunner().invoke(
        evolve,
        ["run", "--repo-root", str(tmp_path), "--goal", "Refactor deliberately", "--refactor-first", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert captured["refactor_first"] is True


def test_evolve_run_cli_prints_acceptance_checks_in_human_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_evolve_session(repo_root, **kwargs):
        return {
            "ok": True,
            "session": {
                "session_id": "s1",
                "status": "ready",
                "delta": {"changed_count": 1},
                "promotable": True,
                "acceptance_checks": ["evolve_status_verifier_panel"],
            },
        }

    monkeypatch.setattr("thomas.cli.commands.evolve.run_evolve_session", fake_run_evolve_session)

    result = CliRunner().invoke(
        evolve,
        [
            "run",
            "--repo-root",
            str(tmp_path),
            "--goal",
            "Show acceptance checks",
            "--acceptance-check",
            "status-verifier-panel",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Acceptance checks: evolve_status_verifier_panel" in result.output


def test_evolve_agent_prompt_names_hard_stop_boundaries() -> None:
    prompt = evolve_runtime._build_agent_prompt(
        evolve_runtime.EvolveCharter(),
        "Make a safe improvement",
        pass_index=1,
        pass_count=1,
    )

    assert "Hard-stop boundary" in prompt
    assert "rejects the whole session before verification" in prompt
    assert "WORKTREE_RULES.md" in prompt
    assert "tests/*" in prompt
    assert "new thomas/forge/anvil/*.py files" in prompt
    assert "Existing non-supervisor evolve-loop files may be changed" in prompt
    assert "stop and report the boundary" in prompt
    assert "Do not call git.status or git.diff" in prompt
    assert "NO_ELIGIBLE_CHANGE" in prompt
    assert "diff.create" in prompt
    assert "fs.write_file" in prompt
    assert "Use `fs.search` or `code.search` to locate target symbols" in prompt
    assert "Do not use shell commands to edit files" in prompt
    assert "Shell/process tools are disabled in self-development" in prompt
    assert "Non-Python file changes are human-held" in prompt


def test_evolve_agent_prompt_names_acceptance_checks() -> None:
    prompt = evolve_runtime._build_agent_prompt(
        evolve_runtime.EvolveCharter(acceptance_checks=["status-verifier-panel"]),
        "Make a safe improvement",
        pass_index=1,
        pass_count=1,
    )

    assert "Acceptance checks the blue supervisor will run:" in prompt
    assert "evolve_status_verifier_panel" in prompt


def test_refactor_prompt_names_edit_tools_and_real_compile_command() -> None:
    prompt = build_refactor_prompt(RefactorTarget(path="thomas/core/example.py", line_count=1601, reason="oversized"))

    assert "diff.create" in prompt
    assert "fs.write_file" in prompt
    assert "Shell/process tools are disabled in self-development" in prompt
    assert "{path}" not in prompt
    assert "python -m py_compile <modified-file>" in prompt


def test_refactor_plan_skips_loop_and_protected_oversized_files(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        "enforcement_files=[]\n"
        'enforcement_scripts=["thomas/tools/shell.py"]\n',
        encoding="utf-8",
    )

    def write_lines(rel: str, count: int) -> None:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join("VALUE = 1" for _ in range(count)) + "\n", encoding="utf-8")

    write_lines("thomas/core/safe_big.py", 1601)
    write_lines("thomas/forge/anvil/evolve.py", 1601)
    write_lines("thomas/tools/shell.py", 1601)

    plan = build_refactor_plan(tmp_path)
    paths = [target.path for target in plan.targets]

    assert "thomas/core/safe_big.py" in paths
    assert "thomas/forge/anvil/evolve.py" not in paths
    assert "thomas/tools/shell.py" not in paths
    assert plan.skipped_ineligible >= 2


def test_evolve_protected_prefix_matches_child_paths() -> None:
    protected = {"evolve_corpus/"}

    assert evolve_runtime._is_evolve_protected_path("evolve_corpus/cases/new.json", protected) is True
    assert evolve_runtime._is_evolve_protected_path("evolve_corpus", protected) is False
    assert evolve_runtime._is_evolve_protected_path("thomas/core/example.py", protected) is False


def test_refactor_plan_skips_ineligible_health_ledger_targets(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    ledger_path = tmp_path / ".thomas" / "evolve" / "health_ledger.json"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(
        json.dumps(
            {
                "version": 1,
                "records": {
                    "tests/test_architecture.py": {
                        "path": "tests/test_architecture.py",
                        "status": "needs_work",
                        "line_count": 2000,
                    },
                    "scripts/forge/gates/workboard_inbox.py": {
                        "path": "scripts/forge/gates/workboard_inbox.py",
                        "status": "needs_work",
                        "line_count": 2000,
                    },
                    "thomas/forge/anvil/evolve_loop.py": {
                        "path": "thomas/forge/anvil/evolve_loop.py",
                        "status": "needs_work",
                        "line_count": 2000,
                    },
                    "thomas/core/safe_review.py": {
                        "path": "thomas/core/safe_review.py",
                        "status": "needs_work",
                        "line_count": 2000,
                    },
                },
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    plan = build_refactor_plan(tmp_path)
    paths = [target.path for target in plan.targets]

    assert "thomas/core/safe_review.py" in paths
    assert "tests/test_architecture.py" not in paths
    assert "scripts/forge/gates/workboard_inbox.py" not in paths
    assert "thomas/forge/anvil/evolve_loop.py" not in paths
    assert plan.skipped_ineligible >= 3


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

    run_result = runner.invoke(
        evolve,
        [
            "run",
            "--repo-root",
            str(tmp_path),
            "--goal",
            "Tighten Thomas UX",
            "--acceptance-check",
            "status-verifier-panel",
            "--json",
        ],
    )
    assert run_result.exit_code == 0, run_result.output
    payload = json.loads(run_result.output)
    session = payload["session"]
    assert session["status"] == "ready"
    assert "thomas/__init__.py" in session["changed_files"]
    assert session["promotable"] is True
    assert session["acceptance_checks"] == ["evolve_status_verifier_panel"]
    assert "evolve_status_verifier_panel" in session["pass_results"][0]["prompt"]
    assert any(
        item.get("source") == "acceptance" and item.get("acceptance_check") == "evolve_status_verifier_panel"
        for item in session["verification"]
    )

    promote_result = runner.invoke(evolve, ["promote", "--repo-root", str(tmp_path), "--json"])
    assert promote_result.exit_code == 0, promote_result.output
    promote_payload = json.loads(promote_result.output)
    assert promote_payload["session"]["status"] == "promoted"
    assert promote_payload["session"]["supervisor_verdict"]["ok"] is True
    assert promote_payload["session"]["supervisor_verdict"]["delta"]["modified"] == ["thomas/__init__.py"]
    assert promote_payload["session"]["verifier_panel"]["ok"] is True
    assert promote_payload["session"]["supervisor_verdict"]["verifier_panel"]["ok"] is True
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.1.0"'

    status_result = runner.invoke(evolve, ["status", "--repo-root", str(tmp_path)])
    assert status_result.exit_code == 0, status_result.output
    assert "Verifier panel: PASS" in status_result.output
    assert "5/4 pass" in status_result.output
    assert "Verifier panel reconciled: votes=5 quorum=4 dissent=0 (computed)" in status_result.output


def test_manual_promote_rejects_non_python_delta_without_dedicated_verifier(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "README.md").write_text("blue docs\n", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.2.0"\n', encoding="utf-8")
            Path(cwd, "README.md").write_text("green docs\n", encoding="utf-8")
        return {"command": "verify", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prepare mixed Python and docs change",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]

    result = CliRunner().invoke(evolve, ["promote", session["session_id"], "--repo-root", str(tmp_path), "--json"])

    assert result.exit_code != 0
    assert result.exception is not None
    assert "non-Python delta requires a dedicated passing non-Python verifier" in str(result.exception)
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "blue docs\n"


def test_manual_promote_allows_non_python_delta_with_dedicated_verifier(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "README.md").write_text("blue docs\n", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.3.0"\n', encoding="utf-8")
            Path(cwd, "README.md").write_text("green docs\n", encoding="utf-8")
        return {"command": "verify", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prepare verified mixed Python and docs change",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    session["verification"].append(
        {"command": "non-python verifier: inspect docs delta", "returncode": 0, "stdout_tail": "", "stderr_tail": ""}
    )
    session_path = tmp_path / ".thomas" / "evolve" / "sessions" / session["session_id"] / "session.json"
    session_path.write_text(json.dumps(session, indent=2), encoding="utf-8")

    result = CliRunner().invoke(
        evolve,
        ["promote", session["session_id"], "--repo-root", str(tmp_path), "--approve-critical-risk", "--json"],
    )

    assert result.exit_code == 0, result.output
    promoted = json.loads(result.output)["session"]
    assert promoted["status"] == "promoted"
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.3.0"'
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "green docs\n"


def test_evolve_run_repairs_failed_acceptance_verification_once(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    chat_calls = 0
    acceptance_calls = 0

    def fake_build_verify_plan(charter, delta, repo_root, *, goal="", acceptance_checks=None):
        _ = charter, delta, repo_root, goal, acceptance_checks
        return [
            {
                "command": ["acceptance-check"],
                "source": "acceptance",
                "description": "fake acceptance output",
                "acceptance_check": "fake_acceptance",
            }
        ]

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        nonlocal chat_calls, acceptance_calls
        _ = env, timeout_seconds
        if isinstance(command, list) and "chat" in command:
            chat_calls += 1
            version = "0.1.1" if chat_calls > 1 else "0.1.0"
            Path(cwd, "thomas", "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        if command == ["acceptance-check"]:
            acceptance_calls += 1
            if acceptance_calls == 1:
                return {
                    "command": "acceptance-check",
                    "returncode": 1,
                    "stdout_tail": "",
                    "stderr_tail": "missing required output",
                    "timed_out": False,
                }
            return {
                "command": "acceptance-check",
                "returncode": 0,
                "stdout_tail": "ok",
                "stderr_tail": "",
                "timed_out": False,
            }
        return {"command": "other", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_build_verify_plan", fake_build_verify_plan)
    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Add a visible acceptance output",
        acceptance_checks=["fake_acceptance"],
        refactor_first=False,
    )
    session = payload["session"]

    assert session["verification_repair_attempted"] is True
    assert len(session["verification_repair_failures"]) == 1
    assert session["verification_repair_failures"][0]["acceptance_check"] == "fake_acceptance"
    assert len(session["verification_repair_artifacts"]) == 1
    repair_artifact = Path(session["verification_repair_artifacts"][0]["path"])
    assert repair_artifact.exists()
    assert "missing required output" in repair_artifact.read_text(encoding="utf-8")
    assert str(repair_artifact) in session["pass_results"][-1]["prompt"]
    assert session["pass_results"][-1]["retry_reason"] == "verification_failure"
    assert "missing required output" in session["pass_results"][-1]["prompt"]
    assert "include that string exactly" in session["pass_results"][-1]["prompt"]
    assert session["pass_results"][-1]["verification_failure_artifacts"] == session["verification_repair_artifacts"]
    assert chat_calls == 2
    assert acceptance_calls == 2
    assert session["status"] == "ready"
    assert session["promotable"] is True
    assert session["verification"][0]["returncode"] == 0
    assert (get_paths(tmp_path).green_root / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == (
        '__version__ = "0.1.1"'
    )


def test_evolve_run_does_not_repair_unknown_acceptance_check(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    chat_calls = 0

    def fake_build_verify_plan(charter, delta, repo_root, *, goal="", acceptance_checks=None):
        _ = charter, delta, repo_root, goal, acceptance_checks
        return [
            {
                "command": ["unknown-acceptance-check"],
                "source": "acceptance_unknown",
                "description": "unknown evolve acceptance check",
                "acceptance_check": "missing_check",
            }
        ]

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        nonlocal chat_calls
        _ = env, timeout_seconds
        if isinstance(command, list) and "chat" in command:
            chat_calls += 1
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        if command == ["unknown-acceptance-check"]:
            return {
                "command": "unknown-acceptance-check",
                "returncode": 2,
                "stdout_tail": "",
                "stderr_tail": "unknown evolve acceptance check",
                "timed_out": False,
            }
        return {"command": "other", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_build_verify_plan", fake_build_verify_plan)
    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Use a missing acceptance check",
        acceptance_checks=["missing_check"],
        refactor_first=False,
    )
    session = payload["session"]

    assert session["verification_repair_attempted"] is False
    assert session["verification_repair_failures"] == []
    assert session["verification_repair_artifacts"] == []
    assert chat_calls == 1
    assert session["status"] == "verification_failed"
    assert session["promotable"] is False
    assert session["verification"][0]["source"] == "acceptance_unknown"


def test_evolve_run_does_not_repair_semantic_verification_failure(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    chat_calls = 0

    def fake_build_verify_plan(charter, delta, repo_root, *, goal="", acceptance_checks=None):
        _ = charter, delta, repo_root, goal, acceptance_checks
        return [
            {
                "command": ["semantic-check"],
                "source": "semantic",
                "description": "inferred semantic output",
                "acceptance_check": "semantic_status",
            }
        ]

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        nonlocal chat_calls
        _ = env, timeout_seconds
        if isinstance(command, list) and "chat" in command:
            chat_calls += 1
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        if command == ["semantic-check"]:
            return {
                "command": "semantic-check",
                "returncode": 1,
                "stdout_tail": "",
                "stderr_tail": "missing inferred semantic output",
                "timed_out": False,
            }
        return {"command": "other", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_build_verify_plan", fake_build_verify_plan)
    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Improve status wording",
        refactor_first=False,
    )
    session = payload["session"]

    assert session["verification_repair_attempted"] is False
    assert session["verification_repair_failures"] == []
    assert session["verification_repair_artifacts"] == []
    assert chat_calls == 1
    assert session["status"] == "verification_failed"
    assert session["promotable"] is False
    assert session["verification"][0]["source"] == "semantic"


def test_evolve_run_forces_utf8_child_stdio(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    seen_commands: list[object] = []
    seen_envs: list[dict[str, str]] = []
    seen_cwds: list[Path] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        seen_commands.append(command)
        seen_envs.append(dict(env))
        seen_cwds.append(Path(cwd))
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.1"\n', encoding="utf-8")
        return {
            "command": "ok",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prove green Thomas emits UTF-8 safely",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]

    assert seen_envs
    assert all(env.get("PYTHONIOENCODING") == "utf-8" for env in seen_envs)
    assert all(env.get("PYTHONUTF8") == "1" for env in seen_envs)
    assert all(isinstance(command, list) for command in seen_commands)
    assert any(path == Path(session["green_root"]) for path in seen_cwds)
    assert any(path == Path(session["verification_root"]) for path in seen_cwds)


def test_verification_plan_writes_full_output_sidecars(tmp_path: Path) -> None:
    verify_root = tmp_path / "verify"
    blue_root = tmp_path / "blue"
    artifact_dir = tmp_path / "artifacts"
    verify_root.mkdir()
    blue_root.mkdir()
    stdout_text = "A" * 7000
    stderr_text = "B" * 3000
    script = f"import sys; sys.stdout.write({stdout_text!r}); sys.stderr.write({stderr_text!r})"

    verification = evolve_runtime._run_verification_plan(
        SimpleNamespace(blue_root=blue_root),
        verify_root=verify_root,
        verify_plan=[
            {
                "command": [sys.executable, "-c", script],
                "source": "acceptance",
                "description": "long output check",
                "acceptance_check": "long_output",
            }
        ],
        timeout_seconds=30,
        artifact_dir=artifact_dir,
        prepare_verification_root=lambda *args, **kwargs: blue_root,
        evolve_child_env=lambda: dict(os.environ),
        run_exec=evolve_runtime._run_exec,
        strip_evolve_verification_env=lambda env: None,
    )

    result = verification[0]
    stdout_artifact = result["stdout_artifact"]
    stderr_artifact = result["stderr_artifact"]
    stdout_path = Path(stdout_artifact["path"])
    stderr_path = Path(stderr_artifact["path"])

    assert stdout_path.exists()
    assert stderr_path.exists()
    assert stdout_path.read_text(encoding="utf-8") == stdout_text
    assert stderr_path.read_text(encoding="utf-8") == stderr_text
    assert len(result["stdout_tail"]) < len(stdout_text)
    assert stdout_artifact["bytes"] == len(stdout_text)
    assert stderr_artifact["bytes"] == len(stderr_text)
    assert stdout_artifact["sha256"] == hashlib.sha256(stdout_text.encode("utf-8")).hexdigest()
    assert stderr_artifact["sha256"] == hashlib.sha256(stderr_text.encode("utf-8")).hexdigest()
