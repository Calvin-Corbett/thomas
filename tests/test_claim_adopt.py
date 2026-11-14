"""Tests for orphaned-claim adoption (Calvin 2026-06-01).

Pins the spec:
  * a claim untouched > 48h is an ORPHAN
  * a blocked agent may ADOPT an orphan (claim + active task transfer) but only
    with a verified breakglass actor
  * an ACTIVE (non-orphan) claim can NEVER be adopted
  * adopting your own claim is a no-op
  * every adoption is audited

Staleness is driven by git-blame on the claim line; here we monkeypatch
`_line_commit_unix` to a fixed timestamp (same pattern as the cleanup tests) so
age is deterministic.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import scripts.crew.workboard.claim_adopt as adopt_mod

# A fixed "now" and the blame timestamps that make a claim orphan vs fresh.
_NOW = datetime(2026, 2, 25, 12, 0, 0, tzinfo=timezone.utc)
_ORPHAN_TS = int(_NOW.timestamp()) - int(49 * 3600)  # 49h old -> orphan (>48h)
_FRESH_TS = int(_NOW.timestamp()) - int(1 * 3600)  # 1h old -> active


def _write_workboard(tmp_path: Path, claims_block: str, active_tasks_block: str, issues_block: str = "- none") -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            "Claim format:\n"
            "`- \\`agent=<id>; scope=<path>; task=<short text>\\``\n\n"
            f"{claims_block}\n\n"
            "## Active Tasks\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; agent=<id>; scope=<path>; summary=<short text>; status=<active|blocked>\\``\n\n"
            f"{active_tasks_block}\n\n"
            "## Issues / Blockers\n\n"
            "`- \\`issue_id=<id>; task_id=<task_id>; reporter=<id>; owner=<id>; state=<open|resolved>; summary=<text>\\``\n\n"
            f"{issues_block}\n\n"
            "## Up For Grabs\n\n"
            "`- \\`task_id=<id>; scope=<path>; summary=<text>; reported_by=<id>\\``\n\n"
            "- none\n"
        ),
        encoding="utf-8",
    )
    return path


def _alice_board(tmp_path: Path) -> Path:
    return _write_workboard(
        tmp_path,
        "- agent=alice; scope=thomas/core/foo.py; task=foo work",
        "- task_id=foo-work; agent=alice; scope=thomas/core/foo.py; summary=foo work; status=active",
    )


def _set_age(monkeypatch, ts: int) -> None:
    monkeypatch.setattr(adopt_mod, "_line_commit_unix", lambda *_a, **_k: ts)


def _redirect_audit(monkeypatch, tmp_path: Path) -> Path:
    log = tmp_path / "adoption_audit.jsonl"
    monkeypatch.setattr(adopt_mod, "ADOPTION_AUDIT_LOG", log)
    return log


# --------------------------------------------------------------------------- #
# orphan detection
# --------------------------------------------------------------------------- #
def test_find_orphans_flags_stale_claim(tmp_path: Path, monkeypatch) -> None:
    board = _alice_board(tmp_path)
    _set_age(monkeypatch, _ORPHAN_TS)
    orphans = adopt_mod.find_orphans(board, now=_NOW)
    assert len(orphans) == 1
    assert orphans[0]["agent"] == "alice"
    assert orphans[0]["age_hours"] is not None and orphans[0]["age_hours"] > 48


def test_fresh_claim_is_not_an_orphan(tmp_path: Path, monkeypatch) -> None:
    board = _alice_board(tmp_path)
    _set_age(monkeypatch, _FRESH_TS)
    assert adopt_mod.find_orphans(board, now=_NOW) == []


def test_orphans_covering_paths_excludes_self(tmp_path: Path, monkeypatch) -> None:
    board = _alice_board(tmp_path)
    _set_age(monkeypatch, _ORPHAN_TS)
    # bob is blocked on alice's file -> sees alice's orphan
    hits = adopt_mod.orphans_covering_paths(board, ["thomas/core/foo.py"], exclude_agent="bob", now=_NOW)
    assert len(hits) == 1 and hits[0]["agent"] == "alice"
    assert hits[0]["covered_paths"] == ["thomas/core/foo.py"]
    # alice doesn't get offered her own claim
    assert adopt_mod.orphans_covering_paths(board, ["thomas/core/foo.py"], exclude_agent="alice", now=_NOW) == []


# --------------------------------------------------------------------------- #
# adoption
# --------------------------------------------------------------------------- #
def test_adopt_transfers_orphan_claim_and_task(tmp_path: Path, monkeypatch) -> None:
    board = _alice_board(tmp_path)
    _set_age(monkeypatch, _ORPHAN_TS)
    audit = _redirect_audit(monkeypatch, tmp_path)

    ok, msg, details = adopt_mod.adopt(
        board,
        adopter="bob",
        scope="thomas/core/foo.py",
        reason="alice stranded this; taking over to finish",
        authorized_by="WORKSTATION\\corbe",
        name="Bob",
        now=_NOW,
    )
    assert ok, msg
    text = board.read_text(encoding="utf-8")
    # claim + active task now owned by bob, not alice
    assert "agent=bob" in text
    assert "agent=alice" not in text
    assert details["from_agent"] == "alice" and details["to_agent"] == "bob"
    assert details["active_tasks_transferred"] == 1
    # audit row written
    rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows and rows[0]["event"] == "claim_adopted"
    assert rows[0]["from_agent"] == "alice" and rows[0]["authorized_by"] == "WORKSTATION\\corbe"


def test_cannot_adopt_active_claim(tmp_path: Path, monkeypatch) -> None:
    board = _alice_board(tmp_path)
    _set_age(monkeypatch, _FRESH_TS)  # alice's claim is fresh/active
    _redirect_audit(monkeypatch, tmp_path)
    before = board.read_text(encoding="utf-8")

    ok, msg, details = adopt_mod.adopt(
        board,
        adopter="bob",
        owner="alice",
        reason="trying to seize active work",
        authorized_by="WORKSTATION\\corbe",
        now=_NOW,
    )
    assert ok is False
    assert "not an orphan" in msg.lower() or "active" in msg.lower()
    assert details.get("orphan") is False
    assert board.read_text(encoding="utf-8") == before  # board untouched


def test_adopt_requires_breakglass_actor(tmp_path: Path, monkeypatch) -> None:
    board = _alice_board(tmp_path)
    _set_age(monkeypatch, _ORPHAN_TS)
    ok, msg, _ = adopt_mod.adopt(
        board,
        adopter="bob",
        owner="alice",
        reason="legitimate takeover of stranded work",
        authorized_by="",  # no verified human
        now=_NOW,
    )
    assert ok is False
    assert "breakglass" in msg.lower() or "authoriz" in msg.lower()


def test_adopt_requires_substantive_reason(tmp_path: Path, monkeypatch) -> None:
    board = _alice_board(tmp_path)
    _set_age(monkeypatch, _ORPHAN_TS)
    ok, msg, _ = adopt_mod.adopt(board, adopter="bob", owner="alice", reason="short", authorized_by="corbe", now=_NOW)
    assert ok is False
    assert "reason" in msg.lower()


def test_adopt_own_claim_is_noop(tmp_path: Path, monkeypatch) -> None:
    board = _alice_board(tmp_path)
    _set_age(monkeypatch, _ORPHAN_TS)
    ok, msg, details = adopt_mod.adopt(
        board, adopter="alice", owner="alice", reason="refreshing my own claim", authorized_by="corbe", now=_NOW
    )
    assert ok is True
    assert details.get("already_owned") is True


def test_adopt_unknown_target_is_rejected(tmp_path: Path, monkeypatch) -> None:
    board = _alice_board(tmp_path)
    _set_age(monkeypatch, _ORPHAN_TS)
    ok, msg, _ = adopt_mod.adopt(
        board,
        adopter="bob",
        owner="nobody",
        reason="adopting a claim that does not exist",
        authorized_by="corbe",
        now=_NOW,
    )
    assert ok is False
    assert "no matching claim" in msg.lower()
