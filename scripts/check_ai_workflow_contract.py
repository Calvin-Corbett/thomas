#!/usr/bin/env python3
"""Enforce the public AI contributor guardrail contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_TEXT_SCAN_PATHS = {
    "scripts/check_ai_workflow_contract.py",
    "tests/test_ai_workflow_contract.py",
}
SKIP_TEXT_SCAN_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


def _join(*parts: str) -> str:
    return "".join(parts)


FORBIDDEN_PUBLIC_FILES = [
    "docs/AI_DEVELOPMENT_WORKFLOW.md",
    "docs/GITHUB_BRANCH_PROTECTION_SETUP.md",
    "docs/GITHUB_PUBLISH_SAFETY_WORKFLOW.md",
    "scripts/apply_branch_protection.ps1",
    "scripts/apply_release_lanes.ps1",
    "scripts/check_release_lane_policy.py",
    "scripts/configure_github_branch_protection.py",
    "scripts/setup_github_release_lanes.py",
]

FORBIDDEN_PUBLIC_PHRASES = [
    _join("private repo", " is the source of development truth"),
    _join("public repo", " is a sanitized release artifact"),
    _join("sync public hardening", " back"),
    _join("sanitized ", "public snapshot"),
    _join("sanitized ", "release snapshot"),
    _join("private ", "development branch"),
    _join("private ", "release history"),
    _join("private ", "changelog history"),
    _join("cloud", "flare/site secrets"),
    _join("github branch", " protection setup"),
    _join("release ", "lanes"),
    _join("set", "defaultdev"),
    _join("dev", "` + `", "prod"),
    _join("paste", "_token_here"),
    _join("configure_", "github_branch_protection"),
    _join("setup_", "github_release_lanes"),
    _join("apply_", "release_lanes"),
    _join("check_", "release_lane_policy"),
]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8", errors="replace")


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


def _tracked_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return [
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in ROOT.rglob("*")
            if path.is_file()
        ]
    return [
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def _public_text_paths() -> list[str]:
    paths: list[str] = []
    for relative_path in _tracked_files():
        normalized = relative_path.replace("\\", "/")
        if normalized in SKIP_TEXT_SCAN_PATHS:
            continue
        path = ROOT / normalized
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_TEXT_SCAN_PARTS for part in Path(normalized).parts):
            continue
        paths.append(normalized)
    return paths


def _check_forbidden_public_content(failures: list[str]) -> None:
    for relative_path in FORBIDDEN_PUBLIC_FILES:
        if _exists(relative_path):
            failures.append(f"forbidden public maintainer artifact exists: {relative_path}")

    lowered_phrases = [phrase.lower() for phrase in FORBIDDEN_PUBLIC_PHRASES]
    for relative_path in _public_text_paths():
        text = _read(relative_path).lower()
        for phrase in lowered_phrases:
            if phrase in text:
                failures.append(
                    f"{relative_path} contains forbidden public maintainer phrase: {phrase}"
                )


def evaluate() -> dict[str, object]:
    failures: list[str] = []

    required_files = [
        "docs/AI_CONTRIBUTOR_GUARDRAILS.md",
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

    _check_forbidden_public_content(failures)

    _contains(
        "docs/AI_CONTRIBUTOR_GUARDRAILS.md",
        [
            "public contributors and AI assistants",
            "Do not add secrets, personal notes, local caches, generated support bundles",
            "Do not claim Partial, Prototype, Planned, or Internal work is finished",
            "scripts/check_ai_workflow_contract.py",
        ],
        failures,
    )
    _contains(
        "docs/AGENT_START_HERE.md",
        [
            "docs/AI_CONTRIBUTOR_GUARDRAILS.md",
            "Do not bypass guardrails",
            "github_publish_preflight.py",
        ],
        failures,
    )
    _contains(
        ".github/copilot-instructions.md",
        [
            "docs/AI_CONTRIBUTOR_GUARDRAILS.md",
            "Do not bypass guardrails",
            "github_publish_preflight.py",
        ],
        failures,
    )
    _contains(
        ".github/pull_request_template.md",
        [
            "AI Guardrails",
            "docs/AI_CONTRIBUTOR_GUARDRAILS.md",
            "github_publish_preflight.py",
        ],
        failures,
    )
    _contains(
        "DOCUMENTATION_INDEX.md",
        [
            "docs/AI_CONTRIBUTOR_GUARDRAILS.md",
            "public AI contributor guardrails",
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
