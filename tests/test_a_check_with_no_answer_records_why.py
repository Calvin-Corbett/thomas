"""Every check's own line goes into its clocks record, so a check that gave no answer can be read afterwards.

Since 2026-10-27, 17 checks ended "unavailable, dev-side" and used 65% of the checks' test time, and not one record
said why: the line reached only the hold row, which is dropped once the change settles.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.server.precard import check, clocks

WHY = "the same tests did not run to the end on dev itself: shard 3 of 16: pytest exit 1 contradicts its report"


def test_an_unavailable_check_keeps_its_line_in_the_clocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    held = check._unavailable(WHY, cause="dev-side", costly=False)
    monkeypatch.setattr(check, "_decide", lambda *_a: held)
    monkeypatch.setattr(check.pool, "parallel", lambda: True)
    monkeypatch.delenv(check.CHECK_ENV, raising=False)  # tests/conftest.py turns checks off

    with clocks.recording(tmp_path, "conversation") as record:
        check.check_before_card("green-1")

    assert record["check_cause"] == "dev-side" and record["check_line"] == held.line
    assert WHY in record["check_line"]


def test_a_very_long_line_is_kept_to_its_first_2000_characters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    held = check._unavailable("x" * 5000, cause="dev-side", costly=False)
    monkeypatch.setattr(check, "_decide", lambda *_a: held)
    monkeypatch.setattr(check.pool, "parallel", lambda: True)
    monkeypatch.delenv(check.CHECK_ENV, raising=False)  # tests/conftest.py turns checks off

    with clocks.recording(tmp_path, "conversation") as record:
        check.check_before_card("green-1")

    assert record["check_line"] == held.line[:2000]
