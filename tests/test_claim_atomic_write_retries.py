"""A claim write survives the rename race that message writes already survive.

2026-09-05: claim.py --claim failed twelve times with WinError 5 renaming its
temp file onto WORKBOARD.md while message.py sends succeeded every time. The
message path retries the replace under the board lock; the claim path did a
bare replace once. Same board, same race, one writer must not be weaker.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts" / "crew" / "workboard") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "crew" / "workboard"))


def test_atomic_write_retries_a_transient_replace_failure(tmp_path: Path, monkeypatch) -> None:
    import claim_utils

    board = tmp_path / "WORKBOARD.md"
    board.write_text("old", encoding="utf-8")
    attempts = {"n": 0}
    real_replace = Path.replace

    def flaky_replace(self, target):  # noqa: ANN001
        attempts["n"] += 1
        if attempts["n"] < 3:
            # Built the way Windows builds it: winerror 5 is what the board saw.
            raise OSError(0, "Access is denied", None, 5)
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    import board_io

    monkeypatch.setattr(board_io.time, "sleep", lambda _s: None)

    claim_utils._atomic_write(board, "new")

    assert board.read_text(encoding="utf-8") == "new"
    assert attempts["n"] == 3
    assert not list(tmp_path.glob(".WORKBOARD.md.*.tmp"))


def test_atomic_write_falls_back_to_in_place_when_the_replace_is_denied_for_good(tmp_path: Path, monkeypatch) -> None:
    import board_io
    import claim_utils

    board = tmp_path / "WORKBOARD.md"
    board.write_text("old", encoding="utf-8")

    def denied(self, target):  # noqa: ANN001, ARG001
        raise OSError(0, "Access is denied", None, 5)

    monkeypatch.setattr(Path, "replace", denied)
    monkeypatch.setattr(board_io.time, "sleep", lambda _s: None)

    claim_utils._atomic_write(board, "new")

    assert board.read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob(".WORKBOARD.md.*.tmp"))
