"""thomas_project.py is split before Part 2 grows it, and every name still answers where it did (spec 2026-10-12
Part 2, "Size first").

The file was 795 lines, five under the repo's 800-line rule, and Part 2 adds work orders to its start and its settle.
The start now lives in thomas_project_start and the settle in thomas_project_settle. thomas_project resolves their
names, and what they take from thomas_project is looked up there each time they run, so a caller or a test that
patches thomas_project.<name> still reaches the code that moved.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_store
from thomas.server import precard, thomas_project

SERVER = Path(__file__).resolve().parents[1] / "thomas" / "server"
MOVED = {
    "thomas_project_start": ("start_thomas_project", "_create_green", "_remove_quietly"),
    "thomas_project_settle": ("keep_unfinished", "settle_if_finished", "_may_hand_in", "_settle_unrecorded"),
}
# What callers and tests patch on thomas_project, and what the moved code takes from it: always looked up there.
LOOKED_UP = frozenset(
    {
        "_catalog_root",
        "record_issue",
        "stop_requested",
        "held_steers",
        "_patch_files",
        "_change_summary",
        "_subject",
        "_short_title",
        "_siblings_note",
        "_TEAM_NOTES",
        "_handover_lock",
        "_project",
        "ChangeTooLarge",
        "ThomasProjectError",
    }
)


def test_the_start_and_the_settle_live_in_their_own_modules() -> None:
    for module_name, names in MOVED.items():
        module = importlib.import_module(f"thomas.server.{module_name}")
        for name in names:
            assert name in module.NAMES, name
            assert getattr(thomas_project, name) is getattr(module, name), name


def test_every_file_keeps_to_the_size_rule() -> None:
    lines = {
        name: len((SERVER / f"{name}.py").read_text(encoding="utf-8").splitlines())
        for name in ("thomas_project", *MOVED)
    }
    assert lines["thomas_project"] <= 500, lines
    assert all(lines[name] <= 300 for name in MOVED), lines


def test_the_moved_code_looks_its_names_up_on_thomas_project() -> None:
    for module_name in MOVED:
        tree = ast.parse((SERVER / f"{module_name}.py").read_text(encoding="utf-8"))
        bare = sorted({node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id in LOOKED_UP})
        imported = sorted(
            {
                alias.asname or alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
                if (alias.asname or alias.name) in LOOKED_UP
            }
        )
        assert (bare, imported) == ([], []), module_name


def test_a_stop_patched_on_thomas_project_still_holds_the_settle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guard: it passes before the move and after it."""
    root, catalog = tmp_path / "green", tmp_path / "catalog"
    record = {"execution_id": "thomas-moved1"}
    cid = str(forge_code_store.new_conversation(root, title="t", thomas_project=record)["id"])
    forge_code_store.append_user_turn(root, cid, "Make the Send button blue.")
    forge_code_store.append_agent_turn(
        root, cid, model="claude", transcript="", changed_files=["a.py"], returncode=0, ok=True, noop=False,
        reason="1 file(s) changed", outcome="completed",
    )  # fmt: skip
    monkeypatch.setattr(thomas_project, "stop_requested", lambda _conversation: True)
    monkeypatch.setattr(precard, "check_for_hand_in", lambda _eid: pytest.fail("checked a stopped project"))

    assert thomas_project.settle_if_finished(root, catalog, cid) is None
