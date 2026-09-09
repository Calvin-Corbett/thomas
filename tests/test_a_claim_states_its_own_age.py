"""A claim says when it was made, instead of leaving git to guess.

`git blame` cannot date a claim. The claim tools rewrite the whole claims block
whenever any agent claims or releases, so every line inherits the timestamp of
the newest board write. Measured on 2026-09-03: a claim made on 2026-09-01 -
about 74 hours old, past the 72-hour limit - reported 12.23 hours, the identical
figure reported by three claims made that same morning, because one commit had
rewritten all four lines.

An age that can never exceed the time since the last board write cannot expire
anything. `claim_adopt` and `claim_cleanup` both read that age, which is why a
claim whose agent is long gone could never be adopted or cleaned up.

Legacy claims carry no timestamp and must keep working: absence of a stated age
falls back to blame rather than being treated as infinitely old. Expiry requires
positive evidence, never missing evidence.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "forge" / "gates"))

import workboard_claim_freshness as gate  # noqa: E402
from scripts.crew.workboard import claim_utils as cu  # noqa: E402


def _line(ts: str | None) -> str:
    base = "- agent=a1; name=A One; role=solo; parent=none; scope=x/y.py; task=T-1"
    return base if ts is None else f"{base}; claimed_at={ts}"


def _board(tmp_path: Path, line: str) -> Path:
    board = tmp_path / "WORKBOARD.md"
    board.write_text(f"# Workboard\n\n## Active Agent Claims\n{line}\n", encoding="utf-8")
    return board


def test_a_new_claim_records_when_it_was_made() -> None:
    line = cu._format_claim("a1", "x/y.py", "T-1", name="A One")
    assert "claimed_at=" in line, "the claim does not say when it was made"
    stamp = line.split("claimed_at=", 1)[1].split(";")[0].strip()
    made = datetime.fromisoformat(stamp)
    assert made.tzinfo is not None, "an age without a timezone is not an age"
    assert abs((datetime.now(timezone.utc) - made).total_seconds()) < 120


def test_the_stated_age_is_what_the_gate_uses(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(hours=74)).replace(microsecond=0)
    board = _board(tmp_path, _line(old.isoformat()))
    assert gate._declared_claim_unix(board, 4) == int(old.timestamp())
    assert gate._claim_unix(board, 4) == int(old.timestamp())


def test_a_claim_with_no_stated_age_still_works(tmp_path: Path) -> None:
    """Legacy rows must not become infinitely old the moment this ships."""
    board = _board(tmp_path, _line(None))
    assert gate._declared_claim_unix(board, 4) is None


def test_a_malformed_timestamp_is_ignored_rather_than_trusted(tmp_path: Path) -> None:
    board = _board(tmp_path, _line("not-a-date"))
    assert gate._declared_claim_unix(board, 4) is None, "garbage was parsed as an age"


def test_a_naive_timestamp_is_read_as_utc(tmp_path: Path) -> None:
    """A stamp without an offset must not shift by the reader's local zone."""
    board = _board(tmp_path, _line("2026-09-01T12:00:00"))
    expected = int(datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp())
    assert gate._declared_claim_unix(board, 4) == expected


def test_the_stamp_survives_the_claim_line_parser() -> None:
    """A new field must not break the parser every coordination tool uses."""
    line = cu._format_claim("a1", "x/y.py", "T-1", name="A One")
    agent, fields, err = cu._parse_claim_line(1, line)
    assert err == "" and agent == "a1"
    assert fields.get("scope") == "x/y.py" and fields.get("task") == "T-1"
    assert fields.get("claimed_at")
