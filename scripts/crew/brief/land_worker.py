"""The detached half of land.py: submit a ticket, let a worker wait and land, ask about it later in bounded slices.

A foreground land.py that is killed by its caller's tool-call timeout used to take its ticket with it. Now the process that
waits and lands is a separate worker, so the caller can stop asking and ask again: ``--submit`` returns once its ticket
exists, ``--wait N`` (alias ``--resume N``) polls for at most ``--wait-seconds`` and exits 5 ("still waiting, run it
again") and may be repeated for ever. Every ask refreshes the ticket's ``touch`` file; a worker whose ticket nobody asks
about for ``resume_grace`` seconds leaves the line, and a worker never outlives its ticket, so it cannot keep a dead agent
looking alive. The worker runs the pre-check (``land_precheck``) while it waits near the head of the line, and writes what
it does, and any crash, to ``logs/T<ticket>.log`` under the queue root. Exit codes: 0 landed, 1 refused, 3 waited too
long, 4 ticket taken back, 5 still waiting.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from scripts.crew.brief import land_commit, land_env, land_git, land_precheck, landing_proc, push_after_land
from scripts.crew.brief.landing_queue import Lane
from scripts.crew.brief.landing_types import Config

ADOPT_PATIENCE = 15.0
DETACHED = landing_proc.NO_WINDOW | 0x00000200  # no console at all, own process group
BREAKAWAY = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB


def request_for(args: Any, message: str) -> dict[str, Any]:
    return {
        "message": message,
        "agent_arg": args.agent,
        "include": list(args.include),
        "allow_scope_fallback": bool(args.allow_scope_fallback),
        "fallback_reason": args.fallback_reason,
        "max_hold": args.max_hold,
        "wait_timeout": args.wait_timeout,
        "precheck": not getattr(args, "no_precheck", False),
    }


def worker_log(queue_root: Path, num: int) -> Path:
    return Path(queue_root) / "logs" / f"T{num:06d}.log"


def spawn_worker(num: int, script: Path, log: Path | None = None) -> subprocess.Popen[Any] | None:
    """Start the detached worker for ticket ``num``, its output appended to ``log``. None when the OS refuses."""
    cmd = [sys.executable, str(script), "--worker", str(num)]
    sink = None
    if log is not None:
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            sink = open(log, "a", encoding="utf-8")  # noqa: SIM115 - handed to the child, closed below
        except OSError:
            sink = None  # no log is no reason not to land
    kw: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": sink or subprocess.DEVNULL,
        "stderr": subprocess.STDOUT if sink else subprocess.DEVNULL,
        "close_fds": True,
    }
    flags = [DETACHED | BREAKAWAY, DETACHED] if os.name == "nt" else [0]
    try:
        for flag in flags:  # a caller's job object may forbid breakaway: then the worker simply stays in that job
            try:
                env = {**os.environ, "THOMAS_LAND_BREAKAWAY": "1" if flag & BREAKAWAY else "0"}
                if os.name == "nt":
                    return landing_proc.popen(cmd, creationflags=flag, env=env, **kw)
                return landing_proc.popen(cmd, start_new_session=True, env=env, **kw)
            except OSError:
                continue
        return None
    finally:
        if sink is not None:
            sink.close()  # the child holds its own handle


def report(lane: Lane, num: int) -> tuple[int, str, str, dict[str, Any]]:
    """(exit code, status, text, extra) for a ticket, from the ledger alone."""
    s = lane.states()[num]
    extra: dict[str, Any] = {"ticket": num}
    if s["sha"] and not s["open"]:
        recovered = s["state"] == "recovered" or any(e.get("note") == "already landed" for e in s["events"])
        text = f"already landed as {s['sha']}" if recovered else f"landed as {s['sha']} (ticket T{num:06d})"
        return 0, "already_landed" if recovered else "landed", text, {**extra, "sha": s["sha"]}
    if s["state"] == "refused":
        e = next(x for x in reversed(s["events"]) if x["kind"] == "refused")
        extra["blocker_class"] = e.get("blocker")
        early = e.get("stage") == "precheck"
        where = "by the pre-check before your turn, no slot used" if early else "by the commit tool, slot released"
        text = f"refused {where}: {e.get('message') or e.get('blocker')}"
        if e.get("output_file"):
            extra["output_file"] = e["output_file"]
            text += f"\nthe commit tool's whole output: {e['output_file']}"
        return 1, "refused", text, {**extra, "stage": "precheck"} if early else extra
    if not s["open"]:
        timeout = s.get("reason") == "wait_timeout"
        text = f"not landed: {s.get('notice') or s['state']}"
        log = worker_log(lane.store.root, num)
        if not timeout and log.is_file():
            extra["worker_log"] = str(log)
            text += f" (worker log: {log})"
        return (3 if timeout else 4), ("timeout" if timeout else s["state"]), text, extra
    return 5, "waiting", describe(lane, num, s), extra


def describe(lane: Lane, num: int, s: dict[str, Any]) -> str:
    states = lane.states()
    ahead = [n for n, x in states.items() if x["open"] and n < num]
    if s["state"] in ("holding", "landed"):
        return f"T{num:06d} has the landing slot and is landing now"
    return (
        f"still waiting: T{num:06d} has {len(ahead)} ahead, est. wait {int(lane.eta(len(ahead)))}s "
        f"(holder: {lane._holder_text(states)}); run `land.py --wait {num}` again"
    )


def wait_for(lane: Lane, num: int, seconds: float, say: Any) -> tuple[int, str, str, dict[str, Any]]:
    """Ask about a ticket for at most ``seconds``; touch it so the worker knows someone still wants it."""
    deadline, last_say = time.monotonic() + seconds, float("-inf")
    while True:
        lane.touch(num)
        lane.reap()
        s = lane.states().get(num)
        if s is None:
            return (
                2,
                "unknown_ticket",
                f"no ticket T{num:06d} (it finished long ago and was pruned, or never existed)",
                {"ticket": num},
            )
        if not s["open"]:
            return report(lane, num)
        if time.monotonic() >= deadline:
            return report(lane, num)
        if time.monotonic() - last_say >= lane.cfg.say_every:
            last_say = time.monotonic()
            say(describe(lane, num, s))
        lane.sleep(lane.cfg.poll)


def await_adoption(lane: Lane, num: int) -> bool:
    deadline = time.monotonic() + ADOPT_PATIENCE
    while time.monotonic() < deadline:
        if lane.states().get(num, {}).get("owner_pid"):
            return True
        time.sleep(0.2)
    return False


def to_log(num: int) -> Any:
    def say(text: str) -> None:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} T{num:06d} {text}", file=sys.stderr, flush=True)

    return say


def push_after(root: Path, lane: Lane, num: int, agent: str, say: Any, verdict: str) -> None:
    """Push dev to GitHub once a landing is over. Called after the lease is released, so it cannot change the landing.

    Nothing is pushed while another ticket is still open: the push after the last landing carries the earlier ones. When that
    last ticket ends without landing, it sends the push the earlier one put off. A failure
    is said in the worker's log and never raised, so a landing that finished stays finished."""
    if verdict not in ("landed", "already_landed") and not push_after_land.a_push_was_put_off():
        return  # nothing landed here, and no earlier landing left its push to this one
    try:
        waiting = any(s["open"] for n, s in lane.states().items() if n != num)
        push_after_land.push_after_landing(root, agent=agent, others_waiting=waiting, say=say)
    except push_after_land.PUSH_FAILED as exc:
        say(f"the push to GitHub did not run: {type(exc).__name__}: {exc}")


def worker_main(num: int) -> int:
    """Run as ``land.py --worker N``: adopt the ticket, wait for the slot, run the one landing, finish the ticket."""
    say = to_log(num)
    root = land_env.repo_root()
    probe = land_env.make_lane(root, "", "", Config(), say)
    seen = probe.states().get(num)
    ticket = seen["ticket"] if seen else None
    if not ticket or ticket.get("torn"):
        say("no such ticket: nothing to do")
        return 2
    owner = seen.get("owner_pid")
    if seen["state"] in ("holding", "landed") or (
        owner and owner != os.getpid() and probe.same_process(owner, seen.get("owner_start"))
    ):
        say("another worker already owns this ticket: leaving it alone")
        return 3  # a worker already owns this ticket: never a second commit tool for one ticket
    request = ticket.get("request") or {}
    args = type("A", (), {k: request.get(k) for k in ("include", "allow_scope_fallback", "fallback_reason")})()
    args.agent = request.get("agent_arg") or ""
    cfg = Config(
        max_hold=min(Config.max_hold, float(request.get("max_hold") or Config.max_hold)),
        max_wait=float(request.get("wait_timeout") or Config.max_wait),
    )
    lane = land_env.make_lane(root, ticket["agent"], ticket.get("session", ""), cfg, say, staged_args=args)
    lane.adopt(num, breakaway=os.environ.get("THOMAS_LAND_BREAKAWAY") == "1")
    say(f"adopted by worker pid {os.getpid()}")
    key, includes = ticket["key"], ticket.get("includes") or []
    message = land_git.with_key(request["message"], key)
    if request.get("precheck", True):
        dry = land_commit.commit_cmd(land_env.commit_path(), args, message, dry=True)
        lane.on_wait = land_precheck.Precheck(lane, num, dry, root)
    turn = lane.wait_turn(num)
    if turn != "granted":
        say(f"left the line: {turn} ({report(lane, num)[2][:300]})")
        push_after(root, lane, num, ticket["agent"], say, turn)
        return 0
    say("granted: running the commit tool")
    cmd = land_commit.commit_cmd(land_env.commit_path(), args, message, dry=False)
    verdict, out = lane.hold(
        num, lambda: land_commit.run_commit(cmd, lane, num, cfg, key, root=root, includes=includes)
    )
    say(f"{verdict}: {(out.sha or out.blocker or '')} {out.message[:300]}")
    push_after(root, lane, num, ticket["agent"], say, verdict)
    return 0
