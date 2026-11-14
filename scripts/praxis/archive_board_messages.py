#!/usr/bin/env python3
"""Move old acknowledged messages out of WORKBOARD.md into an append-only archive.

    python scripts/praxis/archive_board_messages.py             # dry run (default)
    python scripts/praxis/archive_board_messages.py --apply     # archive, then shrink the board
    python scripts/praxis/archive_board_messages.py --apply --strict   # keep every unacked row
    python scripts/praxis/archive_board_messages.py --restore all|YYYY-MM

Order of an apply: take the board lock, plan, prove in memory that restoring the
plan gives the original bytes back, append each month's block to
plans/thomas/archive/messages-YYYY-MM.txt and fsync, re-read and verify every
block, and only then swap the board in through a temp file. A run killed at any
point leaves either the old board (and a complete, harmless block) or the new
board; the next run reuses or retires the block. See board_archive.py for the
retention rule.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.praxis import archive_io, archive_restore, board_archive, board_restore  # noqa: E402

DEFAULT_KEEP_DAYS = 7.0
# Unacked rows older than this move too: nobody has acked them in two weeks and nobody will, and on a
# busy board they are most of what is left (heartbeat pings, notices to agents that no longer run).
# They are archived, not deleted: --restore puts them back byte for byte. --strict turns this off.
DEFAULT_STALE_OPEN_DAYS = 14.0
CRASH_ENV = "PRAXIS_ARCHIVE_CRASH_AFTER_ARCHIVE"  # test hook: die between archive write and board swap
TAKEOVER_MARKER = "workboard_takeover_transaction.json"
FILE_HEAD = (
    "<!-- WORKBOARD message archive. Append-only: never edit or rewrite. Written and restored by "
    "scripts/praxis/archive_board_messages.py. Rows are the original board text, one per line. -->\n\n"
)


def _retire_orphans(archive_dir: Path, board_keys: set[str], planned: set[str], now: datetime) -> list[str]:
    """A complete block whose rows are all still on the board is a crashed run's leftover."""
    retired = []
    for path in sorted(archive_dir.glob(f"messages-*{archive_io.ARCHIVE_SUFFIX}")):
        state = archive_io.read_state(path)
        for block in state.active_blocks():
            if block.ident not in planned and set(block.keys) <= board_keys:
                note = {"id": block.ident, "why": "rows still on board", "at": archive_io.iso(now)}
                archive_io.append_bytes(path, f"<!-- abandoned {json.dumps(note)} -->\n".encode())
                retired.append(block.ident)
    return retired


def build(data: bytes, plan: board_archive.Plan, now: datetime) -> tuple[list[bytes], dict[str, tuple[str, bytes]]]:
    """New board lines and {month: (block id, block bytes)}; refuses unless the round trip is exact."""
    lines = data.splitlines(keepends=True)
    by_month: dict[str, list[board_archive.Moved]] = {}
    for item in plan.moved:
        by_month.setdefault(item.month, []).append(item)
    blocks: dict[str, tuple[str, bytes]] = {}
    for month, items in sorted(by_month.items()):
        runs = board_archive.anchors_for(lines, items)
        blocks[month] = board_archive.block_bytes(
            [i.text for i in items], [i.key for i in items], runs, eol=plan.eol, at=archive_io.iso(now)
        )
    gone = {item.idx for item in plan.moved}
    shrunk = [raw for idx, raw in enumerate(lines) if idx not in gone]
    parsed = [board_restore.parse_archive(raw).blocks for _, raw in blocks.values()]
    back, _, stray = board_restore.restore_blocks(shrunk, [b for group in parsed for b in group])
    if b"".join(back) != data or stray:
        raise board_archive.ArchiveRefusal("restoring this plan would not reproduce the board byte for byte")
    return shrunk, blocks


def capped(plan: board_archive.Plan, max_rows: int) -> board_archive.Plan:
    """At most ``max_rows`` rows (oldest on the board first); the rest wait for the next run."""
    if max_rows <= 0 or len(plan.moved) <= max_rows:
        return plan
    kept = {**plan.kept, "batch-limit": len(plan.moved) - max_rows}
    return replace(plan, moved=plan.moved[:max_rows], kept=kept)


def _wait_for_git(root: Path | None) -> None:
    """Skip (not fail) while a commit or stash holds git's index: it reads and rewrites this board."""
    reason = archive_io.busy_reason(root) if root is not None else ""
    if reason:
        raise archive_io.Busy(reason)


def apply_archive(
    board: Path,
    archive_dir: Path,
    *,
    now: datetime,
    keep_days: float,
    stale_open_days: float,
    max_rows: int = 0,
    root: Path | None = None,
) -> dict[str, object]:
    _wait_for_git(root)
    archive_io.sweep_stale_temps(board)
    data = board.read_bytes()
    plan = capped(
        board_archive.make_plan(data, now=now, keep_days=keep_days, stale_open_days=stale_open_days), max_rows
    )
    result: dict[str, object] = {
        "board_bytes_before": len(data),
        "rows_total": plan.total,
        "rows_moved": len(plan.moved),
        "kept_by_reason": plan.kept,
        "stale_archived_by_priority": board_archive.stale_by_priority(plan.moved),
    }
    shrunk, blocks = build(data, plan, now) if plan.moved else ([], {})
    keys = {board_archive.row_key(r) for r in data.splitlines(keepends=True) if r.strip().startswith(b"- ")}
    result["retired_orphans"] = _retire_orphans(archive_dir, keys, {i for i, _ in blocks.values()}, now)
    for month, (ident, raw) in blocks.items():
        path = archive_io.archive_path(archive_dir, month)
        if not archive_io.read_state(path).is_active(ident):
            archive_io.append_bytes(path, raw if path.exists() and path.stat().st_size else FILE_HEAD.encode() + raw)
        if not archive_io.read_state(path).is_active(ident):
            raise RuntimeError(f"{path.name}: block {ident} failed verification after writing; board untouched")
    result["archive_files"] = {m: archive_io.archive_path(archive_dir, m).name for m in blocks}
    if not plan.moved:
        result["board_bytes_after"] = len(data)
        return result
    if os.environ.get(CRASH_ENV):
        os._exit(137)
    _wait_for_git(root)
    if board.read_bytes() != data:
        raise RuntimeError("the board changed while archiving; nothing was swapped in")
    archive_io.atomic_replace(board, b"".join(shrunk))
    result["board_bytes_after"] = board.stat().st_size
    return result


restore_archive = archive_restore.restore_archive


def locked(coordination: Path, lock_file: Path, timeout: float, fn, *args, **kwargs) -> dict[str, object]:
    """Run ``fn`` under the board lock, refusing while a takeover transaction pins the board."""
    if (coordination / TAKEOVER_MARKER).exists():
        raise board_archive.ArchiveRefusal("a takeover transaction is in progress; try again after it ends")
    with archive_io.board_lock(lock_file, timeout):
        return fn(*args, **kwargs)


def dry_run(
    board: Path, *, now: datetime, keep_days: float, stale_open_days: float, max_rows: int = 0
) -> dict[str, object]:
    data = board.read_bytes()
    plan = capped(
        board_archive.make_plan(data, now=now, keep_days=keep_days, stale_open_days=stale_open_days), max_rows
    )
    moved_bytes = sum(len(m.text) + len(board_archive.EOL_BYTES[plan.eol]) for m in plan.moved)
    months: dict[str, int] = {}
    for item in plan.moved:
        months[item.month] = months.get(item.month, 0) + 1
    return {
        "board_bytes_before": len(data),
        "board_bytes_after": len(data) - moved_bytes,
        "rows_total": plan.total,
        "rows_moved": len(plan.moved),
        "bytes_moved": moved_bytes,
        "moved_by_month": months,
        "kept_by_reason": plan.kept,
        "stale_archived_by_priority": board_archive.stale_by_priority(plan.moved),
    }


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(_REPO_ROOT), help="checkout whose board to archive")
    ap.add_argument("--board", default="", help="board path (default: <root>/plans/thomas/WORKBOARD.md)")
    ap.add_argument("--archive-dir", default="", help="default: <board dir>/archive")
    ap.add_argument("--lock-file", default="", help="default: <primary checkout>/runtime/coordination/workboard.lock")
    ap.add_argument("--keep-days", type=float, default=DEFAULT_KEEP_DAYS, help="rows newer than this stay (default 7)")
    ap.add_argument(
        "--stale-open-days",
        type=float,
        default=DEFAULT_STALE_OPEN_DAYS,
        help="also move UNACKED rows older than this many days (default 14; 0 = never)",
    )
    ap.add_argument("--strict", action="store_true", help="keep every unacked row, whatever its age")
    ap.add_argument("--max-rows", type=int, default=0, help="move at most this many rows per run (0 = all)")
    ap.add_argument(
        "--min-board-bytes",
        type=int,
        default=0,
        help="with --apply, do nothing (and take no lock) while the board is smaller than this: a cheap periodic trigger",
    )
    ap.add_argument("--lock-timeout", type=float, default=5.0)
    ap.add_argument("--now", default="", help="ISO time to measure ages from (tests)")
    ap.add_argument("--json", action="store_true")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print counts and bytes, change nothing (default)")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--restore", metavar="MONTH|all", default="")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()
    board = Path(args.board) if args.board else root / "plans" / "thomas" / "WORKBOARD.md"
    archive_dir = Path(args.archive_dir) if args.archive_dir else board.parent / "archive"
    coordination = archive_io.canonical_root(root) / "runtime" / "coordination"
    lock_file = Path(args.lock_file) if args.lock_file else coordination / "workboard.lock"
    now = board_archive.parse_time(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print("archive_board_messages: --now is not an ISO time", file=sys.stderr)
        return 2
    settings = {
        "keep_days": args.keep_days,
        "stale_open_days": 0.0 if args.strict else args.stale_open_days,
        "max_rows": args.max_rows,
    }
    if args.apply and args.min_board_bytes and board.stat().st_size < args.min_board_bytes:
        print(json.dumps({"mode": "apply", "skipped": f"board is under {args.min_board_bytes} bytes"}))
        return 0
    try:
        if args.apply:
            _wait_for_git(root)
            result = locked(
                coordination,
                lock_file,
                args.lock_timeout,
                apply_archive,
                board,
                archive_dir,
                now=now,
                root=root,
                **settings,
            )
        elif args.restore:
            result = locked(
                coordination, lock_file, args.lock_timeout, restore_archive, board, archive_dir, args.restore, now
            )
        else:
            result = dry_run(board, now=now, **settings)
    except archive_io.Busy as exc:
        if args.apply:  # another apply, a writer, or git has the board: a clean skip, nothing changed
            print(json.dumps({"mode": "apply", "busy": str(exc)}))
            return 0
        print(f"archive_board_messages: refused: {exc}", file=sys.stderr)
        return 3
    except board_archive.ArchiveRefusal as exc:
        print(f"archive_board_messages: refused: {exc}", file=sys.stderr)
        return 2
    mode = "apply" if args.apply else "restore" if args.restore else "dry-run"
    print(json.dumps({"mode": mode, **result}, indent=None if args.json else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
