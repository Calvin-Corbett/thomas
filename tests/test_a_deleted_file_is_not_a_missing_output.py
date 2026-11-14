"""A file the task was asked to delete is never read back as an output the task must create.

On 2026-09-27 a Thomas project was asked to delete generated filler, including scripts/generate_gap_assets.py. It did,
and the completion gate then blocked its "done" with "`scripts/generate_gap_assets.py` exists and is non-empty when
the work is done (the task names it as an output)": the contract is built again each turn, and a named path missing
from disk was read as an output to create. A path in the workspace's last commit is a file the task refers to.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.core.acceptance_contract import build_contract


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, check=True, capture_output=True
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "generate_gap_assets.py").write_text("print('filler')\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


ASK = (
    "Delete scripts/generate_gap_assets.py, the generator of the filler, and write the removal up in notes/removed.md."
)


def _outputs(ask: str, root: Path) -> set[str]:
    return {item.item_id for item in build_contract(ask, root) if item.item_id.startswith("output:")}


def test_a_deleted_committed_file_is_not_a_required_output(workspace: Path) -> None:
    (workspace / "scripts" / "generate_gap_assets.py").unlink()  # the team did what it was asked

    outputs = _outputs(ASK, workspace)

    assert "output:scripts/generate_gap_assets.py" not in outputs
    assert "output:notes/removed.md" in outputs  # a genuinely new file is still an output


def test_a_new_file_in_a_folder_that_is_not_a_repository_is_still_an_output(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    assert "output:scripts/generate_gap_assets.py" in _outputs(ASK, plain)
