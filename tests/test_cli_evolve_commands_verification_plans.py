"""Evolve's verification plans: charter commands, semantic deltas, acceptance checks and their verifiers.

Split from test_cli_evolve_commands.py on 2026-09-07 so each file stays under the monolith guard's limit.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from tests._cli_evolve_fakes import _seed_repo
from thomas.cli.commands.evolve import evolve
from thomas.forge.anvil import evolve as evolve_runtime


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
