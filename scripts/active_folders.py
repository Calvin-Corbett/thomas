"""Active folder coordination for multi-agent collaboration.

This script lets agents claim folders with TTL-based leases, heartbeat while
working, and check for overlaps before editing.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "runtime" / "coordination"
STATE_FILE = STATE_DIR / "active_folders.json"
LOCK_FILE = STATE_DIR / "active_folders.lock"

DEFAULT_TTL_SECONDS = 120
DEFAULT_HEARTBEAT_SECONDS = 20
LOCK_TIMEOUT_SECONDS = 10.0
LOCK_STALE_SECONDS = 60.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat(timespec="seconds")


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _normalize_path(path: str) -> str:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (Path.cwd() / raw).resolve()
    try:
        rel = resolved.relative_to(ROOT.resolve())
    except Exception as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Path '{path}' is outside repo root {ROOT}") from exc
    normalized = rel.as_posix().strip("/")
    return normalized or "."


def _paths_overlap(a: str, b: str) -> bool:
    if a == b:
        return True
    if a == "." or b == ".":
        return True
    return a.startswith(f"{b}/") or b.startswith(f"{a}/")


@contextmanager
def _file_lock(lock_file: Path, timeout: float = LOCK_TIMEOUT_SECONDS):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    fd: int | None = None
    while True:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid={os.getpid()} ts={time.time():.3f}".encode("utf-8", errors="ignore"))
            break
        except FileExistsError:
            try:
                age = time.time() - lock_file.stat().st_mtime
            except FileNotFoundError:
                age = 0.0
            if age > LOCK_STALE_SECONDS:
                try:
                    lock_file.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.time() >= deadline:
                raise TimeoutError(f"Timed out waiting for lock: {lock_file}")
            time.sleep(0.1)

    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_file.unlink()
        except FileNotFoundError:
            pass


def _read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"version": 1, "updated_at": _to_iso(_utc_now()), "claims": []}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"version": 1, "updated_at": _to_iso(_utc_now()), "claims": []}

    claims = data.get("claims")
    if not isinstance(claims, list):
        claims = []
    return {
        "version": 1,
        "updated_at": str(data.get("updated_at") or _to_iso(_utc_now())),
        "claims": claims,
    }


def _write_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state["version"] = 1
    state["updated_at"] = _to_iso(_utc_now())
    tmp = STATE_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(STATE_FILE)


def _prune_expired(state: dict[str, Any], now: datetime | None = None) -> tuple[dict[str, Any], int]:
    now = now or _utc_now()
    kept: list[dict[str, Any]] = []
    removed = 0
    for claim in list(state.get("claims") or []):
        try:
            expires = _from_iso(str(claim.get("expires_at")))
        except Exception:
            removed += 1
            continue
        if expires <= now:
            removed += 1
            continue
        kept.append(claim)
    state["claims"] = kept
    return state, removed


def _normalize_paths(paths: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in paths:
        normalized = _normalize_path(raw)
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    if not out:
        raise ValueError("At least one --path is required")
    return out


def _new_claim(agent: str, paths: Sequence[str], ttl_seconds: int, note: str) -> dict[str, Any]:
    now = _utc_now()
    return {
        "claim_id": str(uuid.uuid4()),
        "agent_id": agent,
        "paths": list(paths),
        "note": note,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "started_at": _to_iso(now),
        "last_heartbeat_at": _to_iso(now),
        "expires_at": _to_iso(now + timedelta(seconds=max(1, ttl_seconds))),
    }


def _claim(args: argparse.Namespace) -> int:
    paths = _normalize_paths(args.path)
    with _file_lock(LOCK_FILE):
        state = _read_state()
        state, _ = _prune_expired(state)
        claims = list(state.get("claims") or [])
        if args.replace_agent:
            claims = [c for c in claims if str(c.get("agent_id")) != args.agent]
        claim = _new_claim(args.agent, paths, args.ttl, args.note or "")
        claims.append(claim)
        state["claims"] = claims
        _write_state(state)

    print(json.dumps({"ok": True, "claim_id": claim["claim_id"], "paths": paths}, indent=2))
    return 0


def _heartbeat(args: argparse.Namespace) -> int:
    now = _utc_now()
    with _file_lock(LOCK_FILE):
        state = _read_state()
        state, _ = _prune_expired(state, now=now)
        found = False
        for claim in state.get("claims") or []:
            if str(claim.get("claim_id")) == args.claim_id:
                claim["last_heartbeat_at"] = _to_iso(now)
                claim["expires_at"] = _to_iso(now + timedelta(seconds=max(1, args.ttl)))
                found = True
                break
        if not found:
            print(json.dumps({"ok": False, "error": "claim_not_found", "claim_id": args.claim_id}, indent=2))
            return 1
        _write_state(state)

    print(json.dumps({"ok": True, "claim_id": args.claim_id}, indent=2))
    return 0


def _release(args: argparse.Namespace) -> int:
    with _file_lock(LOCK_FILE):
        state = _read_state()
        before = len(state.get("claims") or [])
        if args.claim_id:
            claims = [c for c in (state.get("claims") or []) if str(c.get("claim_id")) != args.claim_id]
        elif args.agent:
            claims = [c for c in (state.get("claims") or []) if str(c.get("agent_id")) != args.agent]
        else:
            raise ValueError("release requires --claim-id or --agent")
        state["claims"] = claims
        _write_state(state)
    removed = before - len(claims)
    print(json.dumps({"ok": True, "removed": removed}, indent=2))
    return 0


def _list(args: argparse.Namespace) -> int:
    with _file_lock(LOCK_FILE):
        state = _read_state()
        state, removed = _prune_expired(state)
        if removed:
            _write_state(state)

    claims = sorted(
        state.get("claims") or [],
        key=lambda c: (str(c.get("agent_id") or ""), str(c.get("started_at") or "")),
    )

    if args.json:
        print(json.dumps({"ok": True, "claims": claims}, indent=2))
        return 0

    if not claims:
        print("No active folder claims.")
        return 0

    print("Active folder claims:")
    for claim in claims:
        print(
            f"- {claim.get('agent_id')} ({claim.get('claim_id')}): "
            f"paths={claim.get('paths')} expires_at={claim.get('expires_at')}"
        )
        if claim.get("note"):
            print(f"  note: {claim.get('note')}")
    return 0


def _find_conflicts(paths: Sequence[str], ignore_agent: str | None = None) -> list[dict[str, Any]]:
    with _file_lock(LOCK_FILE):
        state = _read_state()
        state, removed = _prune_expired(state)
        if removed:
            _write_state(state)

    conflicts: list[dict[str, Any]] = []
    for claim in state.get("claims") or []:
        agent = str(claim.get("agent_id") or "")
        if ignore_agent and agent == ignore_agent:
            continue
        claim_paths = [str(p) for p in (claim.get("paths") or [])]
        overlap_paths: list[dict[str, str]] = []
        for wanted in paths:
            for active in claim_paths:
                if _paths_overlap(wanted, active):
                    overlap_paths.append({"wanted": wanted, "active": active})
        if overlap_paths:
            conflicts.append(
                {
                    "agent_id": agent,
                    "claim_id": str(claim.get("claim_id") or ""),
                    "expires_at": str(claim.get("expires_at") or ""),
                    "overlaps": overlap_paths,
                    "note": str(claim.get("note") or ""),
                }
            )
    return conflicts


def _check(args: argparse.Namespace) -> int:
    paths = _normalize_paths(args.path)
    conflicts = _find_conflicts(paths, ignore_agent=args.agent)
    if args.json:
        print(json.dumps({"ok": not bool(conflicts), "conflicts": conflicts}, indent=2))
    else:
        if conflicts:
            print("Folder conflicts detected:")
            for row in conflicts:
                print(f"- {row['agent_id']} ({row['claim_id']}) expires_at={row['expires_at']}")
                for item in row["overlaps"]:
                    print(f"  overlap: wanted={item['wanted']} active={item['active']}")
                if row.get("note"):
                    print(f"  note: {row['note']}")
        else:
            print("No folder conflicts detected.")
    return 2 if conflicts else 0


def _daemon(args: argparse.Namespace) -> int:
    paths = _normalize_paths(args.path)
    with _file_lock(LOCK_FILE):
        state = _read_state()
        state, _ = _prune_expired(state)
        claims = list(state.get("claims") or [])
        if args.replace_agent:
            claims = [c for c in claims if str(c.get("agent_id")) != args.agent]
        claim = _new_claim(args.agent, paths, args.ttl, args.note or "")
        claims.append(claim)
        state["claims"] = claims
        _write_state(state)

    claim_id = claim["claim_id"]
    print(json.dumps({"ok": True, "claim_id": claim_id, "mode": "daemon"}, indent=2))

    stop_event = threading.Event()

    def _signal_handler(_sig: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        while not stop_event.wait(max(1, args.interval)):
            hb_args = argparse.Namespace(claim_id=claim_id, ttl=args.ttl)
            rc = _heartbeat(hb_args)
            if rc != 0:
                break
    finally:
        _release(argparse.Namespace(claim_id=claim_id, agent=None))
    return 0


def _run(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("run requires a command after --", file=sys.stderr)
        return 2

    paths = _normalize_paths(args.path)
    with _file_lock(LOCK_FILE):
        state = _read_state()
        state, _ = _prune_expired(state)
        claims = list(state.get("claims") or [])
        if args.replace_agent:
            claims = [c for c in claims if str(c.get("agent_id")) != args.agent]
        claim = _new_claim(args.agent, paths, args.ttl, args.note or "")
        claims.append(claim)
        state["claims"] = claims
        _write_state(state)

    claim_id = claim["claim_id"]
    print(json.dumps({"ok": True, "claim_id": claim_id, "mode": "run", "command": command}, indent=2))

    stop_event = threading.Event()

    def _heartbeat_loop() -> None:
        while not stop_event.wait(max(1, args.interval)):
            _heartbeat(argparse.Namespace(claim_id=claim_id, ttl=args.ttl))

    thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    thread.start()

    try:
        proc = subprocess.run(command, cwd=str(ROOT), check=False)
        return int(proc.returncode)
    finally:
        stop_event.set()
        _release(argparse.Namespace(claim_id=claim_id, agent=None))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Folder lease coordination for multi-agent editing.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    claim = sub.add_parser("claim", help="Create a folder claim.")
    claim.add_argument("--agent", required=True, help="Stable agent id (e.g. codex-main).")
    claim.add_argument("--path", action="append", required=True, help="Folder path to claim (repeatable).")
    claim.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS, help="Lease TTL in seconds.")
    claim.add_argument("--note", default="", help="Optional work note.")
    claim.add_argument("--replace-agent", action="store_true", default=True, help="Replace prior claims for this agent.")
    claim.set_defaults(func=_claim)

    heartbeat = sub.add_parser("heartbeat", help="Refresh an existing claim.")
    heartbeat.add_argument("--claim-id", required=True)
    heartbeat.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS)
    heartbeat.set_defaults(func=_heartbeat)

    release = sub.add_parser("release", help="Release claim(s).")
    release.add_argument("--claim-id", default="")
    release.add_argument("--agent", default="")
    release.set_defaults(func=_release)

    listing = sub.add_parser("list", help="List active claims.")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=_list)

    check = sub.add_parser("check", help="Check path overlap against active claims.")
    check.add_argument("--path", action="append", required=True, help="Path(s) you want to edit.")
    check.add_argument("--agent", default="", help="Ignore conflicts from this agent id.")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=_check)

    daemon = sub.add_parser("daemon", help="Run persistent heartbeat in foreground until stopped.")
    daemon.add_argument("--agent", required=True)
    daemon.add_argument("--path", action="append", required=True)
    daemon.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS)
    daemon.add_argument("--interval", type=int, default=DEFAULT_HEARTBEAT_SECONDS)
    daemon.add_argument("--note", default="")
    daemon.add_argument("--replace-agent", action="store_true", default=True)
    daemon.set_defaults(func=_daemon)

    run = sub.add_parser("run", help="Claim folders, run a command, heartbeat, then release.")
    run.add_argument("--agent", required=True)
    run.add_argument("--path", action="append", required=True)
    run.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS)
    run.add_argument("--interval", type=int, default=DEFAULT_HEARTBEAT_SECONDS)
    run.add_argument("--note", default="")
    run.add_argument("--replace-agent", action="store_true", default=True)
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(func=_run)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # argparse stores empty strings for optional fields where we want None-like behavior.
    if hasattr(args, "agent") and args.agent == "":
        args.agent = None
    if hasattr(args, "claim_id") and args.claim_id == "":
        args.claim_id = None

    try:
        return int(args.func(args))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except TimeoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())