#!/usr/bin/env python3
"""Enforce the AI-operated development and release workflow contract."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _exists(relative_path: str) -> bool:
    return (ROOT / relative_path).is_file()


def _contains(relative_path: str, required: list[str], failures: list[str]) -> None:
    if not _exists(relative_path):
        failures.append(f"missing required file: {relative_path}")
        return
    text = _read(relative_path)
    for needle in required:
        if needle not in text:
            failures.append(f"{relative_path} must contain: {needle}")


def _workflow_run_lines(text: str) -> list[str]:
    """Return executable lines from GitHub Actions run blocks."""
    lines = text.splitlines()
    commands: list[str] = []
    in_run_block = False
    block_indent = 0

    for raw_line in lines:
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))

        if stripped.startswith("run: |") or stripped.startswith("run: >"):
            in_run_block = True
            block_indent = indent
            continue
        if in_run_block and stripped and indent <= block_indent:
            in_run_block = False
        if not in_run_block:
            continue
        if not stripped or stripped.startswith("#"):
            continue
        commands.append(stripped)

    return commands


def _contains_workflow_commands(
    relative_path: str,
    required: list[str],
    failures: list[str],
) -> None:
    if not _exists(relative_path):
        failures.append(f"missing required file: {relative_path}")
        return
    commands = _workflow_run_lines(_read(relative_path))
    for needle in required:
        if not any(needle in command for command in commands):
            failures.append(f"{relative_path} must execute: {needle}")


def evaluate() -> dict[str, object]:
    failures: list[str] = []

    required_files = [
        "docs/AI_DEVELOPMENT_WORKFLOW.md",
        "docs/AGENT_START_HERE.md",
        "docs/FEATURE_MATRIX.md",
        ".github/copilot-instructions.md",
        ".github/pull_request_template.md",
        ".github/workflows/github-publish-safety.yml",
        ".github/workflows/robustness-gates.yml",
        ".github/workflows/windows-installer.yml",
        "scripts/github_publish_preflight.py",
        "scripts/check_repo_hygiene.py",
        "tests/test_ai_workflow_contract.py",
    ]
    for relative_path in required_files:
        if not _exists(relative_path):
            failures.append(f"missing required workflow contract file: {relative_path}")

    _contains(
        "docs/AI_DEVELOPMENT_WORKFLOW.md",
        [
            "private repo is the source of development truth",
            "public repo is a sanitized release artifact",
            "Sync public hardening back to private",
            "Do not publish ZIP download as the primary user path",
            "One issue or task should map to one branch or one scoped commit",
            "scripts/check_ai_workflow_contract.py",
        ],
        failures,
    )
    _contains(
        "docs/AGENT_START_HERE.md",
        [
            "docs/AI_DEVELOPMENT_WORKFLOW.md",
            "Do not bypass guardrails",
            "github_publish_preflight.py",
        ],
        failures,
    )
    _contains(
        ".github/copilot-instructions.md",
        [
            "docs/AI_DEVELOPMENT_WORKFLOW.md",
            "Do not bypass guardrails",
            "github_publish_preflight.py",
        ],
        failures,
    )
    _contains(
        ".github/pull_request_template.md",
        [
            "AI Workflow",
            "docs/AI_DEVELOPMENT_WORKFLOW.md",
            "github_publish_preflight.py",
        ],
        failures,
    )
    _contains(
        "DOCUMENTATION_INDEX.md",
        [
            "docs/AI_DEVELOPMENT_WORKFLOW.md",
            "AI-operated development and release workflow",
        ],
        failures,
    )
    _contains(
        "README.md",
        [
            "ThomasSetup_",
            "support.cmd",
        ],
        failures,
    )
    _contains_workflow_commands(
        ".github/workflows/github-publish-safety.yml",
        [
            "github_publish_preflight.py --deep --json --strict",
            "check_release_hygiene.py",
            "check_ai_workflow_contract.py",
        ],
        failures,
    )
    _contains_workflow_commands(
        ".github/workflows/robustness-gates.yml",
        [
            "tests/test_ai_workflow_contract.py",
            "tests/test_github_publish_preflight.py",
            "tests/test_release_contracts.py",
        ],
        failures,
    )

    return {
        "ok": not failures,
        "failure_count": len(failures),
        "failures": failures,
    }


def main() -> int:
    payload = evaluate()
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
