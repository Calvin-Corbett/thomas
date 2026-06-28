#!/usr/bin/env python3
"""Presence heartbeat monitor -- the liveness daemon that keeps a claim alive.

The problem this fixes: a worker registers a presence session and claims scope,
then its app is closed or the machine is powered off -- but nothing tells the
workboard the agent is gone, so the claim looks live and blocks the next worker
(e.g. codex claimed paths, turned the PC off two days ago, claim still "held").

The fix: when an agent registers, it spawns THIS monitor. The monitor refreshes
the session heartbeat every ``--interval`` seconds for exactly as long as the
agent's process (``--parent-pid``) is alive. The moment that process exits, the
heartbeats stop; after the presence stale window (THOMAS_AGENT_PRESENCE_STALE_SECONDS,
default 120s) the session is judged ``stale`` -> the agent is treated OFFLINE and
its claims no longer block or hold. The claim's life is now leased to the agent's
actual liveness, and a dead agent's claim auto-expires. It does not come back: a
new run must re-register.

Run standalone (normally auto-spawned by `presence register --monitor`):
    python scripts/crew/brief/presence_monitor.py --session-id <id> --parent-pid <pid>
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root for `thomas` import


def _parent_alive(pid: int) -> bool:
    """True if process ``pid`` is still running. pid<=0 means 'no parent to watch'."""
    if pid <= 0:
        return True
    try:
        import psutil  # type: ignore

        return bool(psutil.pid_exists(pid))
    except Exception:  # noqa: BLE001 - psutil optional; fall back to OS probes
        pass
    try:
        if os.name == "nt":
            import subprocess

            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            return str(int(pid)) in (out or "")
        os.kill(int(pid), 0)
        return True
    except Exception:  # noqa: BLE001 - any probe failure -> treat as gone (fail safe to offline)
        return False


def run_monitor(
    session_id: str,
    *,
    repo_root: str | None = None,
    parent_pid: int = 0,
    interval: int = 60,
    max_seconds: int = 0,
    sleeper=time.sleep,
) -> str:
    """Heartbeat the session until the parent dies / session vanishes / cap hit.

    Returns the reason it stopped: 'parent_gone' | 'session_gone' | 'max_seconds'.
    Injectable ``sleeper`` keeps it unit-testable.
    """
    from thomas.core import agent_presence

    repo = repo_root or None
    started = time.time()
    interval = max(5, int(interval))
    while True:
        if parent_pid and not _parent_alive(parent_pid):
            return "parent_gone"
        if agent_presence.heartbeat_session(repo_root=repo, session_id=session_id) is None:
            return "session_gone"
        if max_seconds and (time.time() - started) >= max_seconds:
            return "max_seconds"
        sleeper(interval)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Presence heartbeat liveness monitor.")
    ap.add_argument("--repo", default="")
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--parent-pid", type=int, default=0, help="Stop heartbeating when this PID exits.")
    ap.add_argument("--interval", type=int, default=60, help="Seconds between heartbeats (default 60).")
    ap.add_argument("--max-seconds", type=int, default=0, help="Safety cap; 0 = run until parent exits.")
    args = ap.parse_args(argv)
    reason = run_monitor(
        args.session_id,
        repo_root=args.repo or None,
        parent_pid=int(args.parent_pid),
        interval=int(args.interval),
        max_seconds=int(args.max_seconds),
    )
    print(f"presence monitor stopped: {reason} (session={args.session_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
