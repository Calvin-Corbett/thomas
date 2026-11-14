"""Runtime protection guards the Thomas that is running, not every folder that looks like it.

Protection matched paths relative to whatever root a tool was confined to. A Build
run's root is the project folder, so a copy of Thomas (a worktree Thomas was asked to
improve) could not have `thomas/core/*.py` written, and any user project lost the
ability to edit its own `scripts/` or `pyproject.toml`. The Build runner now anchors
protection to the folder the running Thomas was loaded from.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.tools import runtime_protection_paths as protection
from thomas.tools.filesystem import _is_protected_runtime_path, anchor_runtime_protection


@pytest.fixture(autouse=True)
def _no_anchor_leaks() -> None:
    saved = protection._RUNTIME_ANCHOR
    yield
    protection._RUNTIME_ANCHOR = saved


def _tree(root: Path) -> Path:
    (root / "thomas" / "core").mkdir(parents=True)
    (root / "scripts").mkdir()
    return root


def test_a_copy_of_thomas_is_writable_once_protection_is_anchored(tmp_path: Path) -> None:
    running = _tree(tmp_path / "running")
    copy = _tree(tmp_path / "copy")
    anchor_runtime_protection(running)

    assert _is_protected_runtime_path(copy, copy / "thomas" / "core" / "llm_client.py") is None
    assert _is_protected_runtime_path(copy, copy / "scripts" / "build.py") is None
    assert _is_protected_runtime_path(copy, copy / "pyproject.toml") is None


def test_the_running_thomas_stays_protected_once_anchored(tmp_path: Path) -> None:
    running = _tree(tmp_path / "running")
    anchor_runtime_protection(running)

    assert _is_protected_runtime_path(running, running / "thomas" / "core" / "llm_client.py")
    assert _is_protected_runtime_path(running, running / "pyproject.toml")


def test_the_file_size_waiver_file_cannot_be_written_by_an_agent(tmp_path: Path) -> None:
    # Found live 2026-09-19: an agent rewrote this file to waive every violation.
    # It was protected when committing, but nothing stopped the write itself.
    running = _tree(tmp_path / "running")
    (running / "docs").mkdir()
    anchor_runtime_protection(running)

    reason = _is_protected_runtime_path(running, running / "docs" / "monolith_guard_baseline.json")

    assert reason and "protected" in reason.lower()


@pytest.mark.parametrize(
    "rel",
    [
        # Everything git trusts: the hooks that run every gate, the config that can
        # redirect them, and the verification records two gates read.
        ".git/hooks/pre-commit",
        ".git/config",
        ".git/agent_verification.json",
        # Waivers and records gates read while Thomas is running.
        "docs/ops/landed_history_waivers.json",
        "docs/monolith_guard_baseline.json",
        # Claims and acks the coordination gates judge.
        "plans/thomas/WORKBOARD.md",
        "runtime/push_gate_cache.json",
        "runtime/coordination/workboard_takeover_transaction.json",
        # Rules the gates quote, and the ignore file that decides what they see.
        "WORKTREE_RULES.md",
        "AGENT_SAFETY_GATES.md",
        "AGENT_RULES_QUICK_REFERENCE.md",
        "PROJECT_MANAGEMENT_RULES.md",
        "docs/AGENT_FILE_EDITING_RULES.md",
        "docs/REPO_STRUCTURE_PROTOCOL.md",
        ".gitignore",
    ],
)
def test_an_agent_cannot_write_what_a_gate_trusts(tmp_path: Path, rel: str) -> None:
    running = _tree(tmp_path / "running")
    anchor_runtime_protection(running)

    assert _is_protected_runtime_path(running, running / rel), f"{rel} is writable by agent tools"


def test_a_broad_root_still_cannot_reach_the_running_thomas(tmp_path: Path) -> None:
    running = _tree(tmp_path / "running")
    anchor_runtime_protection(running)

    # A tool confined to a parent folder (e.g. "anywhere on my PC") must still be refused.
    assert _is_protected_runtime_path(tmp_path, running / "thomas" / "core" / "llm_client.py")


def test_without_an_anchor_protection_is_unchanged(tmp_path: Path) -> None:
    protection._RUNTIME_ANCHOR = None
    root = _tree(tmp_path / "root")

    assert _is_protected_runtime_path(root, root / "thomas" / "core" / "llm_client.py")
    assert _is_protected_runtime_path(root, root / "pyproject.toml")


def test_the_build_runner_anchors_to_the_thomas_it_loaded() -> None:
    import thomas
    from thomas.forge.anvil.forge_code_runner import prepare_runner_process

    protection._RUNTIME_ANCHOR = None
    prepare_runner_process()

    loaded_from = Path(thomas.__file__).resolve().parents[1]
    assert loaded_from == protection._RUNTIME_ANCHOR
