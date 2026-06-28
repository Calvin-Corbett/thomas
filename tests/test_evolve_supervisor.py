from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import evolve_supervisor
import evolve_supervisor.coverage_floor as coverage_floor
from evolve_supervisor import (
    ACTION_APPROVE,
    ACTION_PROMOTE,
    ACTION_REJECT,
    WATCHDOG_RETURN_CODE,
    SpendGovernorVerdict,
    evaluate_candidate,
    evaluate_spend_governor,
    monitor_process_with_spend_watchdog,
    record_evolve_child_spend,
    run_evolve_corpus,
    run_verifier_panel,
)
from evolve_supervisor.coverage_floor import (
    execution_coverage_failures,
    select_blast_radius_tests,
    select_dependent_smoke_tests,
)

from thomas.forge.anvil import doppelganger, evolve_autonomy, evolve_loop


def _write_locked_corpus(root: Path) -> None:
    corpus = root / "evolve_corpus"
    cases = corpus / "cases"
    cases.mkdir(parents=True)
    (cases / "known_good_minimal.json").write_text(
        json.dumps({"case_id": "known_good_minimal", "expected": "promote_or_hold"}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256((cases / "known_good_minimal.json").read_bytes()).hexdigest()
    (corpus / "LOCK.json").write_text(
        json.dumps(
            {
                "version": 1,
                "files": {
                    "cases/known_good_minimal.json": digest,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _seed_pair(root: Path) -> tuple[Path, Path]:
    blue = root / "blue"
    green = root / "green"
    for base in (blue, green):
        (base / "thomas").mkdir(parents=True)
        (base / "tests").mkdir()
        (base / "thomas" / "__init__.py").write_text('__version__ = "0.0.0"\n', encoding="utf-8")
        (base / "tests" / "test_architecture.py").write_text(
            "import thomas\n\n\ndef test_gate():\n    assert thomas.__version__\n",
            encoding="utf-8",
        )
        (base / "pyproject.toml").write_text('[project]\nname = "thomas"\n', encoding="utf-8")
        (base / "agent_safety.toml").write_text(
            (
                "[project]\n"
                'test_dirs = ["tests/"]\n\n'
                "[protected]\n"
                "policy_files=[]\n"
                "guardrails_files=[]\n"
                'enforcement_files=["tests/test_architecture.py"]\n'
                "enforcement_scripts=[]\n"
            ),
            encoding="utf-8",
        )
    _write_locked_corpus(blue)
    shutil.copytree(blue / "evolve_corpus", green / "evolve_corpus")
    return blue, green


def _codes(verdict) -> set[str]:
    return {finding.code for finding in verdict.findings}


class _FakeHangingProcess:
    pid = 12345

    def __init__(self) -> None:
        self.returncode = None
        self.killed = False

    def communicate(self, *, timeout=None):
        if self.killed:
            self.returncode = -9
            return "stdout after kill", "stderr before kill"
        raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout, output="stdout partial", stderr="stderr partial")

    def poll(self):
        return None if not self.killed else self.returncode


class _FakeFinishedProcess:
    pid = 12346
    returncode = 0

    def communicate(self, *, timeout=None):
        return "done", ""

    def poll(self):
        return self.returncode


def test_supervisor_package_is_support_only_not_promotable_scope() -> None:
    assert "evolve_supervisor" not in doppelganger._INCLUDE_DIRS
    assert "evolve_supervisor" not in doppelganger._INCLUDE_FILES
    assert "evolve_supervisor" in doppelganger._GREEN_SUPPORT_DIRS
    assert "evolve_corpus" not in doppelganger._INCLUDE_DIRS
    assert "evolve_corpus" in doppelganger._GREEN_SUPPORT_DIRS


def test_decision_matrix_is_supervisor_owned_and_old_paths_delegate() -> None:
    assert evolve_supervisor.decide_for_session.__module__ == "evolve_supervisor.decision"
    assert evolve_autonomy.decide_for_session is evolve_supervisor.decide_for_session
    assert evolve_loop.decide_for_session is evolve_supervisor.decide_for_session


def test_supervisor_decision_matrix_blocks_untrusted_sessions() -> None:
    clean = dict(
        posture="auto_safe",
        risk_tier="low",
        verification_ok=True,
        changed_count=1,
        policy_violation=False,
    )
    assert evolve_supervisor.decide_promotion(**clean).action == ACTION_PROMOTE

    unverified = evolve_supervisor.decide_promotion(**dict(clean, verification_ran=False))
    assert unverified.action == ACTION_APPROVE
    assert "no verification ran" in unverified.reason

    floor_failed = evolve_supervisor.decide_promotion(
        **dict(clean, verification_ok=False, verification_floor_failed=True),
    )
    assert floor_failed.action == ACTION_REJECT
    assert "verification floor" in floor_failed.reason


def test_supervisor_decision_treats_baseline_failed_charter_checks_as_advisory() -> None:
    session = {
        "status": "ready",
        "delta": {"changed_count": 1},
        "policy_violations": [],
        "verification": [
            {"source": "generated", "returncode": 0},
            {"source": "charter", "returncode": 1, "baseline_returncode": 1},
        ],
    }

    decision = evolve_supervisor.decide_for_session("auto_safe", session, "low")

    assert decision.action == ACTION_PROMOTE


def test_supervisor_decision_rejects_unsafe_charter_verify_failures() -> None:
    session = {
        "status": "ready",
        "delta": {"changed_count": 1},
        "policy_violations": [],
        "verification": [
            {"source": "generated", "returncode": 0},
            {"source": "charter_unsafe", "returncode": 2},
        ],
    }

    decision = evolve_supervisor.decide_for_session("auto_safe", session, "low")

    assert decision.action == ACTION_REJECT
    assert "verification failed" in decision.reason


def test_decision_holds_supervisor_critical_risk_floor_even_in_autonomous() -> None:
    session = {
        "status": "ready",
        "delta": {"changed_count": 1, "changed_files": ["thomas/core/example.py"]},
        "policy_violations": [],
        "session_rejections": [],
        "verification": [{"source": "generated", "returncode": 0}],
        "supervisor_verdict": {
            "ok": True,
            "risk_floor": "critical",
            "delta": {
                "changed_count": 1,
                "changed_files": ["thomas/core/example.py"],
            },
            "findings": [],
        },
    }

    decision = evolve_supervisor.decide_for_session("autonomous", session, "low")

    assert decision.action == ACTION_APPROVE
    assert "risk floor critical" in decision.reason
    assert decision.risk_tier == "critical"


def test_decision_holds_loop_file_changes_without_trusting_planner_risk() -> None:
    session = {
        "status": "ready",
        "delta": {
            "changed_count": 1,
            "changed_files": ["thomas/forge/anvil/evolve_planner_detectors.py"],
        },
        "policy_violations": [],
        "session_rejections": [],
        "verification": [{"source": "generated", "returncode": 0}],
    }

    decision = evolve_supervisor.decide_for_session("autonomous", session, "low")

    assert decision.action == ACTION_APPROVE
    assert "evolve-loop file" in decision.reason
    assert decision.risk_tier == "critical"


def test_decision_holds_non_python_deltas_for_human_approval() -> None:
    session = {
        "status": "ready",
        "delta": {
            "changed_count": 2,
            "changed_files": ["thomas/__init__.py", "README.md"],
        },
        "policy_violations": [],
        "session_rejections": [],
        "verification": [{"source": "generated", "returncode": 0}],
    }

    decision = evolve_supervisor.decide_for_session("autonomous", session, "low")

    assert decision.action == ACTION_APPROVE
    assert "non-Python delta" in decision.reason
    assert decision.risk_tier == "critical"


def test_verifier_panel_passes_clean_verified_candidate(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    (green / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    verdict = evaluate_candidate(blue, green)
    session = {
        "status": "ready",
        "delta": {"changed_count": 1, "changed_files": ["thomas/__init__.py"]},
        "policy_violations": [],
        "session_rejections": [],
        "verification": [{"source": "generated", "returncode": 0}],
    }

    panel = run_verifier_panel(session, supervisor_verdict=verdict)

    assert panel.ok is True
    assert panel.pass_count >= panel.quorum
    assert panel.critical_dissent_count == 0


def test_verifier_panel_accepts_stored_supervisor_verdict_dict(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    (green / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    verdict = evaluate_candidate(blue, green)
    session = {
        "status": "promoted",
        "delta": {"changed_count": 1, "changed_files": ["thomas/__init__.py"]},
        "policy_violations": [],
        "session_rejections": [],
        "verification": [{"source": "generated", "returncode": 0}],
    }

    panel = run_verifier_panel(session, supervisor_verdict=verdict.to_dict())

    assert panel.ok is True
    votes = {vote.role: vote for vote in panel.votes}
    assert votes["security"].status == "pass"


def test_verifier_panel_holds_missing_verification() -> None:
    session = {
        "status": "ready",
        "delta": {"changed_count": 1, "changed_files": ["thomas/__init__.py"]},
        "policy_violations": [],
        "session_rejections": [],
        "verification": [],
    }

    panel = run_verifier_panel(session)

    assert panel.ok is False
    votes = {vote.role: vote for vote in panel.votes}
    assert votes["correctness"].status == "hold"
    assert votes["regression"].status == "hold"
    assert votes["reward_hack"].status == "hold"


def test_verifier_panel_rejects_exam_suppression_candidate(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    (green / "tests" / "test_architecture.py").write_text("def test_gate():\n    pass\n", encoding="utf-8")
    verdict = evaluate_candidate(blue, green)
    session = {
        "status": "ready",
        "delta": {"changed_count": 1, "changed_files": ["tests/test_architecture.py"]},
        "policy_violations": [],
        "session_rejections": [],
        "verification": [{"source": "generated", "returncode": 0}],
    }

    panel = run_verifier_panel(session, supervisor_verdict=verdict)

    assert panel.ok is False
    assert panel.critical_dissent_count >= 1
    votes = {vote.role: vote for vote in panel.votes}
    assert votes["security"].status == "reject"
    assert votes["reward_hack"].status == "reject"


def test_verifier_panel_rejects_stored_exam_suppression_verdict_dict(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    (green / "tests" / "test_architecture.py").write_text("def test_gate():\n    pass\n", encoding="utf-8")
    verdict = evaluate_candidate(blue, green)
    session = {
        "status": "ready",
        "delta": {"changed_count": 1, "changed_files": ["tests/test_architecture.py"]},
        "policy_violations": [],
        "session_rejections": [],
        "verification": [{"source": "generated", "returncode": 0}],
    }

    panel = run_verifier_panel(session, supervisor_verdict=verdict.to_dict())

    assert panel.ok is False
    votes = {vote.role: vote for vote in panel.votes}
    assert votes["security"].status == "reject"
    assert votes["reward_hack"].status == "reject"


def test_supervisor_rederives_delta_and_ignores_agent_session_json(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    (green / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={
            "delta": {"changed_count": 0, "changed_files": []},
            "verification": [{"command": "fake", "returncode": 0}],
            "promotable": True,
        },
    )

    assert verdict.ok is True
    assert verdict.delta.modified == ("thomas/__init__.py",)
    assert set(verdict.ignored_session_keys) == {"delta", "promotable", "verification"}


def test_supervisor_holds_mixed_python_and_non_python_delta(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    for base in (blue, green):
        (base / "README.md").write_text("blue docs\n", encoding="utf-8")
    (green / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    (green / "README.md").write_text("green docs\n", encoding="utf-8")

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={"verification": [{"source": "generated", "returncode": 0}], "promotable": True},
    )

    assert verdict.ok is True
    assert verdict.risk_floor == "critical"
    assert "verification_floor_missing" not in _codes(verdict)
    assert "protected_path_changed" not in _codes(verdict)


def test_supervisor_rejects_faked_success_when_no_delta_exists(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={
            "delta": {"changed_count": 1, "changed_files": ["thomas/__init__.py"]},
            "verification": [{"command": "pytest", "returncode": 0}],
            "promotable": True,
        },
    )

    assert verdict.ok is False
    assert verdict.delta.changed_count == 0
    assert "no_rederived_changes" in _codes(verdict)


def test_supervisor_rejects_exam_suppression_from_green_tree(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    (green / "tests" / "test_architecture.py").write_text("def test_gate():\n    pass\n", encoding="utf-8")

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={"verification": [{"command": "pytest", "returncode": 0}], "promotable": True},
    )

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert {"protected_path_changed", "test_infra_changed"} <= _codes(verdict)


def test_supervisor_rejects_runtime_filesystem_guard_mutation_even_with_blast_radius(
    tmp_path: Path,
) -> None:
    blue, green = _seed_pair(tmp_path)
    for base in (blue, green):
        guard = base / "thomas" / "tools" / "filesystem.py"
        guard.parent.mkdir(parents=True)
        guard.write_text("PROTECTED = True\n", encoding="utf-8")
        (base / "tests" / "test_filesystem_guard.py").write_text(
            "from thomas.tools import filesystem\n\n\ndef test_guard_exists():\n    assert filesystem.PROTECTED\n",
            encoding="utf-8",
        )
    (green / "thomas" / "tools" / "filesystem.py").write_text("PROTECTED = False\n", encoding="utf-8")

    verdict = evaluate_candidate(
        blue,
        green,
        claimed_category="refactor",
        claimed_risk="low",
        session_payload={"verification": [{"source": "generated", "returncode": 0}], "promotable": True},
    )

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "protected_path_changed" in _codes(verdict)
    assert "verification_floor_missing" not in _codes(verdict)


def test_supervisor_allows_existing_loop_package_change_with_blast_radius(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    for base in (blue, green):
        loop_dir = base / "thomas" / "forge" / "anvil"
        loop_dir.mkdir(parents=True)
        (loop_dir / "evolve_planner_models.py").write_text("CATEGORY_RISK = {'meta': 'low'}\n", encoding="utf-8")
        (base / "tests" / "test_evolve_planner_models.py").write_text(
            "from thomas.forge.anvil import evolve_planner_models\n\n\n"
            "def test_category_risk_exists():\n"
            "    assert evolve_planner_models.CATEGORY_RISK\n",
            encoding="utf-8",
        )
    (green / "thomas" / "forge" / "anvil" / "evolve_planner_models.py").write_text(
        "CATEGORY_RISK = {'meta': 'low', 'security': 'low'}\n",
        encoding="utf-8",
    )

    verdict = evaluate_candidate(
        blue,
        green,
        claimed_category="refactor",
        claimed_risk="low",
        session_payload={"risk_tier": "low", "promotable": True},
    )

    assert verdict.ok is True
    assert verdict.risk_floor == "critical"
    assert "loop_package_new_file" not in _codes(verdict)
    assert "protected_path_changed" not in _codes(verdict)


def test_blast_radius_selects_facade_tests_for_planner_detector(tmp_path: Path) -> None:
    anvil = tmp_path / "thomas" / "forge" / "anvil"
    anvil.mkdir(parents=True)
    (tmp_path / "thomas" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "thomas" / "forge" / "__init__.py").write_text("", encoding="utf-8")
    (anvil / "__init__.py").write_text("", encoding="utf-8")
    (anvil / "evolve_planner_detectors.py").write_text("def collect_candidates():\n    return []\n", encoding="utf-8")
    (anvil / "evolve_planner.py").write_text(
        "def plan_backlog():\n"
        "    from .evolve_planner_detectors import collect_candidates\n"
        "    return collect_candidates()\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_evolve_planner.py").write_text(
        "from thomas.forge.anvil.evolve_planner import plan_backlog\n\n\n"
        "def test_planner_facade():\n"
        "    assert plan_backlog\n",
        encoding="utf-8",
    )

    selected = select_blast_radius_tests(
        ["thomas/forge/anvil/evolve_planner_detectors.py"],
        tmp_path,
    )

    assert selected == ["tests/test_evolve_planner.py"]


def test_blast_radius_selects_direct_tests_for_script_modules(tmp_path: Path) -> None:
    workboard = tmp_path / "scripts" / "crew" / "workboard"
    workboard.mkdir(parents=True)
    for package in [
        tmp_path / "scripts",
        tmp_path / "scripts" / "crew",
        tmp_path / "scripts" / "crew" / "workboard",
    ]:
        (package / "__init__.py").write_text("", encoding="utf-8")
    (workboard / "message.py").write_text("def current_status():\n    return 'ok'\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_workboard_message_script.py").write_text(
        "from scripts.crew.workboard import message\n\n\n"
        "def test_message_script():\n"
        "    assert message.current_status() == 'ok'\n",
        encoding="utf-8",
    )

    selected = select_blast_radius_tests(
        ["scripts/crew/workboard/message.py"],
        tmp_path,
    )

    assert selected == ["tests/test_workboard_message_script.py"]


def test_coverage_probe_includes_script_modules_in_source(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, list[str]] = {}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(command, **_kwargs):
        captured["command"] = list(command)
        data_file = Path(command[command.index("--data-file") + 1])
        data_file.parent.mkdir(parents=True, exist_ok=True)
        data_file.write_text("", encoding="utf-8")
        return _Result()

    monkeypatch.setattr(coverage_floor.subprocess, "run", _fake_run)

    _data_file, error = coverage_floor._run_coverage_probe(
        tmp_path,
        ["tests/test_workboard_message_script.py"],
        timeout_seconds=1,
    )

    assert error == ""
    assert "--source=thomas,scripts" in captured["command"]


def test_blast_radius_keeps_direct_tests_ahead_of_symbol_import_dependents(tmp_path: Path) -> None:
    agent = tmp_path / "thomas" / "agent"
    agent.mkdir(parents=True)
    (tmp_path / "thomas" / "__init__.py").write_text("", encoding="utf-8")
    (agent / "__init__.py").write_text("", encoding="utf-8")
    (agent / "loop_tool_exec.py").write_text("def execute_tools():\n    return None\n", encoding="utf-8")
    for index in range(12):
        (agent / f"consumer_{index}.py").write_text(
            "from thomas.agent.loop_tool_exec import execute_tools\n",
            encoding="utf-8",
        )
    tests = tmp_path / "tests"
    tests.mkdir()
    for index in range(12):
        (tests / f"test_consumer_{index}.py").write_text(
            f"from thomas.agent.consumer_{index} import execute_tools\n\n\n"
            f"def test_consumer_{index}():\n"
            "    assert execute_tools is not None\n",
            encoding="utf-8",
        )
    (tests / "test_agent_loop_tool_exec.py").write_text(
        "from thomas.agent.loop_tool_exec import execute_tools\n\n\n"
        "def test_direct_loop_tool_exec():\n"
        "    assert execute_tools is not None\n",
        encoding="utf-8",
    )

    selected = select_blast_radius_tests(
        ["thomas/agent/loop_tool_exec.py"],
        tmp_path,
    )
    smoke = select_dependent_smoke_tests(
        ["thomas/agent/loop_tool_exec.py"],
        tmp_path,
        exclude=set(selected),
    )

    assert selected == ["tests/test_agent_loop_tool_exec.py"]
    assert len(smoke) == 3
    assert "tests/test_agent_loop_tool_exec.py" not in smoke
    assert all(path.startswith("tests/test_consumer_") for path in smoke)


def test_supervisor_rejects_new_loop_package_python_file(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    new_loop_file = green / "thomas" / "forge" / "anvil" / "evolve_fake_gate.py"
    new_loop_file.parent.mkdir(parents=True)
    new_loop_file.write_text("ALWAYS_PASS = True\n", encoding="utf-8")

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={"verification": [{"source": "generated", "returncode": 0}], "promotable": True},
    )

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "loop_package_new_file" in _codes(verdict)


def test_supervisor_rejects_green_side_supervisor_support_mutation(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    for base in (blue, green):
        supervisor_dir = base / "evolve_supervisor"
        supervisor_dir.mkdir()
        (supervisor_dir / "__init__.py").write_text("VERSION = 'blue'\n", encoding="utf-8")
    (green / "evolve_supervisor" / "__init__.py").write_text("VERSION = 'green'\n", encoding="utf-8")

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={"verification": [{"command": "pytest", "returncode": 0}], "promotable": True},
    )

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "supervisor_package_changed" in _codes(verdict)


def test_supervisor_requires_locked_blue_corpus(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    (green / "evolve_corpus" / "LOCK.json").unlink()
    (green / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")

    verdict = evaluate_candidate(blue, green, session_payload={"promotable": True})

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "corpus_lock_missing" in _codes(verdict)


def test_supervisor_rejects_corpus_hash_mismatch(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    (green / "evolve_corpus" / "cases" / "known_good_minimal.json").write_text(
        '{"case_id":"known_good_minimal","expected":"tampered"}\n',
        encoding="utf-8",
    )
    (green / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")

    verdict = evaluate_candidate(blue, green, session_payload={"promotable": True})

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "corpus_hash_mismatch" in _codes(verdict)


def test_supervisor_rejects_candidate_corpus_tamper_behind_legit_change(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    (green / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    (green / "evolve_corpus" / "cases" / "known_good_minimal.json").write_text(
        '{"case_id":"known_good_minimal","expected":"tampered-candidate"}\n',
        encoding="utf-8",
    )

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={"verification": [{"source": "generated", "returncode": 0}], "promotable": True},
    )

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "corpus_hash_mismatch" in _codes(verdict)
    assert "evolve_corpus/cases/known_good_minimal.json" in verdict.delta.changed_files


def test_supervisor_rejects_unlocked_corpus_files(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    (green / "evolve_corpus" / "cases" / "unlocked.json").write_text('{"case_id":"unlocked"}\n', encoding="utf-8")
    (green / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")

    verdict = evaluate_candidate(blue, green, session_payload={"promotable": True})

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "corpus_unlocked_file" in _codes(verdict)


def test_supervisor_rejects_changed_python_without_candidate_blast_radius_tests(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    (green / "thomas" / "untested.py").write_text("VALUE = 1\n", encoding="utf-8")

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={"verification": [{"source": "generated", "returncode": 0}], "promotable": True},
    )

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "verification_floor_missing" in _codes(verdict)


def test_supervisor_rejects_name_only_blast_radius_spoof(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    for base in (blue, green):
        feature_dir = base / "thomas" / "feature"
        feature_dir.mkdir(parents=True)
        (feature_dir / "__init__.py").write_text("", encoding="utf-8")
        (feature_dir / "backdoor.py").write_text("VALUE = 1\n", encoding="utf-8")
        (base / "tests" / "test_backdoor_spoof.py").write_text(
            "def test_mentions_backdoor_name_only():\n"
            '    assert "thomas.feature.backdoor" == "thomas.feature.backdoor"\n',
            encoding="utf-8",
        )
    (green / "thomas" / "feature" / "backdoor.py").write_text("VALUE = 2\n", encoding="utf-8")

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={"verification": [{"source": "generated", "returncode": 0}], "promotable": True},
    )

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "verification_floor_missing" in _codes(verdict)
    assert "protected_path_changed" not in _codes(verdict)


def test_supervisor_rejects_import_only_test_without_changed_line_execution(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    for base in (blue, green):
        feature_dir = base / "thomas" / "feature"
        feature_dir.mkdir(parents=True)
        (feature_dir / "__init__.py").write_text("", encoding="utf-8")
        (feature_dir / "payments.py").write_text("def charge(x):\n    return x\n", encoding="utf-8")
        (base / "tests" / "test_payments.py").write_text(
            "from thomas.feature import payments\n\n\ndef test_import_only():\n    assert payments\n",
            encoding="utf-8",
        )
    (green / "thomas" / "feature" / "payments.py").write_text(
        "def charge(x):\n    return x * 999\n",
        encoding="utf-8",
    )

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={"verification": [{"source": "generated", "returncode": 0}], "promotable": True},
    )

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "verification_floor_missing" in _codes(verdict)
    messages = "\n".join(finding.message for finding in verdict.findings)
    assert "no changed executable lines covered" in messages
    assert "thomas/feature/payments.py" in messages
    assert "protected_path_changed" not in _codes(verdict)


def test_supervisor_allows_test_that_executes_changed_line(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    for base in (blue, green):
        feature_dir = base / "thomas" / "feature"
        feature_dir.mkdir(parents=True)
        (feature_dir / "__init__.py").write_text("", encoding="utf-8")
        (feature_dir / "payments.py").write_text("def charge(x):\n    return x\n", encoding="utf-8")
        (base / "tests" / "test_payments.py").write_text(
            "from thomas.feature import payments\n\n\n"
            "def test_charge_executes_changed_line():\n"
            "    assert payments.charge(2) > 0\n",
            encoding="utf-8",
        )
    (green / "thomas" / "feature" / "payments.py").write_text(
        "def charge(x):\n    return x * 999\n",
        encoding="utf-8",
    )

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={"verification": [{"source": "generated", "returncode": 0}], "promotable": True},
    )

    assert verdict.ok is True
    assert verdict.risk_floor == "low"
    assert "verification_floor_missing" not in _codes(verdict)


def test_supervisor_rejects_failing_blast_radius_test_even_when_changed_line_executes(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    for base in (blue, green):
        feature_dir = base / "thomas" / "feature"
        feature_dir.mkdir(parents=True)
        (feature_dir / "__init__.py").write_text("", encoding="utf-8")
        (feature_dir / "payments.py").write_text("def charge(x):\n    return x\n", encoding="utf-8")
        (base / "tests" / "test_payments.py").write_text(
            "from thomas.feature import payments\n\n\n"
            "def test_charge_executes_changed_line_but_fails():\n"
            "    assert payments.charge(2) == 2\n",
            encoding="utf-8",
        )
    (green / "thomas" / "feature" / "payments.py").write_text(
        "def charge(x):\n    return x * 999\n",
        encoding="utf-8",
    )

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={"verification": [{"source": "generated", "returncode": 0}], "promotable": True},
    )

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "verification_floor_missing" in _codes(verdict)
    messages = "\n".join(finding.message for finding in verdict.findings)
    assert "blast-radius tests failed with returncode" in messages


def test_supervisor_rejects_failing_dependent_smoke_test_after_direct_coverage_passes(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    for base in (blue, green):
        feature_dir = base / "thomas" / "feature"
        feature_dir.mkdir(parents=True)
        (feature_dir / "__init__.py").write_text("", encoding="utf-8")
        (feature_dir / "core.py").write_text("def charge(x):\n    return x\n", encoding="utf-8")
        (feature_dir / "api.py").write_text(
            "from thomas.feature.core import charge\n\n\ndef quote(x):\n    return charge(x)\n",
            encoding="utf-8",
        )
        (base / "tests" / "test_core.py").write_text(
            "from thomas.feature import core\n\n\n"
            "def test_core_executes_changed_line():\n"
            "    assert core.charge(2) > 0\n",
            encoding="utf-8",
        )
        (base / "tests" / "test_api.py").write_text(
            "from thomas.feature import api\n\n\ndef test_api_facade_contract():\n    assert api.quote(2) == 2\n",
            encoding="utf-8",
        )
    (green / "thomas" / "feature" / "core.py").write_text(
        "def charge(x):\n    return x * 999\n",
        encoding="utf-8",
    )

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={"verification": [{"source": "generated", "returncode": 0}], "promotable": True},
    )

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "verification_floor_missing" in _codes(verdict)
    messages = "\n".join(finding.message for finding in verdict.findings)
    assert "dependent blast-radius smoke tests failed with returncode" in messages


def test_execution_coverage_floor_accepts_changed_script_module_with_direct_test(tmp_path: Path) -> None:
    blue = tmp_path / "blue"
    green = tmp_path / "green"
    for base, expression in [(blue, "x"), (green, "x + 1")]:
        workboard = base / "scripts" / "crew" / "workboard"
        workboard.mkdir(parents=True)
        for package in [
            base / "scripts",
            base / "scripts" / "crew",
            base / "scripts" / "crew" / "workboard",
        ]:
            (package / "__init__.py").write_text("", encoding="utf-8")
        (workboard / "message.py").write_text(
            f"def bump(x):\n    return {expression}\n",
            encoding="utf-8",
        )
        tests = base / "tests"
        tests.mkdir()
        (tests / "test_workboard_message_script.py").write_text(
            "from scripts.crew.workboard import message\n\n\n"
            "def test_message_script_executes_changed_line():\n"
            "    assert message.bump(2) == 3\n",
            encoding="utf-8",
        )

    failures = execution_coverage_failures(
        ["scripts/crew/workboard/message.py"],
        blue_root=blue,
        candidate_root=green,
        timeout_seconds=60,
    )

    assert failures == []


def test_supervisor_rederives_verification_floor_and_ignores_green_claim(tmp_path: Path) -> None:
    blue, green = _seed_pair(tmp_path)
    (green / "thomas" / "untested.py").write_text("VALUE = 1\n", encoding="utf-8")

    verdict = evaluate_candidate(
        blue,
        green,
        session_payload={
            "verification": [{"source": "generated", "returncode": 0}],
            "verification_floor_failures": [],
            "promotable": True,
        },
    )

    assert verdict.ok is False
    assert verdict.risk_floor == "critical"
    assert "verification_floor_missing" in _codes(verdict)
    assert "verification_floor_failures" in verdict.ignored_session_keys


def test_spend_governor_defaults_to_disabled_without_config(tmp_path: Path) -> None:
    verdict = evaluate_spend_governor(tmp_path, today="2026-06-22")

    assert verdict.ok is True
    assert verdict.enabled is False
    assert verdict.code == "config_missing"


def test_spend_governor_blocks_projected_daily_cap(tmp_path: Path) -> None:
    (tmp_path / "evolve_governor.toml").write_text(
        (
            "[spend_governor]\n"
            "enabled = true\n"
            'ledger_path = "thomas_spend.jsonl"\n'
            "daily_usd_cap = 1.0\n"
            "total_usd_cap = 10.0\n"
            "per_iteration_usd_reserve = 0.25\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "thomas_spend.jsonl").write_text(
        json.dumps({"day": "2026-06-22", "usd_total": 0.9}) + "\n",
        encoding="utf-8",
    )

    verdict = evaluate_spend_governor(tmp_path, today="2026-06-22")

    assert verdict.ok is False
    assert verdict.enabled is True
    assert verdict.code == "daily_cap_exceeded"
    assert verdict.daily_usd == 0.9
    assert verdict.reserved_usd == 0.25


def test_spend_governor_counts_recorded_at_over_forged_day_field(tmp_path: Path) -> None:
    (tmp_path / "evolve_governor.toml").write_text(
        (
            "[spend_governor]\n"
            "enabled = true\n"
            'ledger_path = "thomas_spend.jsonl"\n'
            "daily_usd_cap = 1.0\n"
            "total_usd_cap = 10.0\n"
            "per_iteration_usd_reserve = 0.25\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "thomas_spend.jsonl").write_text(
        json.dumps(
            {
                "source": "blue_evolve_child_reserve",
                "day": "2026-06-21",
                "recorded_at": "2026-06-22T12:00:00+00:00",
                "usd_total": 0.9,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    verdict = evaluate_spend_governor(tmp_path, today="2026-06-22")

    assert verdict.ok is False
    assert verdict.code == "daily_cap_exceeded"
    assert verdict.daily_usd == 0.9


def test_record_evolve_child_spend_appends_blue_reserve_entry(tmp_path: Path) -> None:
    (tmp_path / "evolve_governor.toml").write_text(
        (
            "[spend_governor]\n"
            "enabled = true\n"
            'ledger_path = "thomas_spend.jsonl"\n'
            "daily_usd_cap = 1.0\n"
            "total_usd_cap = 10.0\n"
            "per_iteration_usd_reserve = 0.25\n"
        ),
        encoding="utf-8",
    )

    result = record_evolve_child_spend(
        tmp_path,
        {"returncode": 0, "timed_out": False},
        session_id="session-123",
        phase="creative",
        pass_index=2,
        today="2026-06-22",
    )

    assert result.ok is True
    assert result.enabled is True
    assert result.code == "ledger_appended"
    entry = json.loads((tmp_path / "thomas_spend.jsonl").read_text(encoding="utf-8"))
    assert entry["source"] == "blue_evolve_child_reserve"
    assert entry["session_id"] == "session-123"
    assert entry["phase"] == "creative"
    assert entry["pass_index"] == 2
    assert entry["day"] == "2026-06-22"
    assert entry["recorded_at"] == "2026-06-22T00:00:00+00:00"
    assert entry["usd_total"] == 0.25


def test_spend_governor_fails_closed_when_blue_reserve_lacks_recorded_at(tmp_path: Path) -> None:
    (tmp_path / "evolve_governor.toml").write_text(
        (
            "[spend_governor]\n"
            "enabled = true\n"
            'ledger_path = "thomas_spend.jsonl"\n'
            "daily_usd_cap = 10.0\n"
            "per_iteration_usd_reserve = 0.25\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "thomas_spend.jsonl").write_text(
        json.dumps({"source": "blue_evolve_child_reserve", "day": "2026-06-22", "usd_total": 0.25}) + "\n",
        encoding="utf-8",
    )

    verdict = evaluate_spend_governor(tmp_path, today="2026-06-22")

    assert verdict.ok is False
    assert verdict.code == "ledger_invalid"
    assert "missing recorded_at" in verdict.message


def test_spend_governor_fails_closed_on_malformed_ledger(tmp_path: Path) -> None:
    (tmp_path / "evolve_governor.toml").write_text(
        (
            "[spend_governor]\n"
            "enabled = true\n"
            'ledger_path = "thomas_spend.jsonl"\n'
            "daily_usd_cap = 10.0\n"
            "per_iteration_usd_reserve = 0.25\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "thomas_spend.jsonl").write_text("{bad json\n", encoding="utf-8")

    verdict = evaluate_spend_governor(tmp_path, today="2026-06-22")

    assert verdict.ok is False
    assert verdict.code == "ledger_invalid"


def test_spend_watchdog_terminates_running_process_on_cap_breach(tmp_path: Path) -> None:
    process = _FakeHangingProcess()
    terminated = False

    def evaluator(root: Path) -> SpendGovernorVerdict:
        assert root == tmp_path
        return SpendGovernorVerdict(
            ok=False,
            enabled=True,
            code="daily_cap_exceeded",
            message="daily evolve spend cap would be exceeded",
        )

    def terminator(target) -> None:
        nonlocal terminated
        terminated = True
        target.killed = True

    result = monitor_process_with_spend_watchdog(
        process,
        repo_root=tmp_path,
        timeout_seconds=30,
        interval_seconds=0.05,
        terminator=terminator,
        evaluator=evaluator,
    )

    assert terminated is True
    assert result.returncode == WATCHDOG_RETURN_CODE
    assert result.watchdog_triggered is True
    assert result.watchdog_verdict is not None
    assert result.watchdog_verdict.code == "daily_cap_exceeded"
    assert "spend watchdog terminated process" in result.stderr


def test_spend_watchdog_returns_finished_process_without_budget_check(tmp_path: Path) -> None:
    process = _FakeFinishedProcess()

    def evaluator(root: Path) -> SpendGovernorVerdict:
        raise AssertionError("finished process should not need a budget recheck")

    result = monitor_process_with_spend_watchdog(
        process,
        repo_root=tmp_path,
        timeout_seconds=30,
        interval_seconds=0.05,
        evaluator=evaluator,
    )

    assert result.returncode == 0
    assert result.stdout == "done"
    assert result.watchdog_triggered is False


def test_evolve_corpus_runner_passes_locked_seed_corpus() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    result = run_evolve_corpus(repo_root)

    assert result.ok is True, result.to_dict()
    assert result.case_count == 7


def test_evolve_corpus_runner_fails_closed_on_invalid_lock(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    shutil.copytree(repo_root / "evolve_corpus", tmp_path / "evolve_corpus")
    (tmp_path / "evolve_corpus" / "cases" / "known_bad_empty_verification.json").write_text(
        '{"case_id":"known_bad_empty_verification","tampered":true}\n',
        encoding="utf-8",
    )

    result = run_evolve_corpus(tmp_path)

    assert result.ok is False
    assert result.case_count == 0
    assert any(item["code"] == "corpus_hash_mismatch" for item in result.lock_errors)
