"""A path on this machine, outside the workspace, is never a file the task must create or a data file it reads.

On 2026-09-27 a Thomas project was asked to fix its ChatGPT sign-in. The request named the live Codex login by its
Windows path and said "never touch the Codex auth.json itself". The contract did not read `C:\\...\\auth.json` as a
path, so the bare name became a file the team had to create at the root of its copy ("`auth.json` exists and is
non-empty when the work is done"), and the run could not finish without writing a sign-in file. Written with forward
slashes, the same path was read as a data file outside the workspace and its keys became requirements.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from thomas.core.acceptance_contract import build_contract


def _ids(text: str, ws: Path) -> list[str]:
    return [item.item_id for item in build_contract(text, ws)]


def test_a_windows_path_is_not_an_output_and_its_name_is_not_a_bare_mention(tmp_path: Path) -> None:
    text = (
        "You signed in to Codex again (C:\\Users\\someone\\.codex\\auth.json, written 19:51). "
        "Import the live login, and never touch the Codex auth.json itself. "
        "Write the change up in notes/signin.md."
    )

    ids = _ids(text, tmp_path)

    assert not [i for i in ids if "auth.json" in i]
    assert "output:notes/signin.md" in ids  # a workspace file the task names is still an output


def test_a_bare_data_file_with_no_path_elsewhere_is_still_an_output(tmp_path: Path) -> None:
    assert "output:auth.json" in _ids("Write the sample login to auth.json.", tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="a drive-letter path is a real file only on Windows")
def test_a_file_outside_the_workspace_is_never_read(tmp_path: Path) -> None:
    outside = tmp_path / "profile" / ".codex" / "auth.json"
    outside.parent.mkdir(parents=True)
    outside.write_text(json.dumps({"tokens": {"access_token": "x"}, "last_refresh": "y"}), encoding="utf-8")
    workspace = tmp_path / "project"
    workspace.mkdir()

    for written in (str(outside), outside.as_posix()):
        ids = _ids(f"Read the live login at {written} and never change it.", workspace)
        assert not [i for i in ids if "auth.json" in i], written
