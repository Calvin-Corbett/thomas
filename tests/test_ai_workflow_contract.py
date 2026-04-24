from __future__ import annotations

from scripts.check_ai_workflow_contract import evaluate


def test_ai_workflow_contract_is_enforced() -> None:
    payload = evaluate()

    assert payload["ok"], payload["failures"]
