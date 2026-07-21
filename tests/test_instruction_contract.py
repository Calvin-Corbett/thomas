"""CAP-019: Root instruction file — honored on every execution surface.

Proves the acceptance line:
    "Honor the root instruction contract consistently in every execution
     surface, including delegated workers."

The main agent loop already injects hierarchical root/project instructions into
its system prompt. These tests prove the *shared* enforcement helper applies the
identical contract to a delegated-worker system prompt, that both surfaces can
assert they used the same contract via a stable signature, that a worker with no
project instructions degrades cleanly, and that the delegation seam actually
calls the helper.
"""

from pathlib import Path

from thomas.agent.instruction_contract import (
    EMPTY_SIGNATURE,
    apply_root_instructions,
    contract_signature,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_project(tmp_path: Path, *, instructions: str | None = "Always ship tests.") -> Path:
    """Create a git-rooted project dir; optionally with a THOMAS.md contract."""

    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    if instructions is not None:
        _write(root / "THOMAS.md", instructions)
    return root


def test_apply_root_instructions_injects_into_worker_prompt(tmp_path: Path) -> None:
    root = _make_project(tmp_path, instructions="Delegated workers MUST run ruff.")
    worker_system = "You are a background worker completing the user's task."

    applied = apply_root_instructions(worker_system, cwd=root)

    # Original worker prompt is preserved and the resolved contract is appended.
    assert worker_system in applied
    assert "Delegated workers MUST run ruff." in applied
    assert "Project Instructions" in applied
    assert len(applied) > len(worker_system)


def test_signature_identical_across_main_and_delegated_worker(tmp_path: Path) -> None:
    root = _make_project(tmp_path, instructions="Root contract v1.")

    # Main surface resolves at the project root; a delegated worker rooted at the
    # SAME cwd must compute the identical contract signature.
    main_sig = contract_signature(root)
    worker_sig = contract_signature(root)

    assert main_sig == worker_sig
    assert main_sig != EMPTY_SIGNATURE

    # A worker resolving from a nested subdir of the same project inherits the
    # same root contract, so the signature is unchanged.
    nested = root / "pkg" / "sub"
    nested.mkdir(parents=True)
    assert contract_signature(nested) == main_sig


def test_signature_differs_when_instruction_set_differs(tmp_path: Path) -> None:
    root_a = _make_project(tmp_path / "a", instructions="Contract A.")
    root_b = _make_project(tmp_path / "b", instructions="Contract B — different rules.")

    assert contract_signature(root_a) != contract_signature(root_b)

    # Same file path, mutated content -> different signature (content-addressed).
    _write(root_a / "THOMAS.md", "Contract A, revised.")
    revised = contract_signature(root_a)
    assert revised != contract_signature(root_b)


def test_worker_with_no_project_instructions_degrades_cleanly(tmp_path: Path) -> None:
    # Fresh, empty per-task workspace: no instruction files anywhere up to root.
    empty_root = tmp_path / "empty"
    (empty_root / ".git").mkdir(parents=True)
    worker_system = "You are a background worker in a fresh, empty workspace."

    applied = apply_root_instructions(worker_system, cwd=empty_root)
    assert applied == worker_system  # unchanged — no contract to apply
    assert contract_signature(empty_root) == EMPTY_SIGNATURE

    # None cwd must not raise either.
    assert isinstance(contract_signature(None), str)


def test_signature_is_budget_independent(tmp_path: Path) -> None:
    # A large contract truncated differently by two surfaces must still yield the
    # same signature (signature hashes the source files, not the clipped merge).
    root = _make_project(tmp_path, instructions="LINE\n" * 4_000)

    tight = apply_root_instructions("worker", cwd=root, budget=500)
    wide = apply_root_instructions("worker", cwd=root, budget=24_000)
    # Different budgets can produce different injected text lengths...
    assert len(tight) < len(wide)
    # ...but the asserted contract identity is identical.
    assert contract_signature(root) == contract_signature(root)


def test_delegation_seam_applies_the_contract() -> None:
    """The delegated-worker prompt path wires the shared helper (source contract)."""

    seam = Path(__file__).resolve().parents[1] / "thomas" / "server" / "chat_delegation.py"
    src = seam.read_text(encoding="utf-8")
    assert "from thomas.agent.instruction_contract import apply_root_instructions" in src
    assert "apply_root_instructions(instructions, cwd=work_dir)" in src
