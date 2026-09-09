from __future__ import annotations

from scripts.forge.gates.monolith_baseline_approval_gate import (
    apply_approval_file_change_requirement,
    evaluate_relaxation_gate,
)


def test_relaxation_gate_passes_without_relaxations() -> None:
    base = {
        "allowed_large_files": {
            "thomas/server/app.py": {"max_lines": 3300, "max_growth_lines": 100},
        }
    }
    head = {
        "allowed_large_files": {
            "thomas/server/app.py": {"max_lines": 3300, "max_growth_lines": 90},
        }
    }
    approvals = {"approvals": []}

    result = evaluate_relaxation_gate(base, head, approvals)
    assert result["ok"] is True
    assert result["violations"] == []


def test_relaxation_gate_fails_without_matching_approval() -> None:
    base = {
        "allowed_large_files": {
            "thomas/server/app.py": {"max_lines": 3300},
        }
    }
    head = {
        "allowed_large_files": {
            "thomas/server/app.py": {"max_lines": 3400},
        }
    }
    approvals = {"approvals": []}

    result = evaluate_relaxation_gate(base, head, approvals)
    assert result["ok"] is False
    assert result["violations"]
    assert result["violations"][0]["change"] == "max_lines_increase"


def test_relaxation_gate_passes_with_matching_approval() -> None:
    base = {
        "allowed_large_files": {
            "thomas/server/app.py": {"max_lines": 3300},
        }
    }
    head = {
        "allowed_large_files": {
            "thomas/server/app.py": {"max_lines": 3400},
        }
    }
    approvals = {
        "approvals": [
            {
                "id": "a1",
                "path": "thomas/server/app.py",
                "change": "max_lines_increase",
                "new_value": 3400,
                "approved_by": "core-platform",
                "approved_on": "2026-02-22",
                "reason": "temp baseline bump during split migration",
            }
        ]
    }

    result = evaluate_relaxation_gate(base, head, approvals)
    assert result["ok"] is True
    assert result["violations"] == []
    assert len(result["matched_approvals"]) == 1


def test_relaxation_gate_detects_growth_cap_relaxation() -> None:
    base = {
        "allowed_large_files": {
            "thomas/server/web/js/app.js": {"max_lines": 24000, "max_growth_lines": 400},
        }
    }
    head = {
        "allowed_large_files": {
            "thomas/server/web/js/app.js": {"max_lines": 24000, "max_growth_lines": 900},
        }
    }
    approvals = {"approvals": []}

    result = evaluate_relaxation_gate(base, head, approvals)
    assert result["ok"] is False
    assert any(row.get("change") == "max_growth_lines_relaxed" for row in result["violations"])


def test_relaxation_gate_requires_approvals_registry_diff_when_relaxing() -> None:
    base = {
        "allowed_large_files": {
            "thomas/server/app.py": {"max_lines": 3300},
        }
    }
    head = {
        "allowed_large_files": {
            "thomas/server/app.py": {"max_lines": 3400},
        }
    }
    approvals = {
        "approvals": [
            {
                "id": "a1",
                "path": "thomas/server/app.py",
                "change": "max_lines_increase",
                "new_value": 3400,
                "approved_by": "core-platform",
                "approved_on": "2026-02-22",
                "reason": "baseline bump",
            }
        ]
    }

    result = evaluate_relaxation_gate(base, head, approvals)
    assert result["ok"] is True

    enforced = apply_approval_file_change_requirement(
        result,
        approvals_changed=False,
        allow_existing_approvals=False,
    )
    assert enforced["ok"] is False
    assert any(v.get("change") == "approvals_registry_unchanged" for v in enforced["violations"])


def test_relaxation_gate_allows_existing_approvals_when_flag_enabled() -> None:
    base = {
        "allowed_large_files": {
            "thomas/server/app.py": {"max_lines": 3300},
        }
    }
    head = {
        "allowed_large_files": {
            "thomas/server/app.py": {"max_lines": 3400},
        }
    }
    approvals = {
        "approvals": [
            {
                "id": "a1",
                "path": "thomas/server/app.py",
                "change": "max_lines_increase",
                "new_value": 3400,
                "approved_by": "core-platform",
                "approved_on": "2026-02-22",
                "reason": "baseline bump",
            }
        ]
    }

    result = evaluate_relaxation_gate(base, head, approvals)
    assert result["ok"] is True

    enforced = apply_approval_file_change_requirement(
        result,
        approvals_changed=False,
        allow_existing_approvals=True,
    )
    assert enforced["ok"] is True
