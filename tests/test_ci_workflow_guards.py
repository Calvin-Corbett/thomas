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
