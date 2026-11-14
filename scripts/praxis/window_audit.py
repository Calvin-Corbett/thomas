"""Part 4's pass line, read from the window's record, from dev and from the outbox (spec 2026-10-12, section 8).

"One sign-in per sitting instead of one per card; no change lands in a window without the landing conditions in 8.2;
no change is lost or landed twice." For the windows opened since --since:

- sign-ins: windows opened (each was one Windows sign-in), and window landings per sign-in;
- unproven: window landings whose record lacks a write-ahead intent for the same commit, the change digest it was
  derived as, a checker job that PASSED the tree that landed, or a SAFE second look of that same change digest;
- not checked after landing: window landings with no check after landing recorded for their commit;
- landed twice: hand-ins dev holds more than one promoter commit for;
- lost: window landings dev does not hold, or with no verdict in the outbox;
- torn events and landings the promoter stopped inside that were never settled.

    python scripts/praxis/window_audit.py --since 2026-10-15T00:00 --json-out <file>

Prints the result and writes it (aggregates and hand-in ids only) when asked.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.cage import self_change_checks as checks  # noqa: E402
from scripts.cage.window_record import RECORD_ROOT, Record, landed_on  # noqa: E402
from thomas.tools import cage_shell  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _promoter_landings(repo: Path, branch: str, since: float) -> Counter[str]:
    """How many promoter commits *branch* holds for each hand-in, committed at or after *since*. The time is read from
    each commit, not asked of ``git log --since``, which returned nothing on some runs on 2026-10-14."""
    keys = "%ct%x00%(trailers:key=Thomas-Submission-Id,valueonly)%x00%(trailers:key=Thomas-Committed-By,valueonly)"
    shown = checks.run_git(repo, "log", f"refs/heads/{branch}", f"--format={keys}%x01")
    counts: Counter[str] = Counter()
    for row in shown.stdout.split("\x01"):
        when, sid, committer = ([part.strip() for part in row.split("\0")] + ["", "", ""])[:3]
        if not when.isdigit() or int(when) < since or committer != "self-change-promoter":
            continue
        if sid and not sid.startswith("undo-"):
            counts[sid] += 1
    return counts


def _proven(event: dict[str, object], intents: set[str]) -> bool:
    """A landing with its write-ahead intent, and a PASSED check and a SAFE second look of exactly what landed."""
    change, tree = event.get("change"), event.get("tree")
    return (
        event.get("commit") in intents
        and bool(change)
        and bool(tree)
        and bool(event.get("check_job"))
        and event.get("check_verdict") == "PASSED"
        and event.get("check_tree") == tree
        and event.get("second_look") == "SAFE"
        and event.get("second_look_change") == change
    )


def audit(record_root: Path, repo: Path, outbox: Path, *, branch: str = "dev", since: float = 0.0) -> dict[str, object]:
    record = Record(record_root)
    events = [event for event in record.events() if event.get("torn") or float(event.get("at") or 0) >= since]
    opened = [event for event in events if event.get("name") == "window_opened"]
    # A landing recover() found on dev is a landing too, and has no checks of its own on record (review D1).
    landed = list(
        {
            str(event.get("commit")): event
            for event in events
            if event.get("name") == "landed" or (event.get("name") == "recovered" and event.get("on_dev"))
        }.values()
    )
    intents = {str(event.get("commit")) for event in events if event.get("name") == "landing_intent"}
    unproven = [str(event.get("sid")) for event in landed if not _proven(event, intents)]
    unchecked = [
        str(event.get("sid"))
        for event in landed
        if not any(
            after.get("name") == "after_check" and after.get("commit") == event.get("commit")
            for after in events
            if int(after.get("seq") or 0) > int(event.get("seq") or 0)
        )
    ]
    lost = [
        str(event.get("sid"))
        for event in landed
        if not landed_on(repo, branch, str(event.get("commit")))
        or not (Path(outbox) / f"{event.get('sid')}.verdict.json").is_file()
    ]
    twice = sorted(sid for sid, count in _promoter_landings(repo, branch, since).items() if count > 1)
    torn = sum(1 for event in events if event.get("torn"))
    unsettled = len(record.unfinished())
    per = round(len(landed) / len(opened), 2) if opened else 0.0
    failed = unproven or unchecked or lost or twice or torn or unsettled
    met = bool(opened) and not failed and (len(landed) < 2 or per > 1.0)
    return {
        "windows": len(opened),
        "window_landings": len(landed),
        "landings_per_sign_in": per,
        "unproven": unproven,
        "not_checked_after_landing": unchecked,
        "lost": lost,
        "landed_twice": twice,
        "torn_events": torn,
        "unsettled_landings": unsettled,
        "pass_line_met": met,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Part 4's pass line, from the window's record and dev.")
    parser.add_argument("--since", default="", help="local time, e.g. 2026-10-15T00:00; default: everything")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--record", default=str(RECORD_ROOT))
    args = parser.parse_args(argv)
    since = datetime.fromisoformat(args.since).timestamp() if args.since else 0.0
    result = audit(Path(args.record), REPO_ROOT, cage_shell.cage_root() / "outbox", since=since)
    text = json.dumps(result, indent=1, sort_keys=True)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    return 0 if result["pass_line_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
