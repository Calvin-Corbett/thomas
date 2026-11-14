"""``python -m scripts.pipeline_canary once | status | replay <good> <new>``.

``once`` is what the scheduled task ThomasPipelineCanary runs every 5 minutes and at your sign-in. It never runs twice
at once: a pass takes ``run.lock`` in the canary's data folder, and a lock older than STALE_LOCK_S is taken over.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):  # run as a file by pythonw: make the checkout importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.pipeline_canary import canary, measure
from scripts.pipeline_canary.act import RealActions
from scripts.pipeline_canary.judge import judge

REPO = Path(__file__).resolve().parents[2]
STALE_LOCK_S = 30 * 60  # longer than two backstopped measurements and their re-measure


def _take_lock(lock: Path) -> bool:
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        if time.time() - lock.stat().st_mtime > STALE_LOCK_S:
            lock.unlink(missing_ok=True)  # left by a pass that ended without its finally
    except FileNotFoundError:
        pass
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(handle, str(os.getpid()).encode())
    os.close(handle)
    return True


def _log(data: Path, line: str) -> None:
    data.mkdir(parents=True, exist_ok=True)
    with (data / "canary.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline_canary", description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--data", type=Path, default=None, help="default: <repo>/.thomas/pipeline_canary")
    parser.add_argument("--scratch", type=Path, default=Path(tempfile.gettempdir()) / "thomas-pipeline-canary")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("once", help="one pass: notice, measure, judge, act")
    commands.add_parser("status", help="the canary's state and its last measurements")
    replay = commands.add_parser("replay", help="measure two commits back to back and judge them")
    replay.add_argument("good")
    replay.add_argument("new")
    args = parser.parse_args(argv)
    data = args.data or args.repo / ".thomas" / "pipeline_canary"

    if args.command == "status":
        try:
            recent = (data / "history.jsonl").read_text(encoding="utf-8").splitlines()[-6:]
        except OSError:
            recent = []
        print(json.dumps({"state": canary.load_state(data), "recent": [json.loads(r) for r in recent]}, indent=2))
        return 0
    if args.command == "replay":
        good = measure.measure(args.repo, args.good, args.scratch, timeout_s=measure.BACKSTOP_S)
        new = measure.measure(args.repo, args.new, args.scratch, timeout_s=measure.BACKSTOP_S)
        reasons = judge(good, new)
        print(json.dumps({"good": good.as_dict(), "new": new.as_dict()}, indent=2))
        print("ALARM: " + "; ".join(reasons) if reasons else "fine")
        return 0

    lock = data / "run.lock"
    if not _take_lock(lock):
        print("a canary pass is already running")
        return 0
    try:
        actions = RealActions(args.repo, log_file=data / "canary.log")
        line = canary.run_once(args.repo, data, args.scratch, actions)
    except (OSError, ValueError, RuntimeError) as exc:  # one failed pass must not stop the next; the log says why
        line = f"the pass failed: {type(exc).__name__}: {exc}"
    finally:
        lock.unlink(missing_ok=True)
    _log(data, line)
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
