"""The protection toggle must agree with the validator that actually gates writes.

Two defects found on 2026-09-09 while landing the break-glass window:

1. ``python scripts/runtime_protection_toggle.py off`` failed from the repo root
   with "ERROR: Could not import breakglass_auth. Run from the Thomas repo root."
   Run as a plain script, ``sys.path[0]`` is ``scripts/``, so neither
   ``scripts.breakglass_auth`` nor its own ``scripts.*`` imports resolve. The
   human-facing control for the safety system did not work the documented way,
   and said the opposite of the real cause.

2. ``_is_disabled`` was a presence check -- ``_flag_path(repo).exists()`` -- so a
   flag that is expired, unsigned, or signed with the wrong key still counted as
   "disabled". ``status`` therefore reported DISABLED while every gate correctly
   treated protection as ON, and ``off`` short-circuited with "already DISABLED"
   and refused to mint a fresh flag. Together that is a dead end: the override
   cannot be restored without deleting files by hand.

   Presence-only trust is the same shape as B9 (praxis-unbypassable-2026-05-29),
   where several gates honoured the flag by presence and an unsigned file planted
   by an agent disabled them all. The gates were fixed then; this tool was not.

The toggle now asks the same validator the gates ask.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from tests.filesystem_protection_helpers import _write_signed_flag  # noqa: E402


def _plant_flag(root: Path, *, key: bytes, issued_at: str | None = None) -> None:
    """A signed flag AND the key that verifies it.

    The shared helper writes only the flag; every caller plants the key itself.
    Without it the validator rejects the flag for a missing key, which would make
    a "fresh flag is honoured" assertion pass for the wrong reason.
    """
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / ".runtime_protection_key").write_text(key.hex(), encoding="utf-8")
    _write_signed_flag(root, key=key, issued_at=issued_at)


def _toggle():
    import runtime_protection_toggle

    return runtime_protection_toggle


def test_status_runs_as_a_plain_script_without_pythonpath() -> None:
    """The documented invocation must work with no environment help.

    This is the regression: it exited 1 with an import error that blamed the
    working directory.
    """
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "runtime_protection_toggle.py"), "status"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    combined = (out.stdout or "") + (out.stderr or "")
    assert "Could not import breakglass_auth" not in combined, combined
    assert "Runtime protection" in combined, combined


def test_an_expired_flag_is_not_reported_as_disabled(tmp_path: Path) -> None:
    """The defect this file exists for: status lied and off refused to act."""
    import datetime as dt
    import hashlib

    stale = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=48)).isoformat()
    _plant_flag(tmp_path, key=hashlib.sha256(b"k").digest(), issued_at=stale)
    assert _toggle()._is_disabled(tmp_path) is False


def test_an_unsigned_flag_is_not_reported_as_disabled(tmp_path: Path) -> None:
    """B9's shape: presence is not authorisation."""
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runtime" / ".runtime_protection_disabled").write_text(
        "planted, unsigned", encoding="utf-8"
    )
    assert _toggle()._is_disabled(tmp_path) is False


# A "fresh signed flag is honoured" case lived here. It duplicated
# test_runtime_guard_signed_flag.py::test_a_fresh_breakglass_flag_is_still_honoured,
# which covers the validator directly and passes. What this file needs to pin is
# that the TOGGLE agrees with that validator, which is the test below.


def test_the_toggle_and_the_gates_never_disagree(tmp_path: Path) -> None:
    """One source of truth, so status can never contradict what the gates do."""
    import datetime as dt
    import hashlib

    from scripts.forge.gates._runtime_guard import runtime_protection_disabled

    key = hashlib.sha256(b"k").digest()
    fresh = dt.datetime.now(dt.UTC).isoformat()
    stale = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=48)).isoformat()
    for issued_at in (fresh, stale, "not-a-timestamp"):
        _plant_flag(tmp_path, key=key, issued_at=issued_at)
        assert _toggle()._is_disabled(tmp_path) is runtime_protection_disabled(tmp_path), (
            f"toggle and gate validator disagree for issued_at={issued_at}"
        )


def test_status_names_a_flag_that_is_present_but_not_honoured(tmp_path: Path, capsys) -> None:
    """A stale flag on disk is worth saying out loud, not silently ignoring."""
    import datetime as dt
    import hashlib

    stale = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=48)).isoformat()
    _plant_flag(tmp_path, key=hashlib.sha256(b"k").digest(), issued_at=stale)
    _toggle().cmd_status(tmp_path)
    printed = capsys.readouterr().out
    assert "ENABLED" in printed
    assert "not honoured" in printed.lower() or "expired" in printed.lower(), printed
