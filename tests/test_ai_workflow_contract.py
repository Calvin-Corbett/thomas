from __future__ import annotations

from scripts.check_ai_workflow_contract import evaluate, _workflow_run_lines


def test_ai_workflow_contract_is_enforced() -> None:
    payload = evaluate()

    assert payload["ok"], payload["failures"]


def test_workflow_run_lines_ignore_commented_commands() -> None:
    text = """
name: example
jobs:
  check:
    steps:
      - name: Commented
        run: |
          # python scripts/check_ai_workflow_contract.py
      - name: Real
        run: |
          python scripts/github_publish_preflight.py --deep --json --strict
"""

    assert _workflow_run_lines(text) == [
        "python scripts/github_publish_preflight.py --deep --json --strict"
    ]
