"""Locking the pin folder must not lock Thomas out of the pins already in it.

Measured live 2026-09-22, right after the first real pin run: the posture pin
could not be read by anyone -- not even its permissions could be listed -- while
the catalogue pin written a moment later was fine. The folder step ran icacls
with ``/T``, which re-applied the folder's permissions to every file already
inside: it stripped each file's inherited access, then tried to grant the
folder-style ``(OI)(CI)`` rights, which do not apply to a file, and the errors
were swallowed by ``/C /Q``. So whichever pin was written second emptied the
first one's permissions.

For the posture that fails closed (an unreadable pin reads as "required"). For
the catalogue it would not: an unreadable catalogue pin reads as tampered, and
every PIN prompt would refuse. Re-pinning the posture would have done exactly
that. This runs the folder step unelevated on a folder the test owns, which is
all the bug needs.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "scripts" / "cage" / "pin_folder.ps1"


@pytest.mark.skipif(os.name != "nt", reason="the pin scripts are PowerShell and Windows ACLs")
def test_locking_the_folder_leaves_every_pin_readable(tmp_path: Path) -> None:
    pins = tmp_path / "pins"
    pins.mkdir()
    (pins / "posture").write_text("required", encoding="utf-8")
    (pins / "catalogue.sha256").write_text("ab" * 32, encoding="utf-8")
    try:
        done = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f". '{HELPER}'; Set-PinFolderAcl -PinRoot '{pins}'",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert done.returncode == 0, done.stderr

        assert (pins / "posture").read_text(encoding="utf-8") == "required"
        assert (pins / "catalogue.sha256").read_text(encoding="utf-8") == "ab" * 32
        with pytest.raises(PermissionError):
            (pins / "posture").write_text("off", encoding="utf-8")
    finally:
        # The test's own account owns these, and an owner may always reset
        # permissions -- so the temp folder can be cleaned up afterwards.
        subprocess.run(["icacls", str(pins), "/reset", "/T", "/C", "/Q"], capture_output=True, check=False)
