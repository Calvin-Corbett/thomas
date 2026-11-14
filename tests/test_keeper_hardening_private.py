"""Regression tests for the security review of keeper capture v1 (P0.3): where the keeper may write.

One section per finding, named by its id; the other findings are in ``test_keeper_hardening*.py``. Each test fails on
the code the review read and passes on the fix. Nothing here changes an access list: privacy is judged from what
Windows already says about folders, or from a stand-in for that reading.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from scripts.keeper import private
from scripts.keeper.capture import CaptureRefused, capture_tree, main

from tests.express_winfs import IS_WINDOWS, create_junction

# world is a pytest fixture, shared through keeper_support
from tests.keeper_support import keep_files, world

# --- state-dir-unvalidated-writes-into-place-or-cage -------------------------------------------------------------


def test_a_state_folder_inside_the_place_is_refused_and_the_place_is_untouched(world):
    with pytest.raises(CaptureRefused, match="never go there"):
        capture_tree(world.place, world.settings(state_dir=world.place / "sub" / "keeper-state"), world.main_git)
    assert not (world.place / "sub").exists() and keep_files(world.keep) == []


def test_a_state_folder_where_the_cage_reads_is_refused(world, monkeypatch):
    cage = world.root / "cage-root"
    monkeypatch.setattr(private, "CAGE_ROOTS", (str(cage),))
    with pytest.raises(CaptureRefused, match="never go there"):
        capture_tree(world.place, world.settings(state_dir=cage / "states"), world.main_git)
    assert not cage.exists()


def test_a_state_folder_others_can_read_is_refused(world, monkeypatch):
    shared = world.root / "shared"
    real = private.readers_besides_you

    def readers(path):
        inside = os.path.normcase(str(path)).startswith(os.path.normcase(str(shared)))
        return ["CodexSandboxUsers (S-1-5-21-1-2-3-1005)"] if inside else real(path)

    monkeypatch.setattr(private, "readers_besides_you", readers)
    with pytest.raises(CaptureRefused, match="can be read by CodexSandboxUsers"):
        capture_tree(world.place, world.settings(state_dir=shared / "states"), world.main_git)
    assert not shared.exists() and keep_files(world.keep) == []


def test_a_state_file_goes_only_where_captures_go(world, capsys):
    assert main(["state", str(world.place), "--out", str(world.place / "state.json")]) == 2
    assert "never go there" in json.loads(capsys.readouterr().out)["refused"]
    assert not (world.place / "state.json").exists()


@pytest.mark.parametrize(
    ("owner", "aces", "found"),
    [
        ("S-me", [(0, 0x1F01FF, "S-me"), (0, 0x1F01FF, "S-1-5-18"), (0, 0x1F01FF, "S-1-5-32-544")], []),
        ("S-me", [(0, 0x1200A9, "S-1-5-21-9-1005")], ["S-1-5-21-9-1005"]),  # read and execute for a sandbox group
        ("S-me", [(0, 0x20, "S-1-1-0")], []),  # traverse only: nothing can be read
        ("S-me", [(0, 0x40000, "S-1-5-11")], ["S-1-5-11"]),  # may rewrite the access list, so may read
        ("S-me", [(1, 0x1F01FF, "S-1-1-0")], []),  # a deny entry lets nobody in
        ("S-1-5-21-9-1010", [], ["S-1-5-21-9-1010 (owner)"]),
        ("S-me", [(5, 0, "")], ["an access entry of kind 5"]),  # an entry not parsed counts against the folder
        ("S-me", None, ["anyone (no access list)"]),
    ],
)
def test_strangers_reads_an_access_list(owner, aces, found):
    assert private.strangers(owner, aces, "S-me") == found


@pytest.mark.skipif(not IS_WINDOWS, reason="access lists are read on Windows only")
def test_windows_itself_is_not_private_and_says_who_can_read_it():
    readers = private.readers_besides_you(Path(os.environ["SYSTEMROOT"]))
    assert any("S-1-5-32-545" in r for r in readers)  # Users can read the Windows folder on every install


# --- r3-checks-do-not-resolve-links ------------------------------------------------------------------------------


@pytest.mark.skipif(not IS_WINDOWS, reason="junctions are Windows behaviour")
def test_a_work_folder_reached_through_a_junction_is_refused(world):
    (world.place / "scratch").mkdir()
    create_junction(world.root / "work-link", world.place / "scratch")
    settings = world.settings()
    settings.work = world.root / "work-link" / "w"
    with pytest.raises(CaptureRefused, match="passes through a link"):
        capture_tree(world.place, settings, world.main_git)
    assert list((world.place / "scratch").iterdir()) == []


@pytest.mark.skipif(not IS_WINDOWS, reason="junctions are Windows behaviour")
def test_containment_compares_where_a_write_really_lands(world, monkeypatch):
    (world.place / "scratch").mkdir()
    create_junction(world.root / "keep-link", world.place / "scratch")
    monkeypatch.setattr(private, "link_in", lambda _p: None)  # the second wall, alone: real paths
    reason = private.why_not_private(world.root / "keep-link", [world.place])
    assert reason and "is inside" in reason and os.path.normcase(str(world.place)) in reason
