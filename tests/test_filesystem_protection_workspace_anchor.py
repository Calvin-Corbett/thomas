"""Runtime protection must be anchored to the real Thomas repo, not an arbitrary
deliverable workspace.

A background worker builds a user deliverable in an isolated workspace
(``~/.thomas/workspaces/<id>/``) whose ``sandbox_root`` is NOT the repo. Before this
fix, the guard matched the path *shape* (``scripts/``, ``thomas/``) relative to the
sandbox, so a worker creating ``<workspace>/scripts/foo.py`` was falsely blocked as if
it were modifying Thomas's protected ``scripts/`` — and then retried forever, hanging
a task whose deliverable was already built. Protection is now anchored to the project
root: writes inside the real repo are still blocked; writes inside a separate workspace
are free. The file-access ladder (not runtime protection) is what confines the
workspace.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from thomas.core.file_access import FULL, WORKSPACE
from thomas.tools.diff import CreateDiffTool
from thomas.tools.filesystem import WriteFileTool, WriteProtectedFileTool


def _run(tool, args):
    return asyncio.run(tool.execute(args))


def test_workspace_scripts_write_is_allowed_when_sandbox_is_not_the_repo(tmp_path: Path) -> None:
    """A deliverable workspace with its own scripts/ subdir is the user's, not Thomas's."""
    workspace = tmp_path / "workspace"
    repo = tmp_path / "thomas_repo"
    workspace.mkdir()
    repo.mkdir()
    tool = WriteFileTool(workspace, project_root=repo)
    result = _run(tool, {"path": "scripts/forge/gates/monolith_guard.py", "content": "# user output\n"})
    assert result.ok is True, f"workspace scripts/ write must be allowed, got: {result.error}"
    assert (workspace / "scripts" / "forge" / "gates" / "monolith_guard.py").exists()


def test_repo_scripts_write_is_blocked_even_from_a_workspace_sandbox(tmp_path: Path) -> None:
    """A write that resolves INSIDE the real repo is still protected (FULL access)."""
    workspace = tmp_path / "workspace"
    repo = tmp_path / "thomas_repo"
    workspace.mkdir()
    (repo / "scripts").mkdir(parents=True)
    # FULL access so the file-access ladder doesn't block first — we want to prove the
    # RUNTIME-PROTECTION layer blocks the repo write specifically.
    tool = WriteFileTool(workspace, file_access=FULL, project_root=repo)
    target = repo / "scripts" / "evil.py"
    result = _run(tool, {"path": str(target), "content": "x = 1"})
    assert result.ok is False
    assert result.error is not None and "protected runtime" in result.error
    assert not target.exists()


def test_repo_thomas_package_write_is_blocked(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    repo = tmp_path / "thomas_repo"
    workspace.mkdir()
    (repo / "thomas" / "core").mkdir(parents=True)
    tool = WriteFileTool(workspace, file_access=FULL, project_root=repo)
    target = repo / "thomas" / "core" / "config.py"
    result = _run(tool, {"path": str(target), "content": "# tamper"})
    assert result.ok is False
    assert "protected runtime" in (result.error or "")


def test_workspace_level_confinement_still_blocks_repo_escape(tmp_path: Path) -> None:
    """At WORKSPACE level the file-access ladder (not runtime protection) blocks the
    repo escape — defense in depth: even if protection were anchored elsewhere, a
    WORKSPACE worker cannot reach the repo at all."""
    workspace = tmp_path / "workspace"
    repo = tmp_path / "thomas_repo"
    workspace.mkdir()
    (repo / "scripts").mkdir(parents=True)
    tool = WriteFileTool(workspace, file_access=WORKSPACE, project_root=repo)
    result = _run(tool, {"path": str(repo / "scripts" / "x.py"), "content": "x"})
    assert result.ok is False  # refused by the file-access ladder before protection


def test_write_protected_tool_allows_workspace_subdir_without_prompt(tmp_path: Path) -> None:
    """fs.write_protected_file on a workspace path is a normal write — no false block."""
    workspace = tmp_path / "workspace"
    repo = tmp_path / "thomas_repo"
    workspace.mkdir()
    repo.mkdir()
    tool = WriteProtectedFileTool(workspace, project_root=repo)
    result = _run(
        tool,
        {"path": "scripts/setup.py", "content": "# user output\n", "reason": "deliverable scaffolding"},
    )
    assert result.ok is True, f"workspace path must not be treated as protected, got: {result.error}"
    assert (workspace / "scripts" / "setup.py").exists()


def test_green_evolve_can_write_thomas_runtime_mirror(tmp_path: Path, monkeypatch) -> None:
    green = tmp_path / "runtime" / "doppelganger" / "green"
    (green / "thomas" / "core").mkdir(parents=True)
    monkeypatch.setenv("THOMAS_EVOLVE_GREEN_RUNTIME_WRITES", "1")

    tool = WriteFileTool(green, project_root=green)
    result = _run(tool, {"path": "thomas/core/config.py", "content": "# green candidate\n"})

    assert result.ok is True, result.error
    assert (green / "thomas" / "core" / "config.py").read_text(encoding="utf-8") == "# green candidate\n"


def test_green_evolve_can_apply_diff_to_thomas_runtime_mirror(tmp_path: Path, monkeypatch) -> None:
    green = tmp_path / "runtime" / "doppelganger" / "green"
    target = green / "thomas" / "core" / "config.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setenv("THOMAS_EVOLVE_GREEN_RUNTIME_WRITES", "1")

    tool = CreateDiffTool(green)
    result = _run(
        tool,
        {
            "file": "thomas/core/config.py",
            "old_str": "VALUE = 1\n",
            "new_str": "VALUE = 2\n",
        },
    )

    assert result.ok is True, result.error
    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"


def test_diff_create_accepts_fs_read_file_numbered_snippet(tmp_path: Path, monkeypatch) -> None:
    green = tmp_path / "runtime" / "doppelganger" / "green"
    target = green / "thomas" / "core" / "config.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\nNAME = 'old'\n", encoding="utf-8")
    monkeypatch.setenv("THOMAS_EVOLVE_GREEN_RUNTIME_WRITES", "1")

    tool = CreateDiffTool(green)
    result = _run(
        tool,
        {
            "file": "thomas/core/config.py",
            "old_str": "     1\tVALUE = 1\n     2\tNAME = 'old'\n",
            "new_str": "     1\tVALUE = 2\n     2\tNAME = 'new'\n",
        },
    )

    assert result.ok is True, result.error
    assert target.read_text(encoding="utf-8") == "VALUE = 2\nNAME = 'new'\n"


def test_green_evolve_still_blocks_scripts_guardrail_writes(tmp_path: Path, monkeypatch) -> None:
    green = tmp_path / "runtime" / "doppelganger" / "green"
    (green / "scripts").mkdir(parents=True)
    monkeypatch.setenv("THOMAS_EVOLVE_GREEN_RUNTIME_WRITES", "1")

    tool = WriteFileTool(green, project_root=green)
    result = _run(tool, {"path": "scripts/forge/gates/workboard_inbox.py", "content": "# tamper\n"})

    assert result.ok is False
    assert "protected runtime" in (result.error or "")


def test_green_evolve_still_blocks_supervisor_and_corpus_writes(tmp_path: Path, monkeypatch) -> None:
    green = tmp_path / "runtime" / "doppelganger" / "green"
    (green / "evolve_supervisor").mkdir(parents=True)
    (green / "evolve_corpus" / "cases").mkdir(parents=True)
    monkeypatch.setenv("THOMAS_EVOLVE_GREEN_RUNTIME_WRITES", "1")

    tool = WriteFileTool(green, project_root=green)
    supervisor_result = _run(tool, {"path": "evolve_supervisor/supervisor.py", "content": "# tamper\n"})
    corpus_result = _run(tool, {"path": "evolve_corpus/cases/new.json", "content": "{}\n"})

    assert supervisor_result.ok is False
    assert "protected runtime" in (supervisor_result.error or "")
    assert corpus_result.ok is False
    assert "protected runtime" in (corpus_result.error or "")


def test_green_evolve_runtime_write_requires_exact_green_slot_shape(tmp_path: Path, monkeypatch) -> None:
    near_miss = tmp_path / "runtime" / "doppelganger" / "greenish"
    (near_miss / "thomas" / "core").mkdir(parents=True)
    monkeypatch.setenv("THOMAS_EVOLVE_GREEN_RUNTIME_WRITES", "1")

    tool = WriteFileTool(near_miss, project_root=near_miss)
    result = _run(tool, {"path": "thomas/core/config.py", "content": "# tamper\n"})

    assert result.ok is False
    assert "protected runtime" in (result.error or "")


def test_green_evolve_runtime_write_requires_doppelganger_parent(tmp_path: Path, monkeypatch) -> None:
    fake_green = tmp_path / "runtime" / "not-doppelganger" / "green"
    (fake_green / "thomas" / "core").mkdir(parents=True)
    monkeypatch.setenv("THOMAS_EVOLVE_GREEN_RUNTIME_WRITES", "1")

    tool = WriteFileTool(fake_green, project_root=fake_green)
    result = _run(tool, {"path": "thomas/core/config.py", "content": "# tamper\n"})

    assert result.ok is False
    assert "protected runtime" in (result.error or "")


def test_green_evolve_still_blocks_policy_file_writes(tmp_path: Path, monkeypatch) -> None:
    green = tmp_path / "runtime" / "doppelganger" / "green"
    green.mkdir(parents=True)
    monkeypatch.setenv("THOMAS_EVOLVE_GREEN_RUNTIME_WRITES", "1")

    tool = WriteFileTool(green, project_root=green)
    result = _run(tool, {"path": "agent_safety.toml", "content": "# tamper\n"})

    assert result.ok is False
    assert "protected policy file" in (result.error or "")


def test_green_evolve_still_blocks_runtime_control_file_writes(tmp_path: Path, monkeypatch) -> None:
    green = tmp_path / "runtime" / "doppelganger" / "green"
    (green / "runtime").mkdir(parents=True)
    monkeypatch.setenv("THOMAS_EVOLVE_GREEN_RUNTIME_WRITES", "1")

    tool = WriteFileTool(green, project_root=green)
    result = _run(tool, {"path": "runtime/.runtime_protection_key", "content": "00" * 32})

    assert result.ok is False
    assert "runtime-protection control file" in (result.error or "")
