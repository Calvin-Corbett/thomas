from __future__ import annotations

import re
from pathlib import Path

import yaml


def test_nightly_reliability_uses_strict_security_check() -> None:
    # The "competitor" portion of this assertion was removed during the
    # 2026-05-21 pre-public cleanup (competitor parity scripts deleted).
    # The security audit signal still runs.
    text = Path(".github/workflows/nightly-reliability.yml").read_text(encoding="utf-8")
    assert "python scripts/security_audit.py --repo-root . --json --strict" in text


def test_robustness_gates_auto_checks_declares_breakglass_metadata() -> None:
    text = Path(".github/workflows/robustness-gates.yml").read_text(encoding="utf-8")
    assert 'THOMAS_SKIP_BREAKGLASS: "1"' in text
    assert 'THOMAS_SKIP_TICKET: "CI-ROBUSTNESS-GATES"' in text
    assert (
        'THOMAS_SKIP_REASON: "CI-reviewed robustness-gates lane skips nested gate scripts to avoid duplicate execution."'
        in text
    )


def test_robustness_gates_publish_core_python_quality_signals() -> None:
    text = Path(".github/workflows/robustness-gates.yml").read_text(encoding="utf-8")
    assert "Core Python coverage signal" in text
    assert "--cov-fail-under=88" in text
    assert "tests/test_agent_presence_more.py" in text
    assert "tests/test_chat_delegation.py" in text
    assert "tests/test_server_app_core.py" in text
    assert "tests/test_config_runtime.py" in text
    assert "--cov=thomas.server.chat_delegation" in text
    assert "--cov=thomas.server.app_core" in text
    assert "--cov=thomas.core.config" in text
    assert "--cov-report=xml:output/ci/core-python-coverage.xml" in text
    assert "python scripts/python_dependency_vulnerability_scan.py" in text
    assert "--allow-unfixed" in text
    assert "bandit -r \\" in text
    assert "thomas/server/chat_delegation.py \\" in text
    assert "thomas/server/app_core.py \\" in text
    assert "thomas/core/config.py \\" in text
    assert "output/ci/python-bandit-core.json" in text
    assert "actions/upload-artifact@v4" in text


_REPO = Path(__file__).resolve().parents[1]
_WORKFLOWS = _REPO / ".github" / "workflows"


def _steps(workflow: str) -> list[tuple[str, dict]]:
    doc = yaml.safe_load((_WORKFLOWS / workflow).read_text(encoding="utf-8-sig"))
    return [(job_id, step) for job_id, job in doc["jobs"].items() for step in job.get("steps") or []]


def _missing_test_files(workflow: str, step_name: str) -> list[str]:
    runs = [str(step.get("run") or "") for _, step in _steps(workflow) if step.get("name") == step_name]
    assert runs, f"{workflow} has no step named {step_name!r}"
    missing = []
    for run in runs:
        for line in run.splitlines():
            if line.strip().startswith("#"):
                continue
            missing.extend(name for name in re.findall(r"\btests/[\w./-]+\.py", line) if not (_REPO / name).is_file())
    return missing


def test_protocol_safety_step_names_only_test_files_that_exist() -> None:
    # pytest stops on "file or directory not found", so one stale name aborts the
    # step before it runs the tests that do exist. This step named two deleted
    # files and never reached its real tests.
    assert _missing_test_files("robustness-gates.yml", "Protocol safety tests") == []


def test_board_and_ledger_gates_are_scoped_off_main_not_removed() -> None:
    # The public main branch publishes an empty board and an empty module audit
    # ledger, so these gates can never pass there. They stay on everywhere else.
    steps = ("Workboard changed-file ownership gate", "Workboard audit backstop gate", "Module audit gate")
    gates_doc = yaml.safe_load((_WORKFLOWS / "gates.yml").read_text(encoding="utf-8-sig"))
    found = {"workboard-changed-files-gate": gates_doc["jobs"]["workboard-changed-files-gate"].get("if")}
    found.update(
        {step["name"]: step.get("if") for _, step in _steps("robustness-gates.yml") if step.get("name") in steps}
    )
    off_main = "github.ref_name != 'main'"
    assert found == {name: off_main for name in ("workboard-changed-files-gate", *steps)}
