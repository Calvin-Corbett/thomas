#!/usr/bin/env python3
"""Land your work through the queue: ``python scripts/crew/brief/land.py --message "..." [--include PATH ...]``.

Takes the same arguments as ``commit.py`` and runs that tool unchanged, once, when it is your turn. A wait takes minutes
when others are landing. A worker process waits for you, so if your tool call times out, run the same command again (it
attaches to your open ticket) or ask in slices:

  land.py --submit --message "..."     take a ticket and return once it exists (exit 0)
  land.py --wait N [--wait-seconds S]  ask about ticket N for up to S seconds; safe to repeat (alias --resume N)
  land.py --status [--verify] [--json] show the queue, change nothing

Exit codes: 0 landed or already landed, 1 refused (reason printed, whole output in a file), 2 usage, identity or attempt
cap, 3 waited too long, 4 your ticket was taken back and nothing landed, 5 still waiting. 3, 4 and 5 mean run it again.
Pre-check: while your ticket waits with at most 2 ahead, the waiting process runs one dry run of the commit tool if one of
2 queue-wide slots is free (``--no-precheck`` skips it); alone, you pay for one run.
This is a queue in front of the commit tool, not protection: commit.py still works and is not blocked, and every file in the
queue folder can be written by any agent. See docs/ops/LANDING_QUEUE_DESIGN.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.crew.brief import land_env, land_git, land_precheck, land_worker, landing_status  # noqa: E402
from scripts.crew.brief.land_commit import commit_cmd, parse_outcome, run_commit  # noqa: E402,F401
from scripts.crew.brief.land_env import make_lane, presence_beat, repo_root  # noqa: E402,F401
from scripts.crew.brief.land_git import TRAILER, intent_key, with_key  # noqa: E402,F401
from scripts.crew.brief.landing_queue import AttemptCapReached, Config, Lane  # noqa: E402,F401
from scripts.crew.brief.landing_store import resolve_queue_root  # noqa: E402,F401


def split_includes(raw: Sequence[str]) -> list[str]:
    """``--include a,b`` and ``--include a --include b`` are the same list, exactly as scoped_commit_cli.py splits them (that
    expression is inline there, so it is repeated here and a test pins the two together)."""
    return [token.strip() for item in raw for token in str(item or "").split(",") if token.strip()]


def find_landed(key: str, includes: Sequence[str] = ()) -> str | None:
    return land_git.find_landed(repo_root(), key, includes, Config.window_commits)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Land your work through the FIFO landing queue (wraps commit.py unchanged)."
    )
    p.add_argument("--message")
    p.add_argument("--agent", default="")
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--allow-scope-fallback", action="store_true")
    p.add_argument("--fallback-reason", default="")
    p.add_argument("--no-precheck", action="store_true", help="skip the dry run that runs near the head of the line")
    p.add_argument(
        "--new-intent", action="store_true", help="a second, different change with the same message and paths"
    )
    p.add_argument("--submit", action="store_true", help="take a ticket and return once it exists")
    p.add_argument("--wait", "--resume", dest="wait", type=int, default=0, metavar="TICKET", help="ask about a ticket")
    p.add_argument("--wait-seconds", type=float, default=None, help="how long this call may wait (--wait: 90)")
    p.add_argument("--worker", type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument("--no-detach", action="store_true", help="wait and land inside this process (dies with it)")
    p.add_argument("--wait-timeout", type=float, default=Config.max_wait, help="how long a ticket may wait in line")
    p.add_argument(
        "--max-hold", type=float, default=Config.max_hold, help="lease for your landing (can only shorten it)"
    )
    p.add_argument("--status", action="store_true")
    p.add_argument("--verify", action="store_true", help="with --status: also report tampering and odd leases")
    p.add_argument("--json", action="store_true")
    return p


def emit(args: argparse.Namespace, code: int, status: str, text: str, **extra: Any) -> int:
    print(
        json.dumps({"ok": code == 0, "status": status, "message": text, **extra}, sort_keys=True) if args.json else text
    )
    return code


def say_to_stderr(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def show_status(args: argparse.Namespace, lane: Lane, root: Path) -> int:
    oldest = max((q["age_s"] for q in landing_status.build_status(lane)["queue"]), default=None)
    outside = land_git.commits_outside_queue(root, lane.clock() - oldest) if oldest is not None else None
    status = landing_status.build_status(lane, agent=lane.agent, verify=args.verify, untagged_since_oldest=outside)
    print(json.dumps(status, sort_keys=True, default=str) if args.json else landing_status.render(status))
    return 0


def start_ticket(args: argparse.Namespace, lane: Lane, key: str) -> tuple[int | None, int, str, dict[str, Any]]:
    """Take or attach to a ticket. Returns (ticket, exit code, text, extra). No dry run here: the waiting process runs
    the pre-check near the head of the line, so this returns as soon as the ticket exists.

    Reaped FIRST, so an open ticket of yours whose worker died is finished (and you are told) before the attach check;
    and "attached" only when the ticket is the very one found open, so a worker that dies between the two reads still
    gets a new worker for the new ticket instead of a ticket nobody waits for."""
    states = lane.states()
    gone = [n for n in lane.reap(states) if states[n]["ticket"].get("key") == key]
    attach = lane.find_open(key)
    try:
        num = lane.enqueue(
            key,
            args.message.splitlines()[0],
            includes=args.include,
            request=land_worker.request_for(args, args.message),
            mode="foreground" if args.no_detach else "detached",
        )
    except AttemptCapReached as exc:
        return None, 2, str(exc), {}
    attached = attach is not None and num == attach
    for old in gone:
        why = lane.states().get(old, {}).get("reason") or "taken back"
        say_to_stderr(
            f"your earlier ticket T{old:06d} for this change was taken back ({why}); queued again as T{num:06d}"
        )
    return num, 0, "attached" if attached else "queued", {}


def land_in_process(args: argparse.Namespace, lane: Lane, root: Path, num: int, cfg: Config, key: str) -> int:
    parent = os.getppid()
    lane.stop_if = lambda: (
        None if lane.pid_alive(parent) else "parent_gone"
    )  # an orphaned wait must not outlive its caller
    if not args.no_precheck:
        dry = commit_cmd(land_env.commit_path(), args, args.message, dry=True)
        lane.on_wait = land_precheck.Precheck(lane, num, dry, root)
    try:
        turn = lane.wait_turn(num)
    except KeyboardInterrupt:
        lane.withdraw(num)
        raise
    if turn != "granted":
        code, status, text, extra = land_worker.report(lane, num)  # the whole answer: stage, blocker, output file
        return emit(args, code, status, text, **extra)
    cmd = commit_cmd(land_env.commit_path(), args, with_key(args.message, key), dry=False)
    lane.hold(num, lambda: run_commit(cmd, lane, num, cfg, key, root=root, includes=args.include))
    code, status, text, extra = land_worker.report(lane, num)
    return emit(args, code, status, text, **extra)


def run(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    args.include = split_includes(args.include)
    if args.worker:
        return land_worker.worker_main(args.worker)
    root = repo_root()
    cfg = Config(max_wait=args.wait_timeout, max_hold=min(Config.max_hold, args.max_hold))
    try:
        agent, session = land_env.resolve_identity(args.agent, root)
    except ValueError as exc:
        if not args.status:
            return emit(args, 2, "identity", f"land.py needs the same session-bound identity commit.py does: {exc}")
        agent, session = args.agent, ""
    lane = make_lane(root, agent, session, cfg, say_to_stderr, staged_args=args)
    if args.status:
        return show_status(args, lane, root)
    if args.wait:
        s = lane.states().get(args.wait)
        if s is not None and (s["ticket"].get("session") or s["ticket"].get("agent")) != lane.ident:
            return emit(args, 2, "not_yours", f"T{args.wait:06d} belongs to {s['ticket'].get('agent')}, not to you")
        seconds = 90.0 if args.wait_seconds is None else args.wait_seconds
        code, status, text, extra = land_worker.wait_for(lane, args.wait, seconds, say_to_stderr)
        return emit(args, code, status, text, **extra)
    if not args.message or not agent:
        return emit(args, 2, "usage", "land.py needs --message and an agent id (--agent or a bound session)")
    for note in landing_status.build_status(lane, agent=agent)["notices"]:
        print(f"NOTICE for you (T{note['ticket']:06d}): {note['notice']}", file=sys.stderr)
    key = intent_key(agent, args.message, args.include, salt=str(lane.clock()) if args.new_intent else "")
    if (prior := lane.find_landed(key, args.include, True)) is not None:
        return emit(args, 0, "already_landed", f"already landed as {prior}", sha=prior)
    num, code, text, extra = start_ticket(args, lane, key)
    if num is None:
        return emit(args, code, "attempt_cap", text, **extra)
    if args.no_detach:
        return land_in_process(args, lane, root, num, cfg, key)
    if text == "queued" or args.submit:
        log = land_worker.worker_log(lane.store.root, num)
        proc = land_worker.spawn_worker(num, Path(__file__).resolve(), log) if text == "queued" else None
        if text == "queued" and (proc is None or not land_worker.await_adoption(lane, num)):
            lane.withdraw(num, "worker_did_not_start")
            return emit(
                args, 4, "worker_failed", "the background worker did not start; run again with --no-detach", ticket=num
            )
        if text == "queued" and lane.states().get(num, {}).get("owner_breakaway") is False:
            say_to_stderr(
                "WARNING: the worker could not leave your tool's job object. If that tool kills its processes at a "
                "timeout the worker dies with them and your ticket is dropped: run land.py again."
            )
    if args.submit:
        code, status, text, extra = land_worker.report(lane, num)
        text = f"submitted T{num:06d}: {text}" if status == "waiting" else text
        return emit(
            args,
            0 if status in ("waiting", "landed", "already_landed") else code,
            "submitted" if status == "waiting" else status,
            text,
            **extra,
        )
    code, status, text, extra = land_worker.wait_for(
        lane, num, cfg.max_wait + 300 if args.wait_seconds is None else args.wait_seconds, say_to_stderr
    )
    return emit(args, code, status, text, **extra)


if __name__ == "__main__":
    raise SystemExit(run())
