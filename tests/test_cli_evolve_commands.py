from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from evolve_supervisor import evaluate_spend_governor
from thomas.cli import _commands_base as cli_commands_base
from thomas.cli.commands.evolve import evolve
from thomas.core.config import load_config
from thomas.forge.anvil import evolve as evolve_runtime
from thomas.forge.anvil.doppelganger import (
    get_paths,
    promote_green_delta_to_blue,
    sync_blue_to_green,
    sync_green_to_blue,
)
from thomas.forge.anvil.refactor_pass import RefactorTarget, build_refactor_plan, build_refactor_prompt


def _seed_locked_corpus(root: Path) -> None:
    corpus = root / "evolve_corpus"
    cases = corpus / "cases"
    cases.mkdir(parents=True, exist_ok=True)
    case_file = cases / "known_good_minimal.json"
    case_file.write_text(
        json.dumps(
            {
                "case_id": "known_good_minimal",
                "expected_supervisor_outcome": "eligible_for_decision_gate",
                "session": {
                    "status": "ready",
                    "delta": {"changed_count": 1, "changed_files": ["thomas/__init__.py"]},
                    "verification": [{"source": "generated", "returncode": 0}],
                    "policy_violations": [],
                    "session_rejections": [],
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(case_file.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    (corpus / "LOCK.json").write_text(
        json.dumps({"version": 1, "files": {"cases/known_good_minimal.json": digest}}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _seed_repo(root: Path) -> None:
    (root / "thomas").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
    (root / "thomas" / "__init__.py").write_text('__version__ = "0.0.0"\n', encoding="utf-8")
    (root / "tests" / "test_architecture.py").write_text(
        "import thomas\n\n\ndef test_smoke():\n    assert thomas.__version__\n",
        encoding="utf-8",
    )
    _seed_locked_corpus(root)


class _FakeVerifierPanelResult:
    def __init__(
        self,
        *,
        ok: bool,
        pass_count: int,
        quorum: int = 4,
        critical_dissent_count: int = 0,
        votes: list[dict[str, str]] | None = None,
    ) -> None:
        self.ok = ok
        self.pass_count = pass_count
        self.quorum = quorum
        self.critical_dissent_count = critical_dissent_count
        self.votes = (
            votes
            if votes is not None
            else [
                {"role": f"role_{idx}", "status": "pass", "reason": "ok", "severity": "advisory"}
                for idx in range(pass_count)
            ]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "quorum": self.quorum,
            "pass_count": self.pass_count,
            "critical_dissent_count": self.critical_dissent_count,
            "votes": self.votes,
        }


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


def test_charter_verify_strings_are_normalized_to_argv(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(
        verify_commands=['python -m pytest tests/test_architecture.py -q -k "not slow"']
    )

    commands = evolve_runtime._build_verify_commands(charter, {"changed_files": []}, tmp_path)

    assert commands == [[sys.executable, "-m", "pytest", "tests/test_architecture.py", "-q", "-k", "not slow"]]


def test_unsafe_charter_verify_string_is_rejected_without_shell(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(verify_commands=["python -m pytest tests; echo unsafe"])

    plan = evolve_runtime._build_verify_plan(charter, {"changed_files": []}, tmp_path)
    commands = evolve_runtime._build_verify_commands(charter, {"changed_files": []}, tmp_path)

    assert plan[0]["source"] == "charter_unsafe"
    assert len(commands) == 1
    command = commands[0]
    assert isinstance(command, list)
    assert command[:3] == [
        sys.executable,
        "-c",
        "import sys; sys.stderr.write(sys.argv[1] + '\\n'); raise SystemExit(2)",
    ]
    assert "unsafe charter verify command rejected" in command[3]
    assert "shell metacharacter" in command[3]


def test_changed_python_verify_plan_includes_ruff_hygiene(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(verify_commands=[])

    plan = evolve_runtime._build_verify_plan(charter, {"changed_files": ["thomas/__init__.py"]}, tmp_path)
    commands = [entry["command"] for entry in plan]

    assert [sys.executable, "-m", "py_compile", "thomas/__init__.py"] in commands
    assert [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--select",
        "F401,F821,F841",
        "thomas/__init__.py",
    ] in commands
    assert any(entry.get("description") == "ruff changed-python hygiene" for entry in plan)
    assert any(
        entry.get("source") == "generated"
        and entry.get("description") == "python semantic delta"
        and entry["command"][0:2] == [sys.executable, "-c"]
        and entry["command"][-1] == "thomas/__init__.py"
        for entry in plan
    )


def test_python_semantic_delta_counts_import_binding_swap(tmp_path: Path) -> None:
    blue = tmp_path / "blue"
    green = tmp_path / "green"
    for base in (blue, green):
        (base / "thomas").mkdir(parents=True)
    (blue / "thomas" / "security.py").write_text(
        "from hashlib import sha256 as digest\n\n\ndef hash_value(data):\n    return digest(data).hexdigest()\n",
        encoding="utf-8",
    )
    (green / "thomas" / "security.py").write_text(
        "from hashlib import md5 as digest\n\n\ndef hash_value(data):\n    return digest(data).hexdigest()\n",
        encoding="utf-8",
    )
    plan = evolve_runtime._build_verify_plan(
        evolve_runtime.EvolveCharter(verify_commands=[]),
        {"changed_files": ["thomas/security.py"]},
        green,
    )
    semantic = next(entry for entry in plan if entry.get("description") == "python semantic delta")
    env = dict(os.environ)
    env["THOMAS_EVOLVE_BLUE_ROOT"] = str(blue)

    result = subprocess.run(
        semantic["command"],
        cwd=green,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "semantic delta: PASS" in result.stdout


def test_python_semantic_delta_still_blocks_docstring_only_change(tmp_path: Path) -> None:
    blue = tmp_path / "blue"
    green = tmp_path / "green"
    for base in (blue, green):
        (base / "thomas").mkdir(parents=True)
    (blue / "thomas" / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    (green / "thomas" / "feature.py").write_text('"""Updated docs."""\n\nVALUE = 1\n', encoding="utf-8")
    plan = evolve_runtime._build_verify_plan(
        evolve_runtime.EvolveCharter(verify_commands=[]),
        {"changed_files": ["thomas/feature.py"]},
        green,
    )
    semantic = next(entry for entry in plan if entry.get("description") == "python semantic delta")
    env = dict(os.environ)
    env["THOMAS_EVOLVE_BLUE_ROOT"] = str(blue)

    result = subprocess.run(
        semantic["command"],
        cwd=green,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "semantic-noop Python change(s): thomas/feature.py" in result.stderr


def test_status_goal_adds_and_runs_semantic_status_verifier(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(verify_commands=[])
    delta = {"changed_files": ["thomas/cli/commands/evolve.py"]}

    plan = evolve_runtime._build_verify_plan(
        charter,
        delta,
        tmp_path,
        goal="Improve evolve status verifier panel output",
    )

    semantic = [
        entry
        for entry in plan
        if entry.get("source") == "semantic" and entry.get("description") == "evolve status verifier-panel output"
    ]
    assert len(semantic) == 1
    result = subprocess.run(
        semantic[0]["command"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_corpus_goal_adds_and_runs_semantic_corpus_verifier(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(verify_commands=[])
    delta = {"changed_files": ["thomas/cli/commands/evolve.py"]}

    plan = evolve_runtime._build_verify_plan(
        charter,
        delta,
        tmp_path,
        goal="Improve human-readable thomas evolve corpus output with failed and lock error counts",
    )

    semantic = [
        entry
        for entry in plan
        if entry.get("source") == "semantic" and entry.get("description") == "evolve corpus human-readable summary"
    ]
    assert len(semantic) == 1
    result = subprocess.run(
        semantic[0]["command"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_explicit_acceptance_check_adds_semantic_verifier_without_goal_text(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(verify_commands=[])
    delta = {"changed_files": ["README.md"]}

    plan = evolve_runtime._build_verify_plan(
        charter,
        delta,
        tmp_path,
        acceptance_checks=["status-verifier-panel"],
    )

    acceptance = [
        entry
        for entry in plan
        if entry.get("source") == "acceptance" and entry.get("acceptance_check") == "evolve_status_verifier_panel"
    ]
    assert len(acceptance) == 1
    assert acceptance[0]["description"] == "evolve status verifier-panel output"
    result = subprocess.run(
        acceptance[0]["command"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_panel_counts_acceptance_check_runs_nonce_reconciled_verifier(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(verify_commands=[])
    delta = {"changed_files": ["README.md"]}

    plan = evolve_runtime._build_verify_plan(
        charter,
        delta,
        tmp_path,
        acceptance_checks=["panel-counts-match"],
    )

    acceptance = [
        entry
        for entry in plan
        if entry.get("source") == "acceptance" and entry.get("acceptance_check") == "evolve_status_panel_counts_match"
    ]
    assert len(acceptance) == 1
    assert acceptance[0]["description"] == "evolve status verifier-panel computed count reconciliation"
    result = subprocess.run(
        acceptance[0]["command"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_status_rejection_reason_acceptance_check_runs_behavioral_verifier(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(verify_commands=[])
    delta = {"changed_files": ["thomas/cli/commands/evolve.py"]}

    plan = evolve_runtime._build_verify_plan(
        charter,
        delta,
        tmp_path,
        acceptance_checks=["status-rejection-reason"],
    )

    acceptance = [
        entry
        for entry in plan
        if entry.get("source") == "acceptance" and entry.get("acceptance_check") == "evolve_status_rejection_reason"
    ]
    assert len(acceptance) == 1
    assert acceptance[0]["description"] == "evolve status rejection reason output"
    result = subprocess.run(
        acceptance[0]["command"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_status_rejection_reason_semantic_check_is_goal_inferred(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(verify_commands=[])
    delta = {"changed_files": ["thomas/cli/commands/evolve.py"]}

    plan = evolve_runtime._build_verify_plan(
        charter,
        delta,
        tmp_path,
        goal="Show rejection reason in evolve status for rejected sessions",
    )

    inferred = [
        entry
        for entry in plan
        if entry.get("source") == "semantic" and entry.get("acceptance_check") == "evolve_status_rejection_reason"
    ]
    assert len(inferred) == 1
    assert inferred[0]["description"] == "evolve status rejection reason output"


def test_planner_builtins_eval_alias_acceptance_check_runs_behavioral_verifier(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(verify_commands=[])
    delta = {"changed_files": ["thomas/forge/anvil/evolve_planner_detectors.py"]}

    plan = evolve_runtime._build_verify_plan(
        charter,
        delta,
        tmp_path,
        goal="Count builtins eval aliases in the evolve planner detector",
        acceptance_checks=["planner-builtins-eval-alias"],
    )

    explicit_acceptance = [
        entry
        for entry in plan
        if entry.get("source") == "acceptance" and entry.get("acceptance_check") == "evolve_planner_builtins_eval_alias"
    ]
    assert len(explicit_acceptance) == 1
    assert explicit_acceptance[0]["description"] == "evolve planner builtins eval alias detection"
    assert not [
        entry
        for entry in plan
        if entry.get("source") == "semantic" and entry.get("acceptance_check") == "evolve_planner_builtins_eval_alias"
    ]
    result = subprocess.run(
        explicit_acceptance[0]["command"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_planner_builtins_eval_alias_semantic_check_is_goal_inferred(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(verify_commands=[])
    delta = {"changed_files": ["thomas/forge/anvil/evolve_planner_detectors.py"]}

    plan = evolve_runtime._build_verify_plan(
        charter,
        delta,
        tmp_path,
        goal="Count eval calls imported from builtins in planner detector",
    )

    inferred = [
        entry
        for entry in plan
        if entry.get("source") == "semantic" and entry.get("acceptance_check") == "evolve_planner_builtins_eval_alias"
    ]
    assert len(inferred) == 1
    assert inferred[0]["description"] == "evolve planner builtins eval alias detection"


def test_unknown_acceptance_check_fails_closed(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(verify_commands=[])
    delta = {"changed_files": ["README.md"]}

    plan = evolve_runtime._build_verify_plan(
        charter,
        delta,
        tmp_path,
        acceptance_checks=["missing-check"],
    )

    assert len(plan) == 1
    assert plan[0]["source"] == "acceptance_unknown"
    assert plan[0]["acceptance_check"] == "missing_check"
    result = subprocess.run(
        plan[0]["command"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "unknown evolve acceptance check: missing_check" in result.stderr


def test_evolve_reject_can_mark_ready_session_rejected(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    evolve_runtime.ensure_evolve_charter(tmp_path, overwrite=True)
    session_id = "evolve-20260622-233601-ff7c36"
    session_dir = tmp_path / ".thomas" / "evolve" / "sessions" / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "goal": "Known-bad candidate",
                "status": "ready",
                "delta": {"changed_count": 1, "changed_files": ["thomas/__init__.py"]},
                "changed_files": ["thomas/__init__.py"],
                "verification": [{"command": "synthetic verify", "source": "generated", "returncode": 0}],
                "session_rejections": [],
                "policy_violations": [],
                "promotable": True,
                "promoted": False,
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        evolve,
        [
            "reject",
            session_id,
            "--repo-root",
            str(tmp_path),
            "--reason",
            "red-team found behavior did not change",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    session = payload["session"]
    assert payload["rejected_session"] is True
    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["rejection_reason"] == "red-team found behavior did not change"
    assert any("red-team found behavior did not change" in item for item in session["session_rejections"])
    stored = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    assert stored["status"] == "rejected"
    assert stored["promotable"] is False

    promote = CliRunner().invoke(evolve, ["promote", session_id, "--repo-root", str(tmp_path), "--json"])
    assert promote.exit_code != 0
    assert json.loads((session_dir / "session.json").read_text(encoding="utf-8"))["promoted"] is False


def test_baseline_failed_charter_check_does_not_block_candidate_specific_passes(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.2"\n', encoding="utf-8")
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        is_charter_architecture = isinstance(command, list) and "-k" in command
        if is_charter_architecture:
            return {
                "command": "charter architecture",
                "returncode": 1,
                "stdout_tail": "pre-existing architecture debt",
                "stderr_tail": "",
                "timed_out": False,
            }
        return {"command": "generated", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Make a tiny version marker change",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    charter_rows = [item for item in session["verification"] if item.get("source") == "charter"]

    assert session["status"] == "ready"
    assert session["promotable"] is True
    assert charter_rows
    assert charter_rows[0]["returncode"] == 1
    assert charter_rows[0]["baseline_returncode"] == 1


def test_unsafe_charter_verify_command_blocks_even_when_baseline_also_fails(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    charter = evolve_runtime.EvolveCharter(verify_commands=["python -m pytest tests; echo unsafe"])
    evolve_runtime.ensure_evolve_charter(tmp_path, charter=charter, overwrite=True)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.3"\n', encoding="utf-8")
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        if isinstance(command, list) and "-c" in command:
            return {
                "command": "unsafe charter",
                "returncode": 2,
                "stdout_tail": "",
                "stderr_tail": "unsafe charter verify command rejected",
                "timed_out": False,
            }
        return {"command": "generated", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Make a tiny version marker change",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    unsafe_rows = [item for item in session["verification"] if item.get("source") == "charter_unsafe"]

    assert session["status"] == "verification_failed"
    assert session["promotable"] is False
    assert unsafe_rows
    assert unsafe_rows[0]["returncode"] == 2
    assert "baseline_returncode" not in unsafe_rows[0]


def test_evolve_run_blocks_unused_import_candidate_with_generated_ruff(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text(
                "import os\n\n__version__ = '0.2.0'\n",
                encoding="utf-8",
            )
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        if isinstance(command, list) and command[:4] == [sys.executable, "-m", "ruff", "check"]:
            return {
                "command": "ruff",
                "returncode": 1,
                "stdout_tail": "F401 `os` imported but unused",
                "stderr_tail": "",
                "timed_out": False,
            }
        return {"command": "generated", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Make an import-only improvement",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]
    ruff_rows = [item for item in session["verification"] if item.get("description") == "ruff changed-python hygiene"]

    assert session["status"] == "verification_failed"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert ruff_rows
    assert ruff_rows[0]["returncode"] == 1
    assert "F401" in ruff_rows[0]["stdout_tail"]
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_blocks_docstring_only_candidate_with_semantic_delta(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text(
                '"""Updated but behavior-free module docs."""\n\n__version__ = "0.0.0"\n',
                encoding="utf-8",
            )
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        if isinstance(command, list) and command[:2] == [sys.executable, "-c"] and "semantic-noop" in command[2]:
            return {
                "command": "semantic",
                "returncode": 1,
                "stdout_tail": "",
                "stderr_tail": "semantic-noop Python change(s): thomas/__init__.py",
                "timed_out": False,
            }
        return {"command": "generated", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Make a docstring-only improvement",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]
    semantic_rows = [item for item in session["verification"] if item.get("description") == "python semantic delta"]

    assert session["status"] == "verification_failed"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert semantic_rows
    assert semantic_rows[0]["returncode"] == 1
    assert "semantic-noop" in semantic_rows[0]["stderr_tail"]
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_rejects_green_delta_drift_after_verified_session(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    assert session["status"] == "ready"
    assert session["promotable"] is True

    paths = get_paths(tmp_path)
    (paths.green_root / "thomas" / "__init__.py").write_text('__version__ = "0.9.9"\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="green tree changed since evolve session verification"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_preserves_unrelated_dirty_blue_files(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    unrelated = tmp_path / "thomas" / "core" / "unrelated.py"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("VALUE = 'blue baseline'\n", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    assert session["status"] == "ready"
    unrelated.write_text("VALUE = 'user dirty blue edit'\n", encoding="utf-8")

    promoted = evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert promoted["session"]["status"] == "promoted"
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.1.0"'
    assert unrelated.read_text(encoding="utf-8") == "VALUE = 'user dirty blue edit'\n"


def test_promote_rejects_when_blue_target_changed_since_session_baseline(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    (tmp_path / "thomas" / "__init__.py").write_text('__version__ = "user-edit"\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="blue target files changed since evolve session baseline"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == ('__version__ = "user-edit"')


def test_promote_rejects_when_blue_supervisor_manifest_changes(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    blue_anvil = tmp_path / "thomas" / "forge" / "anvil" / "evolve.py"
    blue_anvil.parent.mkdir(parents=True, exist_ok=True)
    blue_anvil.write_text("BASELINE = 'safe'\n", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    assert "thomas/forge/anvil/evolve.py" in session["blue_supervisor_manifest"]["files"]
    blue_anvil.write_text("BASELINE = 'tampered'\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="blue supervisor/anvil files changed since evolve session baseline"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_rejects_forged_blue_supervisor_manifest_signature(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    blue_anvil = tmp_path / "thomas" / "forge" / "anvil" / "evolve.py"
    blue_anvil.parent.mkdir(parents=True, exist_ok=True)
    blue_anvil.write_text("BASELINE = 'safe'\n", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    session["blue_supervisor_manifest"]["signature"]["value"] = "0" * 64
    session_path = Path(session["diff_path"]).parent / "session.json"
    session_path.write_text(json.dumps(session, ensure_ascii=True, indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="blue supervisor/anvil manifest signature mismatch"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_rejects_legacy_session_without_blue_baseline_fingerprint(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    session.pop("blue_delta_base_fingerprint", None)
    session_path = Path(session["diff_path"]).parent / "session.json"
    session_path.write_text(json.dumps(session, ensure_ascii=True, indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing blue delta base fingerprint"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_calls_blue_only_supervisor_before_copying(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    paths = get_paths(tmp_path)
    (paths.green_root / "tests" / "test_architecture.py").write_text("def test_smoke():\n    pass\n", encoding="utf-8")

    forged_delta = evolve_runtime._collect_tree_delta(paths)
    session["delta"] = forged_delta
    session["changed_files"] = list(forged_delta["changed_files"])
    session["verified_delta_fingerprint"] = evolve_runtime._delta_fingerprint(paths, forged_delta)
    session["blue_delta_base_fingerprint"] = evolve_runtime._delta_fingerprint_for_root(tmp_path, forged_delta)
    session_path = Path(session["diff_path"]).parent / "session.json"
    session_path.write_text(json.dumps(session, ensure_ascii=True, indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="blue-only supervisor rejected evolve promotion"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert "test_architecture.py" not in (tmp_path / "tests" / "test_architecture.py").read_text(encoding="utf-8")


def test_promote_verifier_panel_uses_fresh_supervisor_verdict(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    seen: dict[str, object] = {}

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def fake_panel(session_payload, *, supervisor_verdict, quorum=4):
        seen["stored_supervisor_ok"] = dict(session_payload.get("supervisor_verdict") or {}).get("ok")
        seen["fresh_supervisor_ok"] = supervisor_verdict.get("ok")
        return _FakeVerifierPanelResult(ok=True, pass_count=5, quorum=quorum)

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "run_verifier_panel", fake_panel)

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    session["supervisor_verdict"] = {
        "ok": False,
        "findings": [{"code": "forged_stale_artifact", "severity": "reject"}],
    }
    session_path = Path(session["diff_path"]).parent / "session.json"
    session_path.write_text(json.dumps(session, ensure_ascii=True, indent=2), encoding="utf-8")

    promoted = evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert seen == {"stored_supervisor_ok": False, "fresh_supervisor_ok": True}
    assert promoted["session"]["status"] == "promoted"
    assert promoted["session"]["verifier_panel"]["ok"] is True
    assert promoted["session"]["supervisor_verdict"]["verifier_panel"]["pass_count"] == 5
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.1.0"'


def test_promote_rejects_when_verifier_panel_lacks_quorum(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def fake_panel(session_payload, *, supervisor_verdict, quorum=4):
        _ = session_payload, supervisor_verdict
        return _FakeVerifierPanelResult(ok=False, pass_count=3, quorum=quorum)

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "run_verifier_panel", fake_panel)

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]

    with pytest.raises(RuntimeError, match="verifier panel rejected evolve promotion: pass_count 3 below quorum 4"):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_rejects_when_verifier_panel_has_hold_despite_quorum(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def fake_panel(session_payload, *, supervisor_verdict, quorum=4):
        _ = session_payload, supervisor_verdict
        return _FakeVerifierPanelResult(
            ok=True,
            pass_count=4,
            quorum=quorum,
            votes=[
                {"role": "correctness", "status": "pass", "reason": "ok", "severity": "advisory"},
                {"role": "regression", "status": "pass", "reason": "ok", "severity": "advisory"},
                {"role": "security", "status": "pass", "reason": "ok", "severity": "advisory"},
                {"role": "reward_hack", "status": "pass", "reason": "ok", "severity": "advisory"},
                {
                    "role": "reproducibility",
                    "status": "hold",
                    "reason": "needs replay evidence",
                    "severity": "advisory",
                },
            ],
        )

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "run_verifier_panel", fake_panel)

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tighten Thomas UX",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]

    with pytest.raises(
        RuntimeError,
        match=r"verifier panel rejected evolve promotion: non-passing verifier vote\(s\): reproducibility:hold",
    ):
        evolve_runtime.promote_evolve_session(tmp_path, session_id=session["session_id"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_delta_promotion_does_not_copy_unlisted_green_changes(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    blue_unrelated = tmp_path / "thomas" / "core" / "unrelated.py"
    green_unrelated = paths.green_root / "thomas" / "core" / "unrelated.py"
    blue_unrelated.parent.mkdir(parents=True)
    green_unrelated.parent.mkdir(parents=True)
    blue_unrelated.write_text("VALUE = 'dirty blue'\n", encoding="utf-8")
    green_unrelated.write_text("VALUE = 'stale green'\n", encoding="utf-8")
    (paths.green_root / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")

    promote_green_delta_to_blue(paths, ["thomas/__init__.py"])

    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.1.0"'
    assert blue_unrelated.read_text(encoding="utf-8") == "VALUE = 'dirty blue'\n"


def test_delta_promotion_applies_verified_deletions_only(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    paths = get_paths(tmp_path)
    delete_me = tmp_path / "thomas" / "feature" / "delete_me.py"
    keep_me = tmp_path / "thomas" / "feature" / "keep_me.py"
    delete_me.parent.mkdir(parents=True)
    delete_me.write_text("VALUE = 'delete'\n", encoding="utf-8")
    keep_me.write_text("VALUE = 'keep blue'\n", encoding="utf-8")
    sync_blue_to_green(paths)

    (paths.green_root / "thomas" / "feature" / "delete_me.py").unlink()
    (paths.green_root / "thomas" / "feature" / "keep_me.py").write_text("VALUE = 'stale green'\n", encoding="utf-8")

    promote_green_delta_to_blue(paths, ["thomas/feature/delete_me.py"])

    assert not delete_me.exists()
    assert keep_me.read_text(encoding="utf-8") == "VALUE = 'keep blue'\n"


def test_promotion_candidate_root_preserves_blue_support_scope(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "evolve_supervisor").mkdir()
    (tmp_path / "evolve_supervisor" / "__init__.py").write_text("VERSION = 'blue'\n", encoding="utf-8")
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")

    candidate_root = evolve_runtime._prepare_delta_candidate_root(
        paths,
        {"changed_files": ["thomas/__init__.py"]},
    )

    assert (candidate_root / "evolve_supervisor" / "__init__.py").read_text(encoding="utf-8") == "VERSION = 'blue'\n"
    assert (candidate_root / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == ('__version__ = "0.1.0"')


def test_sync_blue_to_green_includes_support_docs_and_assets(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    support_files = {
        "AGENTS.md": "root agent rules\n",
        "GUARDRAILS.md": "root guardrails\n",
        "WORKTREE_RULES.md": "worktree rules\n",
        "agent_safety.toml": "[protected]\npolicy_files=[]\nguardrails_files=[]\nenforcement_files=[]\nenforcement_scripts=[]\n",
        "docs/AGENT_FILE_EDITING_RULES.md": "edit rules\n",
        "docs/ai/AGENT_ROUTER.md": "router\n",
        "docs/ai/CHECKLISTS/agent-lane-chat.md": "chat lane\n",
        "extensions/catalog.json": "{}\n",
        "evolve_supervisor/__init__.py": "VERSION = 'blue'\n",
        "apps/site/src/lib/site-config.ts": "export const config = {};\n",
        "apps/site/src/app/marketplace/page.tsx": "export default function Page() { return null; }\n",
        "apps/site/src/app/api/marketplace/catalog/route.ts": "export async function GET() { return Response.json({}); }\n",
        "apps/site/src/app/api/v1/plugins/catalog/route.ts": "export async function GET() { return Response.json({}); }\n",
        "apps/site/src/app/api/v1/plugins/download-token/route.ts": "export async function GET() { return Response.json({}); }\n",
        "apps/site/src/app/api/v1/plugins/[pluginId]/route.ts": "export async function GET() { return Response.json({}); }\n",
    }
    for rel, text in support_files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)

    for rel in support_files:
        assert (paths.green_root / rel).exists(), rel
    assert (paths.green_root / "evolve_corpus" / "LOCK.json").exists()


def test_sync_green_to_blue_blocks_protected_diff_at_copy_time(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["tests/test_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "tests" / "test_architecture.py").write_text(
        "def test_smoke():\n    assert False\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="protected/supervisor-owned diff"):
        sync_green_to_blue(paths)

    assert (tmp_path / "tests" / "test_architecture.py").read_text(encoding="utf-8") == (
        "import thomas\n\n\ndef test_smoke():\n    assert thomas.__version__\n"
    )


def test_sync_green_to_blue_blocks_runtime_protected_guard_diff_at_copy_time(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    guard = tmp_path / "thomas" / "tools" / "filesystem.py"
    guard.parent.mkdir(parents=True)
    guard.write_text("PROTECTED = True\n", encoding="utf-8")
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "tools" / "filesystem.py").write_text("PROTECTED = False\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="thomas/tools/filesystem.py"):
        sync_green_to_blue(paths)

    assert guard.read_text(encoding="utf-8") == "PROTECTED = True\n"


def test_sync_green_to_blue_blocks_protected_prefix_diff_at_copy_time(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        'policy_files=["evolve_corpus/"]\n'
        "guardrails_files=[]\n"
        "enforcement_files=[]\n"
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "evolve_corpus" / "cases" / "known_good_minimal.json").write_text(
        '{"case_id":"tampered"}\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="evolve_corpus/cases/known_good_minimal.json"):
        sync_green_to_blue(paths)


def test_sync_green_to_blue_blocks_supervisor_owned_diff_at_copy_time(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas" / "forge" / "anvil").mkdir(parents=True)
    (tmp_path / "thomas" / "forge" / "anvil" / "evolve.py").write_text(
        "SUPERVISOR = 'blue'\n",
        encoding="utf-8",
    )
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "forge" / "anvil" / "evolve.py").write_text(
        "SUPERVISOR = 'tampered'\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="thomas/forge/anvil/evolve.py"):
        sync_green_to_blue(paths)

    assert (tmp_path / "thomas" / "forge" / "anvil" / "evolve.py").read_text(encoding="utf-8") == (
        "SUPERVISOR = 'blue'\n"
    )


def test_sync_green_to_blue_blocks_new_loop_package_python_file_at_copy_time(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas" / "forge" / "anvil").mkdir(parents=True)
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "forge" / "anvil" / "evolve_fake_gate.py").write_text(
        "ALWAYS_PASS = True\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="thomas/forge/anvil/evolve_fake_gate.py"):
        sync_green_to_blue(paths)

    assert not (tmp_path / "thomas" / "forge" / "anvil" / "evolve_fake_gate.py").exists()


def test_sync_green_to_blue_blocks_existing_loop_package_python_diff_at_copy_time(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas" / "forge" / "anvil").mkdir(parents=True)
    (tmp_path / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py").write_text(
        "RANKER = 'blue'\n",
        encoding="utf-8",
    )
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py").write_text(
        "RANKER = 'tampered'\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="thomas/forge/anvil/evolve_loop_learning.py"):
        sync_green_to_blue(paths)

    assert (tmp_path / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py").read_text(
        encoding="utf-8"
    ) == "RANKER = 'blue'\n"


def test_delta_promotion_allows_verified_existing_loop_package_python_diff(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    loop_file = tmp_path / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py"
    loop_file.parent.mkdir(parents=True)
    loop_file.write_text("RANKER = 'blue'\n", encoding="utf-8")
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py").write_text(
        "RANKER = 'green'\n",
        encoding="utf-8",
    )

    promote_green_delta_to_blue(paths, ["thomas/forge/anvil/evolve_loop_learning.py"])

    assert loop_file.read_text(encoding="utf-8") == "RANKER = 'green'\n"


def test_delta_promotion_blocks_new_loop_package_python_file(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "forge" / "anvil").mkdir(parents=True, exist_ok=True)
    (paths.green_root / "thomas" / "forge" / "anvil" / "evolve_fake_gate.py").write_text(
        "ALWAYS_PASS = True\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="thomas/forge/anvil/evolve_fake_gate.py"):
        promote_green_delta_to_blue(paths, ["thomas/forge/anvil/evolve_fake_gate.py"])

    assert not (tmp_path / "thomas" / "forge" / "anvil" / "evolve_fake_gate.py").exists()


def test_delta_promotion_blocks_runtime_protected_guard_delta(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    guard = tmp_path / "thomas" / "tools" / "filesystem.py"
    guard.parent.mkdir(parents=True)
    guard.write_text("PROTECTED = True\n", encoding="utf-8")
    paths = get_paths(tmp_path)
    sync_blue_to_green(paths)
    (paths.green_root / "thomas" / "tools" / "filesystem.py").write_text("PROTECTED = False\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="thomas/tools/filesystem.py"):
        promote_green_delta_to_blue(paths, ["thomas/tools/filesystem.py"])

    assert guard.read_text(encoding="utf-8") == "PROTECTED = True\n"


def test_evolve_run_reverts_protected_file_changes(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["tests/test_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            Path(cwd, "tests", "test_architecture.py").write_text(
                "def test_smoke():\n    assert False\n", encoding="utf-8"
            )
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
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(tmp_path, goal="Safe runtime tweak")
    session = payload["session"]
    green_test = get_paths(tmp_path).green_root / "tests" / "test_architecture.py"

    assert session["status"] == "policy_violation"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["policy_violations"] == ["tests/test_architecture.py"]
    assert session["tamper_count"] == 1
    assert session["verification"] == []
    assert "protected path tamper detected before verification" in session["verification_skipped_reason"]
    assert "tests/test_architecture.py" not in session["changed_files"]
    assert "thomas/__init__.py" in session["changed_files"]
    assert green_test.read_text(encoding="utf-8") == (
        "import thomas\n\n\ndef test_smoke():\n    assert thomas.__version__\n"
    )
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_rejects_whole_session_after_protected_tamper(tmp_path: Path, monkeypatch) -> None:
    """A protected-path tamper rejects the whole session, even with clean edits."""
    _seed_repo(tmp_path)
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["tests/test_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
            Path(cwd, "tests", "test_architecture.py").write_text(
                "def test_smoke():\n    assert False\n", encoding="utf-8"
            )
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        return {"command": "verify", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(tmp_path, goal="tweak", promote_on_pass=True)
    session = payload["session"]

    assert session["status"] == "policy_violation"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["policy_violations"] == ["tests/test_architecture.py"]
    assert session["tamper_count"] == 1
    assert session["verification"] == []
    assert "protected path tamper detected before verification" in session["verification_skipped_reason"]
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'
    assert (tmp_path / "tests" / "test_architecture.py").read_text(
        encoding="utf-8"
    ) == "import thomas\n\n\ndef test_smoke():\n    assert thomas.__version__\n"


def test_evolve_run_cannot_promote_without_verification_evidence(tmp_path: Path, monkeypatch) -> None:
    """A non-Python-only change with an empty verification ladder must fail closed."""
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "README.md").write_text("unverified docs change\n", encoding="utf-8")
        return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(
        evolve_runtime,
        "_build_verify_plan",
        lambda charter, delta, repo_root, *, goal="", acceptance_checks=None: [],
    )

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Make an unverified non-Python change",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["changed_files"] == ["README.md"]
    assert session["verification"] == []
    assert session["status"] == "unverified"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert not (tmp_path / "README.md").exists()


def test_evolve_run_rejects_new_loop_package_python_file(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "forge", "anvil").mkdir(parents=True, exist_ok=True)
            Path(cwd, "thomas", "forge", "anvil", "evolve_fake_gate.py").write_text(
                "ALWAYS_PASS = True\n",
                encoding="utf-8",
            )
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.4.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Install a fake evolve gate",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert any("new evolve-loop Python file" in item for item in session["session_rejections"])
    assert not (tmp_path / "thomas" / "forge" / "anvil" / "evolve_fake_gate.py").exists()
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_allows_existing_loop_package_python_change_with_blast_radius(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas" / "forge" / "anvil").mkdir(parents=True)
    (tmp_path / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py").write_text(
        "RANKER = 'blue'\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_evolve_loop_learning.py").write_text(
        "from thomas.forge.anvil import evolve_loop_learning\n\n\n"
        "def test_ranker_is_configured():\n"
        "    assert evolve_loop_learning.RANKER\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "forge", "anvil", "evolve_loop_learning.py").write_text(
                "RANKER = 'green'\n",
                encoding="utf-8",
            )
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Retune the existing evolve ranker under supervisor review",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "ready"
    assert session["promotable"] is True
    assert session["promoted"] is False
    assert session["session_rejections"] == []
    assert session["verification_floor_failures"] == []
    assert session["changed_files"] == ["thomas/forge/anvil/evolve_loop_learning.py"]
    assert (tmp_path / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py").read_text(
        encoding="utf-8"
    ) == "RANKER = 'blue'\n"
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_rejects_test_infra_changes(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "tests", "conftest.py").write_text(
                "collect_ignore = ['test_architecture.py']\n", encoding="utf-8"
            )
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.5.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Suppress tests",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert any("test infrastructure changed" in item for item in session["session_rejections"])
    assert session["verification"] == []
    assert "session rejected before verification" in session["verification_skipped_reason"]
    assert not (tmp_path / "tests" / "conftest.py").exists()
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_rejects_green_support_file_tamper(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\npolicy_files=[]\nguardrails_files=[]\nenforcement_files=[]\nenforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "agent_safety.toml").write_text(
                "[protected]\n"
                "policy_files=[]\n"
                "guardrails_files=[]\n"
                "enforcement_files=[]\n"
                "enforcement_scripts=[]\n"
                "# green tamper\n",
                encoding="utf-8",
            )
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.5.1"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tamper with green support policy before verifying",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert any("green support file changed" in item for item in session["session_rejections"])
    assert session["verification"] == []
    assert "session rejected before verification" in session["verification_skipped_reason"]
    assert (tmp_path / "agent_safety.toml").read_text(encoding="utf-8").strip().endswith("enforcement_scripts=[]")
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_rejects_green_corpus_tamper(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "evolve_corpus", "cases", "known_good_minimal.json").write_text(
                '{"case_id":"tampered"}\n',
                encoding="utf-8",
            )
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.5.2"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tamper with green corpus before verifying",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert any("green support file changed" in item for item in session["session_rejections"])
    assert session["verification"] == []
    assert "session rejected before verification" in session["verification_skipped_reason"]
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_verification_runs_in_clean_exam_mirror(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    verify_cwds: list[Path] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.5.2"\n', encoding="utf-8")
            Path(cwd, "pytest.py").write_text("raise RuntimeError('shadowed')\n", encoding="utf-8")
        elif isinstance(command, list):
            verify_cwd = Path(cwd)
            verify_cwds.append(verify_cwd)
            assert env["PYTHONPATH"] == str(verify_cwd)
            assert not (verify_cwd / "pytest.py").exists()
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Verify in a clean exam mirror",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    paths = get_paths(tmp_path)

    assert session["status"] == "ready"
    assert session["promotable"] is True
    assert verify_cwds
    assert Path(session["verification_root"]) in verify_cwds
    assert Path(session["verification_root"]).with_name("verify-blue") in verify_cwds
    assert all(path != paths.green_root for path in verify_cwds)
    assert (paths.green_root / "pytest.py").exists()
    assert not (Path(session["verification_root"]) / "pytest.py").exists()


def test_evolve_run_rejects_verification_sandbox_drift(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.5.2"\n', encoding="utf-8")
        elif isinstance(command, list):
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.5.3"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Let verification mutate green after delta capture",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert any("verification sandbox content changed" in item for item in session["session_rejections"])
    assert session["verification_sandbox_rejections"]
    assert not session["delta_drift_rejections"]
    assert session["delta"]["changed_files"] == ["thomas/__init__.py"]
    assert session["post_verification_delta"]["changed_files"] == ["thomas/__init__.py"]
    assert session["verified_delta_fingerprint"] == session["post_verification_delta_fingerprint"]
    assert session["verification_delta_fingerprint"] != session["post_verification_sandbox_fingerprint"]
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_blocks_py_compile_only_verification(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas" / "core").mkdir()
    (tmp_path / "thomas" / "core" / "__init__.py").write_text("", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "core", "untested.py").write_text("VALUE = 1\n", encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(
        evolve_runtime,
        "_build_verify_commands",
        lambda charter, delta, repo_root, *, goal="", acceptance_checks=None: [
            [sys.executable, "-m", "py_compile", "thomas/core/untested.py"]
        ],
    )

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Add untested module",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "verification_failed"
    assert session["verification"] == []
    assert session["verification_floor_failures"] == [
        "no blast-radius tests selected for changed Python files: thomas/core/untested.py"
    ]
    assert "verification floor failed before subprocess verification" in session["verification_skipped_reason"]
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert not (tmp_path / "thomas" / "core" / "untested.py").exists()


def test_evolve_run_blocks_import_only_blast_radius_spoof(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    feature_root = tmp_path / "thomas" / "feature"
    feature_root.mkdir()
    (feature_root / "__init__.py").write_text("", encoding="utf-8")
    (feature_root / "payments.py").write_text("def charge(x):\n    return x\n", encoding="utf-8")
    (tmp_path / "tests" / "test_payments.py").write_text(
        "from thomas.feature import payments\n\n\ndef test_import_only():\n    assert payments\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "feature", "payments.py").write_text(
                "def charge(x):\n    return x * 999\n",
                encoding="utf-8",
            )
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Change payments behind an import-only test",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "verification_failed"
    assert session["verification"] == []
    assert len(session["verification_floor_failures"]) == 1
    assert "no changed executable lines covered" in session["verification_floor_failures"][0]
    assert "thomas/feature/payments.py" in session["verification_floor_failures"][0]
    assert "verification floor failed before subprocess verification" in session["verification_skipped_reason"]
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert (tmp_path / "thomas" / "feature" / "payments.py").read_text(encoding="utf-8") == (
        "def charge(x):\n    return x\n"
    )


def test_evolve_run_blocks_rename_to_escape_blast_radius_tests(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    core_root = tmp_path / "thomas" / "core"
    core_root.mkdir()
    (core_root / "__init__.py").write_text("", encoding="utf-8")
    (core_root / "covered.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_core_covered.py").write_text(
        "from thomas.core import covered\n\n\ndef test_value():\n    assert covered.VALUE == 1\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "core", "covered.py").unlink()
            Path(cwd, "thomas", "core", "renamed.py").write_text("VALUE = 2\n", encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Rename around blast-radius tests",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "verification_failed"
    assert session["verification_floor_failures"] == [
        "no blast-radius tests selected for changed Python files: thomas/core/renamed.py"
    ]
    assert session["verification"] == []
    assert "verification floor failed before subprocess verification" in session["verification_skipped_reason"]
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert (tmp_path / "thomas" / "core" / "covered.py").exists()
    assert not (tmp_path / "thomas" / "core" / "renamed.py").exists()


def test_evolve_run_syncs_stale_architecture_debt_after_refactor(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    cli_root = tmp_path / "thomas" / "cli"
    cli_root.mkdir(parents=True)
    (cli_root / "repl.py").write_text("\n".join("x = 1" for _ in range(900)), encoding="utf-8")
    (cli_root / "still_big.py").write_text("\n".join("y = 1" for _ in range(900)), encoding="utf-8")
    (tmp_path / "thomas" / "_architecture.py").write_text(
        (
            "MODULES = {\n"
            '    "cli": {\n'
            '        "tier": "core",\n'
            '        "depends_on": [],\n'
            '        "health": "yellow",\n'
            '        "debt": "repl.py exceeds 900 lines, still_big.py exceeds 900 lines",\n'
            '        "description": "cli",\n'
            "    },\n"
            "}\n"
            'RULES = {"max_new_file_lines": 800}\n'
        ),
        encoding="utf-8",
    )
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["thomas/_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "cli", "repl.py").write_text("x = 1\n", encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Split oversized repl",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "policy_violation"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["policy_violations"] == ["thomas/_architecture.py"]
    assert session["tamper_count"] == 1
    assert session["architecture_sync"]["changed_files"] == ["thomas/_architecture.py"]
    assert session["architecture_sync"]["removed"] == [{"module": "cli", "path": "repl.py"}]
    arch_text = (tmp_path / "thomas" / "_architecture.py").read_text(encoding="utf-8")
    assert "repl.py exceeds 900 lines" in arch_text
    assert "still_big.py exceeds 900 lines" in arch_text
    assert len((tmp_path / "thomas" / "cli" / "repl.py").read_text(encoding="utf-8").splitlines()) == 900


def test_evolve_run_does_not_bless_agent_architecture_edits(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    original_arch = (
        "MODULES = {\n"
        '    "cli": {\n'
        '        "tier": "core",\n'
        '        "depends_on": [],\n'
        '        "health": "yellow",\n'
        '        "debt": "repl.py exceeds 900 lines",\n'
        '        "description": "cli",\n'
        "    },\n"
        "}\n"
        'RULES = {"max_new_file_lines": 800}\n'
    )
    (tmp_path / "thomas" / "_architecture.py").write_text(original_arch, encoding="utf-8")
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["thomas/_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.2.0"\n', encoding="utf-8")
            Path(cwd, "thomas", "_architecture.py").write_text(
                original_arch.replace("repl.py exceeds 900 lines", "maliciously cleared"),
                encoding="utf-8",
            )
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Try to self-approve architecture debt removal",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["architecture_sync"]["skipped_reason"] == "architecture_already_changed"
    assert session["policy_violations"] == ["thomas/_architecture.py"]
    assert "thomas/_architecture.py" not in session["changed_files"]
    assert session["status"] == "policy_violation"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert (tmp_path / "thomas" / "_architecture.py").read_text(encoding="utf-8") == original_arch
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_only_syncs_debt_for_changed_files(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    cli_root = tmp_path / "thomas" / "cli"
    cli_root.mkdir(parents=True)
    (cli_root / "repl.py").write_text("x = 1\n", encoding="utf-8")
    original_arch = (
        "MODULES = {\n"
        '    "cli": {\n'
        '        "tier": "core",\n'
        '        "depends_on": [],\n'
        '        "health": "yellow",\n'
        '        "debt": "repl.py exceeds 900 lines",\n'
        '        "description": "cli",\n'
        "    },\n"
        "}\n"
        'RULES = {"max_new_file_lines": 800}\n'
    )
    (tmp_path / "thomas" / "_architecture.py").write_text(original_arch, encoding="utf-8")
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["thomas/_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.3.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Change an unrelated runtime file",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["architecture_sync"]["changed_files"] == []
    assert session["architecture_sync"]["removed"] == []
    assert session["promoted"] is True
    assert (tmp_path / "thomas" / "_architecture.py").read_text(encoding="utf-8") == original_arch


def test_auto_promote_calls_blue_only_supervisor_before_copying(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    supervisor_calls: list[dict[str, object]] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "7.7.7"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def reject_candidate(paths, expected_delta, session_payload, *, candidate_dirname="promote-candidate"):
        supervisor_calls.append(
            {
                "candidate_dirname": candidate_dirname,
                "changed_files": list(expected_delta.get("changed_files") or []),
                "promotable": bool(session_payload.get("promotable")),
            }
        )
        return {
            "ok": False,
            "risk_floor": "critical",
            "delta": {"changed_files": list(expected_delta.get("changed_files") or [])},
            "findings": [{"code": "forced_reject", "severity": "reject", "path": "thomas/__init__.py"}],
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "_evaluate_promotion_candidate", reject_candidate)

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prove auto promote uses the blue supervisor",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert supervisor_calls == [
        {
            "candidate_dirname": "promote-candidate-auto",
            "changed_files": ["thomas/__init__.py"],
            "promotable": True,
        }
    ]
    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["supervisor_verdict"]["ok"] is False
    assert any("forced_reject" in item for item in session["session_rejections"])
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_auto_promote_holds_non_python_delta_for_human_approval(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "README.md").write_text("blue docs\n", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.8.0"\n', encoding="utf-8")
            Path(cwd, "README.md").write_text("green docs\n", encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Change Python and docs together",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["supervisor_verdict"]["ok"] is True
    assert session["supervisor_verdict"]["risk_floor"] == "critical"
    assert any("critical risk floor" in item for item in session["session_rejections"])
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "blue docs\n"


def test_manual_promote_requires_explicit_critical_risk_ack(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.9.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def critical_candidate(paths, expected_delta, session_payload, *, candidate_dirname="promote-candidate"):
        _ = paths, session_payload, candidate_dirname
        return {
            "ok": True,
            "risk_floor": "critical",
            "delta": {"changed_files": list(expected_delta.get("changed_files") or [])},
            "findings": [],
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "_evaluate_promotion_candidate", critical_candidate)
    monkeypatch.setattr(
        evolve_runtime,
        "run_verifier_panel",
        lambda session_payload, *, supervisor_verdict, quorum=4: _FakeVerifierPanelResult(
            ok=True,
            pass_count=5,
            quorum=quorum,
        ),
    )

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prepare Python change for manual approval",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    runner = CliRunner()

    bare = runner.invoke(evolve, ["promote", session["session_id"], "--repo-root", str(tmp_path), "--json"])

    assert bare.exit_code != 0
    assert bare.exception is not None
    assert "critical risk floor" in str(bare.exception)
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'

    approved = runner.invoke(
        evolve,
        [
            "promote",
            session["session_id"],
            "--repo-root",
            str(tmp_path),
            "--approve-critical-risk",
            "--json",
        ],
    )

    assert approved.exit_code == 0, approved.output
    approved_payload = json.loads(approved.output)
    approved_session = approved_payload["session"]
    assert approved_session["status"] == "promoted"
    assert approved_session["supervisor_verdict"]["risk_floor"] == "critical"
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.9.0"'


def test_manual_promote_rejects_non_python_delta_without_dedicated_verifier(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "README.md").write_text("blue docs\n", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.9.0"\n', encoding="utf-8")
            Path(cwd, "README.md").write_text("green docs\n", encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def safe_candidate(paths, expected_delta, session_payload, *, candidate_dirname="promote-candidate"):
        _ = paths, session_payload, candidate_dirname
        return {
            "ok": True,
            "risk_floor": "low",
            "delta": {"changed_files": list(expected_delta.get("changed_files") or [])},
            "findings": [],
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "_evaluate_promotion_candidate", safe_candidate)
    monkeypatch.setattr(
        evolve_runtime,
        "run_verifier_panel",
        lambda session_payload, *, supervisor_verdict, quorum=4: _FakeVerifierPanelResult(
            ok=True,
            pass_count=5,
            quorum=quorum,
        ),
    )

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prepare mixed Python and docs change for manual approval",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]

    approved = CliRunner().invoke(
        evolve,
        [
            "promote",
            session["session_id"],
            "--repo-root",
            str(tmp_path),
            "--approve-critical-risk",
            "--json",
        ],
    )

    assert approved.exit_code != 0
    assert approved.exception is not None
    assert "non-Python delta requires a dedicated passing non-Python verifier" in str(approved.exception)
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "blue docs\n"


def test_auto_promote_runs_evolve_corpus_before_copying(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    corpus_roots: list[Path] = []

    class FailingCorpus:
        ok = False

        def to_dict(self):
            return {
                "ok": False,
                "case_count": 1,
                "cases": [
                    {
                        "case_id": "known_bad_import_swap",
                        "ok": False,
                        "expected": "reject",
                        "actual": "promote",
                        "details": {},
                    }
                ],
                "lock_errors": [],
            }

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.9.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    def failing_corpus(repo_root: Path):
        corpus_roots.append(Path(repo_root))
        return FailingCorpus()

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(evolve_runtime, "run_evolve_corpus", failing_corpus)

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prove corpus gates live promotion",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert corpus_roots == [tmp_path.resolve()]
    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["supervisor_verdict"]["evolve_corpus"]["ok"] is False
    assert any("blue evolve corpus rejected promotion" in item for item in session["session_rejections"])
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_defaults_to_codex_profile(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas.toml").write_text(
        '[models.local]\nprovider = "openai_compat"\nbase_url = "http://localhost:11434/v1"\nmodel = "qwen2.5-coder:7b"\n\n'
        '[models.codex]\nprovider = "codex"\nmodel = "gpt-5.3-codex"\n\ndefault_model = "codex"\n',
        encoding="utf-8",
    )
    seen_commands: list[list[str]] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list):
            seen_commands.append([str(part) for part in command])
            if "chat" in command:
                Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {
            "command": "ok",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(tmp_path, goal="Use the right model")
    session = payload["session"]

    chat_commands = [cmd for cmd in seen_commands if "chat" in cmd]
    assert chat_commands
    assert any(
        idx + 1 < len(cmd) and cmd[idx + 1] == "codex"
        for cmd in chat_commands
        for idx, part in enumerate(cmd[:-1])
        if part == "-m"
    )
    assert session["profile"] == "codex"


def test_evolve_profile_legacy_codex_alias_uses_openai_codex(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas.toml").write_text(
        'default_model = "local"\n\n'
        '[models.local]\nprovider = "openai_compat"\nbase_url = "http://localhost:11434/v1"\nmodel = "qwen2.5-coder:7b"\n\n'
        '[models.openai_codex]\nprovider = "openai_codex"\nmodel = "gpt-5.5"\n',
        encoding="utf-8",
    )

    assert evolve_runtime._resolve_evolve_profile(tmp_path, "codex") == "openai_codex"


def test_evolve_profile_env_legacy_codex_alias_uses_openai_codex(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas.toml").write_text(
        'default_model = "local"\n\n'
        '[models.local]\nprovider = "openai_compat"\nbase_url = "http://localhost:11434/v1"\nmodel = "qwen2.5-coder:7b"\n\n'
        '[models.openai_codex]\nprovider = "openai_codex"\nmodel = "gpt-5.5"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("THOMAS_DEFAULT_MODEL", "codex")

    assert evolve_runtime._resolve_evolve_profile(tmp_path, "") == "openai_codex"


def test_evolve_profile_legacy_codex_still_uses_named_codex_when_present(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas.toml").write_text(
        'default_model = "local"\n\n'
        '[models.local]\nprovider = "openai_compat"\nbase_url = "http://localhost:11434/v1"\nmodel = "qwen2.5-coder:7b"\n\n'
        '[models.codex]\nprovider = "codex"\nmodel = "gpt-5.3-codex"\n',
        encoding="utf-8",
    )

    assert evolve_runtime._resolve_evolve_profile(tmp_path, "codex") == "codex"


def test_evolve_run_routes_green_spend_to_main_repo_spend_file(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    seen_envs: list[dict[str, str]] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        _ = command, cwd, timeout_seconds
        seen_envs.append(dict(env))
        return {
            "command": "ok",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    evolve_runtime.run_evolve_session(tmp_path, goal="Track spend in main runtime")

    assert seen_envs
    assert any(env.get("THOMAS_SPEND_PATH") == str(tmp_path / "thomas_spend.jsonl") for env in seen_envs)
    assert any(env.get("THOMAS_EVOLVE_SPEND_WATCHDOG_ROOT") == str(tmp_path) for env in seen_envs)


def test_evolve_run_appends_blue_spend_reserve_after_green_child(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "evolve_governor.toml").write_text(
        (
            "[spend_governor]\n"
            "enabled = true\n"
            'ledger_path = "thomas_spend.jsonl"\n'
            "daily_usd_cap = 0.49\n"
            "total_usd_cap = 10.0\n"
            "per_iteration_usd_reserve = 0.25\n"
        ),
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        _ = env, timeout_seconds
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            return {
                "command": "chat",
                "returncode": 0,
                "stdout_tail": "",
                "stderr_tail": "",
                "timed_out": False,
                "usd_total": 999.0,
            }
        return {"command": "verify", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Meter green child spend from blue",
        refactor_first=False,
        passes=1,
    )
    session = payload["session"]
    ledger_rows = [
        json.loads(line)
        for line in (tmp_path / "thomas_spend.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert session["status"] == "ready"
    assert session["spend_governor_rejections"] == []
    assert session["spend_governor_checks"][0]["code"] == "within_budget"
    assert session["spend_ledger_writes"][0]["code"] == "ledger_appended"
    assert ledger_rows == [session["spend_ledger_writes"][0]["entry"]]
    assert ledger_rows[0]["source"] == "blue_evolve_child_reserve"
    assert ledger_rows[0]["phase"] == "creative"
    assert ledger_rows[0]["session_id"] == session["session_id"]
    assert ledger_rows[0]["usd_total"] == 0.25
    assert evaluate_spend_governor(tmp_path, today=ledger_rows[0]["day"]).code == "daily_cap_exceeded"


def test_evolve_run_blocks_second_green_child_after_blue_spend_reserve(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "evolve_governor.toml").write_text(
        (
            "[spend_governor]\n"
            "enabled = true\n"
            'ledger_path = "thomas_spend.jsonl"\n'
            "daily_usd_cap = 0.49\n"
            "total_usd_cap = 10.0\n"
            "per_iteration_usd_reserve = 0.25\n"
        ),
        encoding="utf-8",
    )
    chat_calls = 0

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        nonlocal chat_calls
        _ = env, timeout_seconds
        if isinstance(command, list) and "chat" in command:
            chat_calls += 1
            Path(cwd, "thomas", "__init__.py").write_text(f'__version__ = "0.1.{chat_calls}"\n', encoding="utf-8")
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        raise AssertionError("verification should not run after spend governor rejects the session")

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Stop when blue spend cap is consumed",
        refactor_first=False,
        passes=2,
    )
    session = payload["session"]

    assert chat_calls == 1
    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert len(session["pass_results"]) == 1
    assert len(session["spend_ledger_writes"]) == 1
    assert session["spend_governor_checks"][0]["ok"] is True
    assert session["spend_governor_checks"][1]["ok"] is False
    assert session["spend_governor_checks"][1]["code"] == "daily_cap_exceeded"
    assert "daily evolve spend cap would be exceeded" in session["spend_governor_rejections"][0]
    assert "session rejected before verification" in session["verification_skipped_reason"]


def test_evolve_run_routes_green_secrets_to_main_repo_secret_store(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    memory_root = tmp_path / "runtime"
    (tmp_path / "thomas.toml").write_text(f'[memory]\nroot = "{memory_root.as_posix()}"\n', encoding="utf-8")
    seen: list[tuple[Path, dict[str, str], object]] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        _ = command, timeout_seconds
        seen.append((Path(cwd), dict(env), command))
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        return {
            "command": "ok",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(tmp_path, goal="Use main repo OAuth store", refactor_first=False)
    session = payload["session"]
    green_envs = [env for cwd, env, _command in seen if cwd == Path(session["green_root"])]
    green_commands = [command for cwd, _env, command in seen if cwd == Path(session["green_root"])]
    verify_envs = [env for cwd, env, _command in seen if cwd == Path(session["verification_root"])]

    assert green_envs
    assert all(env.get("THOMAS_MEMORY_ROOT") == str(get_paths(tmp_path).green_runtime) for env in green_envs)
    assert all(env.get("THOMAS_SECRET_ROOT") == str(memory_root / ".thomas") for env in green_envs)
    assert all(env.get("THOMAS_EVOLVE_SPEND_WATCHDOG_ROOT") == str(tmp_path) for env in green_envs)
    assert all(env.get("THOMAS_MAX_AGENT_ITERATIONS") == "4" for env in green_envs)
    assert all(env.get("THOMAS_EVOLVE_GREEN_RUNTIME_WRITES") == "1" for env in green_envs)
    assert all(env.get("THOMAS_TOOLS_ALLOW_SHELL") == "false" for env in green_envs)
    assert all(isinstance(command, list) and "--max-iterations" in command for command in green_commands)
    assert all(
        isinstance(command, list) and command[command.index("--max-iterations") + 1] == "4"
        for command in green_commands
    )
    assert all(
        isinstance(command, list) and command[command.index("--job-type") + 1] == "self_development"
        for command in green_commands
    )
    assert all(env.get("THOMAS_QUALITY_ENABLED") == "false" for env in green_envs)
    assert all(env.get("THOMAS_QUALITY_ENFORCE") == "false" for env in green_envs)
    assert all(env.get("THOMAS_QUALITY_MAX_AUTO_RETRIES") == "0" for env in green_envs)
    denylist = set(green_envs[0].get("THOMAS_TOOL_DENYLIST", "").split(","))
    assert {
        "git.status",
        "git.diff",
        "shell.exec",
        "ssh.exec",
        "flow_execute",
        "nodes_execute_node",
        "workflow_execution",
        "upgrade_promote_green_to_blue",
        "upgrade_sync_green_to_blue",
        "upgrade_run_green_tests",
    }.issubset(denylist)
    assert "code.search" not in denylist
    assert "fs.search" not in denylist
    assert verify_envs
    stripped_keys = {
        "THOMAS_SPEND_PATH",
        "THOMAS_EVOLVE_SPEND_WATCHDOG_ROOT",
        "THOMAS_MEMORY_ROOT",
        "THOMAS_SECRET_ROOT",
        "THOMAS_EVOLVE_GREEN_RUNTIME_WRITES",
        "THOMAS_TOOLS_ALLOW_SHELL",
        "THOMAS_TOOL_ALLOWLIST",
        "THOMAS_TOOL_DENYLIST",
        "THOMAS_MAX_AGENT_ITERATIONS",
        "THOMAS_SELF_DEVELOPMENT_WRITE_GUARD_LIMIT",
        "THOMAS_QUALITY_ENABLED",
        "THOMAS_QUALITY_ENFORCE",
        "THOMAS_QUALITY_MAX_AUTO_RETRIES",
    }
    assert all(stripped_keys.isdisjoint(env) for env in verify_envs)


def test_cli_tool_denylist_env_filters_registered_tools(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    monkeypatch.setenv("THOMAS_TOOL_DENYLIST", "git.status,code.search,fs.search")
    config = load_config(tmp_path / "thomas.toml")

    registry = cli_commands_base._build_tools(config)

    assert registry.get("git.status") is None
    assert registry.get("code.search") is None
    assert registry.get("fs.search") is None
    assert registry.get("fs.read_file") is not None
    assert registry.get("diff.create") is not None


def test_evolve_green_tool_policy_removes_exec_primitives_even_when_shell_is_configured(
    tmp_path: Path, monkeypatch
) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas.toml").write_text("[tools]\nallow_shell = true\n", encoding="utf-8")
    green_env = evolve_runtime._evolve_child_env()
    evolve_runtime._merge_tool_denylist(green_env)
    monkeypatch.setenv("THOMAS_TOOLS_ALLOW_SHELL", green_env["THOMAS_TOOLS_ALLOW_SHELL"])
    monkeypatch.setenv("THOMAS_TOOL_DENYLIST", green_env["THOMAS_TOOL_DENYLIST"])
    config = load_config(tmp_path / "thomas.toml")

    registry = cli_commands_base._build_tools(config)

    assert config.tools.allow_shell is False
    for tool_name in (
        "shell.exec",
        "ssh.exec",
        "flow_execute",
        "nodes_execute_node",
        "workflow_execution",
        "upgrade_promote_green_to_blue",
        "upgrade_sync_green_to_blue",
        "upgrade_run_green_tests",
    ):
        assert registry.get(tool_name) is None
    assert registry.get("fs.read_file") is not None
    assert registry.get("diff.create") is not None


def test_evolve_run_skips_verification_after_agent_failure(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    calls: list[Path] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        _ = env, timeout_seconds
        calls.append(Path(cwd))
        if isinstance(command, list) and "chat" in command:
            return {
                "command": "chat",
                "returncode": 124,
                "stdout_tail": "timed out",
                "stderr_tail": "",
                "timed_out": True,
            }
        raise AssertionError("verification should not run after an agent failure")

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prove failed agent runs do not spend time verifying",
        refactor_first=False,
    )
    session = payload["session"]

    assert calls == [Path(session["green_root"])]
    assert session["status"] == "agent_failed"
    assert session["promotable"] is False
    assert session["verification"] == []
    assert session["verification_skipped_reason"] == "agent pass failed before verification"


def test_evolve_run_skips_verification_when_agent_makes_no_delta(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    calls: list[Path] = []
    commands: list[object] = []
    envs: list[dict[str, str]] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        _ = env, timeout_seconds
        calls.append(Path(cwd))
        commands.append(command)
        envs.append(dict(env))
        if isinstance(command, list) and "chat" in command:
            return {
                "command": "chat",
                "returncode": 0,
                "stdout_tail": "NO_ELIGIBLE_CHANGE: no safe edit",
                "stderr_tail": "",
                "timed_out": False,
            }
        raise AssertionError("verification should not run when there is no candidate delta")

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prove no-change sessions do not spend time verifying",
        refactor_first=False,
    )
    session = payload["session"]

    assert calls == [Path(session["green_root"]), Path(session["green_root"])]
    assert isinstance(commands[0], list)
    assert isinstance(commands[1], list)
    assert commands[0][commands[0].index("--max-iterations") + 1] == "4"
    assert commands[1][commands[1].index("--max-iterations") + 1] == "6"
    assert commands[0][commands[0].index("--job-type") + 1] == "self_development"
    assert commands[1][commands[1].index("--job-type") + 1] == "self_development"
    assert envs[0].get("THOMAS_SELF_DEVELOPMENT_WRITE_GUARD_LIMIT") is None
    assert envs[1].get("THOMAS_SELF_DEVELOPMENT_WRITE_GUARD_LIMIT") == "2"
    assert session["no_change_retry_attempted"] is True
    assert session["pass_results"][1]["retry_reason"] == "no_candidate_changes"
    assert "write-or-refuse" in session["pass_results"][1]["prompt"]
    assert "at most one targeted `code.search` call" in session["pass_results"][1]["prompt"]
    assert "at most one bounded `fs.read_file` call" in session["pass_results"][1]["prompt"]
    assert "do not call `fs.search`, `git.status`, `shell.exec`" in session["pass_results"][1]["prompt"]
    assert "single optional `code.search` call" in session["pass_results"][1]["prompt"]
    assert "copy `old_str` exactly from the `fs.read_file` output" in session["pass_results"][1]["prompt"]
    assert "must be `diff.create` or `fs.write_file`" in session["pass_results"][1]["prompt"]
    assert "`shell.exec` is unavailable; if `diff.create` fails" in session["pass_results"][1]["prompt"]
    assert "Only run verification after a write tool succeeds" in session["pass_results"][1]["prompt"]
    assert session["status"] == "no_change"
    assert session["promotable"] is False
    assert session["verification"] == []
    assert session["verification_skipped_reason"] == "no candidate changes before verification"


def test_evolve_run_retries_no_change_once_and_verifies_rescued_delta(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    chat_calls = 0
    verify_calls = 0

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        nonlocal chat_calls, verify_calls
        _ = env, timeout_seconds
        if isinstance(command, list) and "chat" in command:
            chat_calls += 1
            if chat_calls == 2:
                Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            return {
                "command": "chat",
                "returncode": 0,
                "stdout_tail": "ok",
                "stderr_tail": "",
                "timed_out": False,
            }
        verify_calls += 1
        return {
            "command": "verify",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Prove no-change retry can produce a candidate delta",
        refactor_first=False,
    )
    session = payload["session"]

    assert chat_calls == 2
    assert verify_calls >= 1
    assert session["no_change_retry_attempted"] is True
    assert session["pass_results"][1]["retry_reason"] == "no_candidate_changes"
    assert session["status"] == "ready"
    assert session["promotable"] is True
    assert session["changed_files"] == ["thomas/__init__.py"]
