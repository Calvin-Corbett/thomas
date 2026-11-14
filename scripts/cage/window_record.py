"""The window's record: one write-once file per event, each naming the one before (spec section 8.4).

It lives in C:\\ProgramData\\ThomasWindow, which scripts/cage/enable_window.ps1 makes owned by Administrators: your
account may create a file there and never change or remove one, the cage's account may read, and nothing else may
write. A file is written once, from its creating handle, and flushed to disk. Each event names the hash of the one
before, and the reader checks that chain and the sequence (review D11): a gap or a change shows, and a window
record with one refuses every window until it is looked at. The record is never authority: nothing here opens a window or lands a change, and
recovery after a crash reads dev's own trailers, never this.

Before a landing moves dev, a ``landing_intent`` event is written; after it, ``landed`` (or ``landing_moved``). An
intent with neither after it is a landing the promoter stopped inside; ``unfinished`` lists them for the window loop,
which settles each one from dev.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

from scripts.cage import self_change_checks as checks

RECORD_ROOT = Path(r"C:\ProgramData\ThomasWindow")
EVENTS = frozenset(
    {
        "window_opened",
        "window_closed",
        "landing_intent",
        "landed",
        "landing_moved",
        "refused",
        "after_check",
        "after_posted",
        "undo_landed",
        "recovered",
        "revert_pending",
        "revert_started",
        "revert_finished",
    }
)
_NAME = re.compile(r"(\d{8})-([a-z_]+)\.json")
_LIMIT = 256 * 1024


def _hash(record: dict[str, object]) -> str:
    body = {key: value for key, value in record.items() if key != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class Record:
    def __init__(self, root: Path = RECORD_ROOT, *, clock: Callable[[], float] = time.time) -> None:
        self.root = Path(root)
        self.clock = clock

    def usable(self) -> str:
        """Why no window may open with this record, or ""."""
        if not self.root.is_dir() or self.root.is_symlink():
            return f"the window's record folder {self.root} is missing; run scripts/cage/enable_window.ps1"
        if any(event.get("torn") for event in self.events()):
            return "the window's record chain is torn or incomplete; no window work may continue"
        return ""

    def events(self) -> list[dict[str, object]]:
        """Every event in order. One that cannot be read, or whose hash is not its own, is {"seq", "torn": True}."""
        found: list[dict[str, object]] = []
        expected, previous = 1, ""
        for path in sorted(self.root.glob("*.json")) if self.root.is_dir() else []:
            match = _NAME.fullmatch(path.name)
            if not match:
                continue
            raw = b""
            try:
                with path.open("rb") as handle:
                    raw = handle.read(_LIMIT + 1)
                data = json.loads(raw.decode("utf-8"))
                good = (
                    isinstance(data, dict)
                    and data.get("hash") == _hash(data)
                    and len(raw) <= _LIMIT
                    and not path.is_symlink()
                    and type(data.get("seq")) is int
                    and data["seq"] == int(match.group(1)) == expected
                    and data.get("name") == match.group(2)
                    and data.get("name") in EVENTS
                    and data.get("prev") == previous
                )
            except (OSError, ValueError):
                data, good = {}, False
            marker = {
                "seq": int(match.group(1)),
                "name": match.group(2),
                "torn": True,
                "bytes_hash": hashlib.sha256(raw).hexdigest(),
            }
            found.append(data if good else marker)
            expected = int(match.group(1)) + 1
            previous = (
                str(data.get("hash") or marker["bytes_hash"]) if isinstance(data, dict) else str(marker["bytes_hash"])
            )
        return found

    def event(self, name: str, **fields: object) -> dict[str, object]:
        """Write one event after the newest, and return it."""
        if name not in EVENTS:
            raise ValueError(f"no window event {name!r}")
        why = self.usable()  # never made here: a folder your account made would be yours to rewrite
        if why:
            raise OSError(why)
        for _attempt in range(3):
            last = self.events()[-1:] or [{}]
            seq = int(last[0].get("seq", 0)) + 1
            prev = str(last[0].get("hash") or last[0].get("bytes_hash") or "")
            record: dict[str, object] = {"seq": seq, "prev": prev, "name": name, "at": self.clock(), **fields}
            record["hash"] = _hash(record)
            try:
                with open(self.root / f"{seq:08d}-{name}.json", "xb") as handle:
                    handle.write(json.dumps(record, sort_keys=True).encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
                return record
            except FileExistsError:
                continue  # another writer took this number: read again
        raise OSError("the window's record could not take a new event")

    def unfinished(self) -> list[dict[str, object]]:
        """Every ``landing_intent`` with no ``landed`` or ``landing_moved`` for the same commit after it."""
        open_intents: dict[str, dict[str, object]] = {}
        for event in self.events():
            commit = str(event.get("commit") or "")
            if event.get("name") == "landing_intent" and commit:
                open_intents[commit] = event
            elif event.get("name") in ("landed", "landing_moved", "recovered") and commit:
                open_intents.pop(commit, None)
        return list(open_intents.values())


def landed_on(repo: Path, branch: str, commit: str) -> bool:
    """Whether *branch* holds *commit*: how a stopped landing is settled."""
    return checks.run_git(repo, "merge-base", "--is-ancestor", commit, f"refs/heads/{branch}").returncode == 0


def window_summary(repo: Path, branch: str, window_id: str) -> list[dict[str, object]]:
    """Every change *branch* holds that landed in *window_id*, read from dev itself: its Submission-Id, commit, files,
    lines added and deleted, and whether a later commit undid it."""
    found = checks.run_git(repo, "log", f"refs/heads/{branch}", "--format=%H", f"--grep=(window {window_id},")
    keys = "%(trailers:key=Thomas-Submission-Id,valueonly)%x00%(trailers:key=Thomas-Committed-By,valueonly)"
    rows: list[dict[str, object]] = []
    for commit in found.stdout.split():
        sid, committer = (part.strip() for part in (checks.run_git(repo, "show", "-s", f"--format={keys}", commit)
                                                     .stdout.split("\0") + ["", ""])[:2])  # fmt: skip
        if committer != "self-change-promoter" or not sid:
            continue
        added = deleted = 0
        files: list[str] = []
        for line in checks.run_git(repo, "diff", "--numstat", f"{commit}^", commit).stdout.splitlines():
            plus, minus, path = (line.split("\t", 2) + ["", "", ""])[:3]
            files.append(path)
            added += int(plus) if plus.isdigit() else 0
            deleted += int(minus) if minus.isdigit() else 0
        undone = checks.run_git(
            repo, "log", f"refs/heads/{branch}", "--format=%H", f"--grep=^Thomas-Submission-Id: undo-{sid}$"
        ).stdout.split()
        rows.append({"sid": sid, "commit": commit, "files": files, "added": added, "deleted": deleted,
                     "undone": undone[0] if undone else ""})  # fmt: skip
    return list(reversed(rows))


__all__ = ["EVENTS", "RECORD_ROOT", "Record", "landed_on", "window_summary"]
