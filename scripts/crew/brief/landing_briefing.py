"""The briefing section that tells agents how to land with other agents. Kept here so briefing.py stays small."""

from __future__ import annotations

FIRST = (
    "Run `python scripts/crew/brief/land.py --status` first; if others are queued, land through the queue so your gates do "
    "not run against a branch that keeps moving: `python scripts/crew/brief/land.py --message ...` takes commit.py's "
    "--message, --agent, --include, --allow-scope-fallback and --fallback-reason (it has no --dry-run). Waits take minutes "
    "(3 to 6 at twenty agents) and a ticket waits at most 45 minutes. If your tool call can time out, do not wait in it: "
    "`land.py --submit --message ...` returns once your ticket exists (exit 0: read its status, it is not landed yet), "
    "then run `land.py --wait N` in a loop (up to 90 seconds a call, safe to repeat). Only "
    "after --submit does a worker keep your place; a plain `land.py --message` call that is killed together with its "
    "processes loses its ticket, and so does a --submit whose tool kills its whole job (--wait then says exit 4: run it "
    "again). A submitted ticket that nobody asks about for 10 minutes leaves the line: call `--wait N` at least every 8 "
    "minutes."
)
SECOND = (
    "Exit codes: 0 landed or already landed. 1 the commit tool refused: read the reason (at least 2000 characters of the "
    "gate's output, and the path of a file with all of it), it may be a gate on your change, "
    "a lease overrun or a lane problem, not necessarily your code. 2 usage, identity or attempt cap, or an unknown or "
    "not-yours ticket. 3 the ticket waited past its limit. 4 your ticket was taken back (owner gone, lease over, 10 "
    "minutes without a --wait) or the worker did not start (run with --no-detach); the answer names the worker's log. 5 "
    "still waiting. Exit codes 3, 4 and 5 mean run it again. With at most 2 tickets ahead, the process that waits for you "
    "runs one pre-check dry run when a queue-wide slot is free, so a refusal can come before your turn; `--no-precheck` "
    "skips it, and the real run still runs every gate. The queue is advisory and tamper-evident, not tamper-proof: commit.py still works "
    "and is not blocked, but do not bypass the queue because a wait is long (calling it directly while others are "
    "queued slows everyone), and hitting the attempt cap (exit 2) is not a reason to use commit.py either: fix the "
    "refusal, or ask."
)


def section() -> list[str]:
    return ["## Landing With Other Agents", "", FIRST, "", SECOND, ""]
