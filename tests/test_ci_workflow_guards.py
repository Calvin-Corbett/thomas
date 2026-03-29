from __future__ import annotations

from pathlib import Path


def test_nightly_reliability_uses_strict_competitor_and_security_checks() -> None:
    text = Path(".github/workflows/nightly-reliability.yml").read_text(encoding="utf-8")
    assert "python scripts/competitors/check_weekly_delta_alert.py --json --strict" in text
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
