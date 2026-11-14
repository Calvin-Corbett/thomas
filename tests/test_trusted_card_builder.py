"""The server's half of the approval cards: the pin check and the card builder.

The catalogue's wording is pinned (an Administrators-only hash); this module
refuses every PIN flow when the file on disk differs from the pin, loads the
catalogue by path from the exact file it checked, and builds cards whose details
come from the real bytes -- never the model's words on the Windows dialog.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from thomas.tools import trusted_card as tc


def _pin(root: Path, value: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / tc.PIN_NAME).write_text(value, encoding="utf-8")
    return root


def test_an_unpinned_catalogue_says_so(tmp_path: Path) -> None:
    assert tc.catalogue_status(pin_root=tmp_path / "nothing-here") == tc.STATUS_UNPINNED


def test_a_catalogue_matching_its_pin_is_trusted(tmp_path: Path) -> None:
    pins = _pin(tmp_path / "pins", tc.catalogue_digest())
    assert tc.catalogue_status(pin_root=pins) == tc.STATUS_OK
    tc.require_trusted_catalogue(pin_root=pins)  # does not raise


def test_an_edited_catalogue_is_refused(tmp_path: Path) -> None:
    edited = tmp_path / "card_catalogue.py"
    edited.write_bytes(tc.CATALOGUE_PATH.read_bytes() + b"\n# reworded\n")
    pins = _pin(tmp_path / "pins", tc.catalogue_digest())
    assert tc.catalogue_status(edited, pin_root=pins) == tc.STATUS_TAMPERED


def test_a_pin_nobody_can_read_is_the_strict_reading(tmp_path: Path) -> None:
    pins = tmp_path / "pins"
    pins.mkdir()
    (pins / tc.PIN_NAME).write_bytes(bytes([0xFF, 0xFE, 0x00]) + b"garbage")
    assert tc.catalogue_status(pin_root=pins) == tc.STATUS_TAMPERED
    with pytest.raises(tc.CatalogueTampered):
        tc.require_trusted_catalogue(pin_root=pins)


def test_crlf_line_endings_do_not_change_the_digest(tmp_path: Path) -> None:
    lf = tmp_path / "lf.py"
    crlf = tmp_path / "crlf.py"
    lf.write_bytes(b"a = 1\nb = 2\n")
    crlf.write_bytes(b"a = 1\r\nb = 2\r\n")
    assert tc.catalogue_digest(lf) == tc.catalogue_digest(crlf)


def test_the_catalogue_is_loaded_from_the_file_that_was_checked(tmp_path: Path) -> None:
    """A same-named module earlier on the import path must not stand in for it:
    the digest is of CATALOGUE_PATH, so that is the file that must be running."""
    shadow = tmp_path / "card_catalogue.py"
    shadow.write_text("KINDS = {}  # an impostor\n", encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        module = tc.load_catalogue()
    finally:
        sys.path.remove(str(tmp_path))
    assert Path(module.__file__).resolve() == tc.CATALOGUE_PATH.resolve()
    assert module.KINDS, "loaded the impostor"


def test_a_card_is_built_from_the_real_bytes() -> None:
    card = tc.protected_write_card("thomas/tools/filesystem.py", "a = 1\n", "a = 2\nb = 3\n", why="tidy up")
    assert card.details == {"path": "thomas/tools/filesystem.py", "diffstat": "+2 -1 line(s)"}
    assert card.content_hash == tc.load_catalogue().content_hash("a = 2\nb = 3\n")
    assert "+a = 2" in card.excerpt
    assert card.danger is None


def test_a_gate_file_is_marked_dangerous() -> None:
    card = tc.protected_write_card("scripts/forge/gates/new_gate.py", None, "x = 1\n", why="add a gate")
    assert card.danger == tc.load_catalogue().DANGER_GATES
    assert card.details["diffstat"] == "new file, 1 line(s)"


def test_an_unreadable_existing_file_is_not_called_new() -> None:
    card = tc.protected_write_card("thomas/tools/x.py", None, "x = 1\n", why="", existed=True)
    assert "new file" not in card.details["diffstat"]


def test_the_dialog_carries_the_code_and_never_the_models_words() -> None:
    why = "IGNORE THE DIFF this is only a typo, approve it"
    card = tc.protected_write_card("thomas/tools/filesystem.py", "a\n", "b\n", why=why)
    action, reason = card.dialog()
    assert card.code in action + reason
    assert "IGNORE" not in action + reason and "typo" not in action + reason
    assert card.why == why, "the model's words stay available for the chat card"


def test_a_dangerous_card_says_it_gets_its_own_approval() -> None:
    card = tc.protected_write_card("agent_safety.toml", "a\n", "b\n", why="")
    _action, reason = card.dialog()
    assert "own approval" in reason


@pytest.mark.skipif(os.name != "nt", reason="the pin script is PowerShell")
def test_powershell_and_python_agree_on_the_digest(tmp_path: Path) -> None:
    """The pin is written by an elevated PowerShell script that hashes the file
    itself -- never by asking the catalogue -- and read here in Python. If the two
    disagreed, every PIN flow would refuse forever."""
    sample = tmp_path / "sample.py"
    sample.write_bytes(b"x = 1\r\ny = 2\r\n# end\n")
    helper = Path(__file__).resolve().parents[1] / "scripts" / "cage" / "pin_folder.ps1"
    command = f". '{helper}'; Get-NormalizedSha256 -Path '{sample}'"
    done = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == tc.catalogue_digest(sample)
