"""A read-only window into the caged Thomas: what it runs, what each run is doing, and what a self-fix has changed.

The cage's account owns the self-fix copies ("greens", ``thomas.core.green_place``) and the processes Build starts, and
your account is refused by design: it cannot list the folder or even read its permissions. Opening that to you would
open the cage to everything that runs as you. So the cage's own server answers instead, read-only, and a person, another
AI, or Thomas himself asks it: nothing here writes, runs a command a caller chose, or leaves the green it was asked about.

Every function returns plain data and never raises for a missing thing; a path that escapes, a secret-looking name, a
binary file or a file over the cap is refused with a reason, and the reason is the answer.
"""

from __future__ import annotations

import collections
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from thomas.core.cage_processes import label, processes, redact

FILE_CAP = 256 * 1024
DIFF_CAP = 200 * 1024
TAIL_BYTES = 400 * 1024
_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_SECRET_NAME = re.compile(
    r"(^\.env|secret|token|credential|passwd|password|id_rsa|id_ed25519|\.pem$|\.key$|\.pfx$)", re.I
)
WRITE_TOOLS = ("fs.write", "fs.edit", "fs.patch", "apply_patch", "fs.create", "fs.delete", "fs.move", "diff.")


def _events(path: Path) -> list[dict[str, Any]]:
    """The last events of one run transcript (only its tail is read, so a long run costs the same as a short one)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - TAIL_BYTES))
            data = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = data.splitlines()[1:] if size > TAIL_BYTES else data.splitlines()
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _flags(events: list[dict[str, Any]]) -> list[str]:
    calls = [e for e in events if e.get("fc") == "tool_started"]
    flags = []
    repeated = collections.Counter((e.get("name"), (e.get("text") or "")[:160]) for e in calls[-60:])
    for (name, text), n in repeated.most_common(2):
        if n >= 4:
            flags.append(f"same call {n} times: {name} {text[:80]}".replace("\n", " "))
    errors = collections.Counter(
        (e.get("name"), (e.get("text") or "")[:100])
        for e in events[-200:]
        if e.get("fc") == "tool_result" and e.get("is_error")
    )
    for (name, text), n in errors.most_common(2):
        if n >= 3:
            flags.append(f"same error {n} times: {name} {text}".replace("\n", " "))
    since = 0
    for e in calls:
        since = 0 if (e.get("name") or "").startswith(WRITE_TOOLS) else since + 1
    if since >= 60:
        flags.append(f"{since} tool calls since the last write")
    return flags


def _describe(event: dict[str, Any]) -> dict[str, Any]:
    kind = event.get("fc")
    text = redact(str(event.get("text") or event.get("question") or ""))[:220].replace("\n", " ")
    return {
        "kind": kind,
        "tool": event.get("name"),
        "error": bool(event.get("is_error")),
        "text": text,
        "at": event.get("ts"),
    }


def runs(agent_dir: Path, hours: float = 3.0, last: int = 10) -> dict[str, Any]:
    """Every run that wrote lately: how long ago, how busy, its last moves, and anything that looks like a loop."""
    cutoff = time.time() - max(0.05, min(hours, 72.0)) * 3600
    out = []
    try:
        files = [p for p in Path(agent_dir).glob("transcript-*.txt") if p.stat().st_mtime > cutoff]
    except OSError:
        files = []
    for path in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:60]:
        events = _events(path)
        calls = sum(1 for e in events if e.get("fc") == "tool_started")
        errors = sum(1 for e in events if e.get("fc") == "tool_result" and e.get("is_error"))
        moves = [_describe(e) for e in events if e.get("fc") in ("tool_started", "say", "ask", "reason")][-last:]
        out.append(
            {
                "run": path.stem.removeprefix("transcript-"),
                "idle_s": int(time.time() - path.stat().st_mtime),
                "tool_calls": calls,
                "errors": errors,
                "flags": _flags(events),
                "last_moves": moves,
            }
        )
    return {"ok": True, "hours": hours, "runs": out}


def run_tail(agent_dir: Path, run: str, n: int = 40) -> dict[str, Any]:
    """The last *n* moves of one run, in order."""
    if not _ID.match(run):
        return {"ok": False, "error": "not a run id"}
    path = Path(agent_dir) / (f"transcript-{run}.txt")
    if not path.is_file():
        return {"ok": False, "error": "no such run"}
    events = [e for e in _events(path) if e.get("fc") in ("tool_started", "tool_result", "say", "ask", "reason")]
    return {"ok": True, "run": run, "moves": [_describe(e) for e in events[-max(1, min(n, 200)) :]]}


def greens(green_root: Path) -> dict[str, Any]:
    """The self-fix copies that exist, newest first."""
    base = Path(green_root) / "work"
    items = []
    try:
        for p in base.iterdir():
            if p.is_dir() and _ID.match(p.name):
                items.append({"id": p.name, "modified_s_ago": int(time.time() - p.stat().st_mtime)})
    except OSError as exc:
        return {"ok": False, "error": f"cannot list greens: {exc.__class__.__name__}"}
    items.sort(key=lambda i: i["modified_s_ago"])
    return {"ok": True, "greens": items}


def _green_dir(green_root: Path, green_id: str) -> Path | None:
    if not _ID.match(green_id):
        return None
    base = (Path(green_root) / "work").resolve()
    path = (base / green_id).resolve()
    return path if path.parent == base and path.is_dir() else None


def _inside(root: Path, rel: str) -> Path | None:
    """*rel* inside *root*, links resolved, and not inside a .git folder; None when it escapes."""
    if not rel or "\x00" in rel:
        return None
    path = (root / rel).resolve()
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    return None if ".git" in parts else path


def _git(root: Path, *args: str) -> tuple[int, str]:
    try:
        done = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "core.quotepath=off", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=25,
            encoding="utf-8",
            errors="replace",
            creationflags=0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"git could not run: {exc.__class__.__name__}"
    return done.returncode, done.stdout


def green_status(green_root: Path, green_id: str) -> dict[str, Any]:
    """What a self-fix has changed so far: the changed files and how much each changed."""
    root = _green_dir(green_root, green_id)
    if root is None:
        return {"ok": False, "error": "no such green"}
    code, status = _git(root, "status", "--porcelain=v1", "-uall")
    _, stat = _git(root, "diff", "--stat", "--no-ext-diff", "HEAD")
    _, head = _git(root, "log", "-1", "--format=%h %s")
    files = [line for line in status.splitlines() if line.strip()]
    return {
        "ok": code == 0,
        "green": green_id,
        "base": head.strip(),
        "changed": len(files),
        "files": files[:400],
        "stat": stat.splitlines()[-1] if stat.strip() else "",
    }


def green_diff(green_root: Path, green_id: str, rel: str) -> dict[str, Any]:
    """One changed file's diff against the green's base."""
    root = _green_dir(green_root, green_id)
    path = _inside(root, rel) if root else None
    if root is None or path is None:
        return {"ok": False, "error": "no such green or path"}
    if _SECRET_NAME.search(path.name):
        return {"ok": False, "error": "refused: the name looks like a secret"}
    _, diff = _git(root, "diff", "--no-ext-diff", "HEAD", "--", str(path.relative_to(root)))
    return {"ok": True, "path": rel, "diff": redact(diff[:DIFF_CAP]), "truncated": len(diff) > DIFF_CAP}


def green_file(green_root: Path, green_id: str, rel: str) -> dict[str, Any]:
    """One text file from a green, whole up to a cap. Secret-named files, binary files and anything outside it are refused."""
    root = _green_dir(green_root, green_id)
    path = _inside(root, rel) if root else None
    if root is None or path is None:
        return {"ok": False, "error": "no such green or path"}
    if _SECRET_NAME.search(path.name):
        return {"ok": False, "error": "refused: the name looks like a secret"}
    try:
        if not path.is_file():
            return {"ok": False, "error": "not a file"}
        size = path.stat().st_size
        with path.open("rb") as fh:
            data = fh.read(FILE_CAP + 1)
    except OSError as exc:
        return {"ok": False, "error": f"cannot read: {exc.__class__.__name__}"}
    if b"\x00" in data[:4096]:
        return {"ok": False, "error": "refused: binary file", "bytes": size}
    return {
        "ok": True,
        "path": rel,
        "bytes": size,
        "truncated": len(data) > FILE_CAP,
        "text": redact(data[:FILE_CAP].decode("utf-8", errors="replace")),
    }


__all__ = ["green_diff", "green_file", "green_status", "greens", "label", "processes", "redact", "run_tail", "runs"]
