"""Files a process wrote into a shared checkout and has not committed yet.

A scoped commit takes whole files from the working copy. When two sessions share one checkout and both write one file,
whoever commits first takes the other's lines under their own message: on 2026-11-06 a Build-header commit (4d1f99cfc)
carried a voice landing's line in chat.html. A writer that leaves files uncommitted for a while holds them here, and
commit.py refuses to commit a file another live process holds until that process has landed it.

One JSON file per holding process, in ``<git dir>/thomas-inflight/<pid>.json``::

    {"pid": 41860, "started": 1762462920.5, "agent": "claude", "why": "landing the voice change",
     "since": "2026-11-06T15:02:00", "files": {"thomas/server/web/chat.html": "<git blob id of what it wrote>"}}

A hold counts for nothing once its process has ended (pid and start time no longer match), or once HEAD already holds
what it wrote. A hold is the committer's own when its process is the committer or one of the committer's parents, so a
landing tool that runs commit.py as its child commits its own files. Identity is the process, not the agent id, because
several sessions can share one agent id.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psutil

from scripts.crew.brief import git_reads

FOLDER = "thomas-inflight"
_READ_TRIES = 5  # Windows refuses a read while another process replaces the file; a short wait clears it


@dataclass(frozen=True)
class Hold:
    path: str
    pid: int
    agent: str
    why: str
    since: str


def _text(data: bytes) -> str:
    return data.decode("utf-8", "replace").strip()


def _git(repo_root: Path, *args: str) -> str:
    # git is started in one place for the crew scripts (git_reads.run_git); a second launcher here would be a direct
    # launch outside the sandbox slot, which test_every_command_runs_through_the_sandbox_slot refuses.
    done = git_reads.run_git(repo_root, args)
    if done.returncode:
        raise RuntimeError(_text(done.stderr) or f"git {' '.join(args)} failed")
    return _text(done.stdout)


def folder(repo_root: Path) -> Path:
    common = Path(_git(repo_root, "rev-parse", "--git-common-dir"))
    return (common if common.is_absolute() else repo_root / common) / FOLDER


def _blob(repo_root: Path, rel: str) -> str:
    """The blob id git would store for the file as it is on disk now; '' when the file is gone."""
    if not (repo_root / rel).exists():
        return ""
    return _git(repo_root, "hash-object", "--", rel)


def _head_blob(repo_root: Path, rel: str) -> str:
    done = git_reads.run_git(repo_root, ["rev-parse", "--verify", "--quiet", f"HEAD:{rel}"])
    return _text(done.stdout) if done.returncode == 0 else ""


_HISTORY_COMMITS = 200


def _was_committed(repo_root: Path, rel: str, wrote: str) -> bool:
    """Whether ``wrote`` is a version of the file some commit already holds, newest or not.

    A hold ends when its lines are committed. Compared with HEAD alone, a file its holder committed and then anyone
    committed again read "not committed yet" for as long as the holder's session stayed open, which is days: on
    2026-11-09 a hold from 09:19, committed at 10:00, still refused another session's commit that evening.
    """
    if not wrote:
        return False
    done = git_reads.run_git(
        repo_root, ["log", f"-n{_HISTORY_COMMITS}", "--format=", "--raw", "--no-abbrev", "--no-renames", "--", rel]
    )
    if done.returncode != 0:
        return False  # git could not say: the hold stands
    for line in _text(done.stdout).splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].startswith(":") and parts[3] == wrote:
            return True
    return False


def _started(pid: int) -> float | None:
    try:
        return psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return None


def _read(path: Path) -> dict | None:
    for attempt in range(_READ_TRIES):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
        except (ValueError, OSError):
            return None
    return None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    spare = path.with_suffix(f".{os.getpid()}.tmp")
    spare.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(spare, path)


def hold(repo_root: Path, paths: Iterable[str], *, pid: int, why: str, agent: str = "") -> None:
    """Record that process ``pid`` wrote these files as they are on disk now and will commit them."""
    started = _started(pid)
    if started is None:
        raise ValueError(f"process {pid} is not running, so it cannot hold files")
    record = folder(repo_root) / f"{pid}.json"
    data = _read(record) or {}
    if data.get("started") != started:
        data = {}
    files = dict(data.get("files") or {})
    files.update({rel: _blob(repo_root, rel) for rel in paths})
    _write(
        record,
        {
            "pid": pid,
            "started": started,
            "agent": agent or str(data.get("agent") or ""),
            "why": why or str(data.get("why") or ""),
            "since": str(data.get("since") or datetime.now().isoformat(timespec="seconds")),
            "files": files,
        },
    )


def release(repo_root: Path, *, pid: int, paths: Iterable[str] | None = None) -> None:
    """Drop the hold on these files (all of them when ``paths`` is None)."""
    record = folder(repo_root) / f"{pid}.json"
    data = _read(record)
    if data is None:
        return
    dropped = set(paths or ())
    files = {} if paths is None else {k: v for k, v in (data.get("files") or {}).items() if k not in dropped}
    if files:
        _write(record, {**data, "files": files})
    else:
        record.unlink(missing_ok=True)


def _mine(pid: int, me: int) -> bool:
    if pid == me:
        return True
    try:
        return pid in {parent.pid for parent in psutil.Process(me).parents()}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def held_by_others(repo_root: Path, paths: Sequence[str], *, me: int | None = None) -> list[Hold]:
    """The files among ``paths`` that another live process wrote and has not committed yet."""
    where = folder(repo_root)
    if not where.is_dir():
        return []
    me = os.getpid() if me is None else me
    wanted = set(paths)
    found: list[Hold] = []
    for record in sorted(where.glob("*.json")):
        data = _read(record)
        if not data:
            continue
        pid = int(data.get("pid") or 0)
        if not pid or _started(pid) != data.get("started"):
            record.unlink(missing_ok=True)  # its process has ended: nothing is in flight any more
            continue
        if _mine(pid, me):
            continue
        agent, why, since = (str(data.get(key) or "") for key in ("agent", "why", "since"))
        for rel, wrote in sorted((data.get("files") or {}).items()):
            if rel in wanted and _head_blob(repo_root, rel) != wrote and not _was_committed(repo_root, rel, wrote):
                found.append(Hold(rel, pid, agent, why, since))
    return found


def explain(held: Sequence[Hold]) -> str:
    """One plain sentence per held file, for the refusal."""
    lines = []
    for item in held:
        who = f"process {item.pid}" + (f" ({item.agent})" if item.agent else "")
        doing = f": {item.why}" if item.why else ""
        lines.append(f"{item.path} holds lines {who} wrote and has not committed yet{doing}, since {item.since}")
    return (
        "; ".join(lines)
        + ". Committing now would take those lines under your message. Wait until that work commits the file,"
        " then commit again."
    )


def refusal(repo_root: Path, paths: Sequence[str]) -> dict[str, str] | None:
    """commit.py's refusal fields when another live process holds one of ``paths``; None when nothing does.

    A file holding lines another process wrote and has not committed would carry them under the committer's message
    (4d1f99cfc took a voice landing's chat.html line, 2026-11-06).
    """
    try:
        held = held_by_others(repo_root, paths)
    except (OSError, RuntimeError) as exc:
        return {"blocker_class": "broken_repo_tool", "message": f"could not read what other sessions hold: {exc}"}
    if not held:
        return None
    return {
        "blocker_class": "held_by_another_session",
        "message": explain(held),
        "next_step": (
            "Wait for that work to commit the file, then commit again; or leave the file out with --include. If both"
            " of you changed it, the other session can hand its lines to you: `python -m scripts.crew.brief.inflight"
            " release --mine <file>` run from that session."
        ),
    }


# The desktop app runs every Code session under one Claude.exe from WindowsApps; each session is its own claude.exe
# (or node running claude-code) beneath it. The session process lives exactly as long as the session, and the session's
# own commit.py runs under it, so its holds count as its own.
_SHARED_APP_MARK = "windowsapps"


def session_pid(start: int | None = None) -> int | None:
    """The Claude Code session process above ``start`` (this process by default), or None outside a session."""
    override = os.environ.get("THOMAS_INFLIGHT_SESSION_PID", "").strip()
    if override.isdigit():
        return int(override)
    try:
        chain = psutil.Process(start or os.getpid()).parents()
    except psutil.Error:
        return None
    for proc in chain:
        try:
            name, line = proc.name().lower(), " ".join(proc.cmdline()).lower()
        except psutil.Error:
            continue
        if _SHARED_APP_MARK in line:
            return None  # reached the shared desktop app: no session of our own below it
        if name in ("claude", "claude.exe") or (name.startswith("node") and "claude-code" in line):
            return proc.pid
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hold files a process wrote and will commit, or drop the hold.")
    sub = parser.add_subparsers(dest="action", required=True)
    held = sub.add_parser("hold", help="hold files a process wrote and will commit")
    held.add_argument("--pid", type=int, required=True)
    held.add_argument("--why", default="")
    held.add_argument("--agent", default="")
    held.add_argument("paths", nargs="+")
    free = sub.add_parser("release", help="drop a process's hold, handing its lines to whoever commits the file")
    whose = free.add_mutually_exclusive_group(required=True)
    whose.add_argument("--pid", type=int)
    whose.add_argument("--mine", action="store_true", help="the Claude Code session this runs in")
    free.add_argument("paths", nargs="*")
    sub.add_parser("list", help="show what is held now")
    args = parser.parse_args(argv)
    root = Path.cwd()
    if args.action == "hold":
        hold(root, args.paths, pid=args.pid, why=args.why, agent=args.agent)
    elif args.action == "release":
        pid = session_pid() if args.mine else args.pid
        if pid is None:
            parser.error("--mine found no Claude Code session above this process")
        release(root, pid=pid, paths=args.paths or None)
    elif folder(root).is_dir():
        for record in sorted(folder(root).glob("*.json")):
            print(record.name, _read(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
