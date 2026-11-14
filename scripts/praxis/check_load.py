"""Start several checks before the card at the same moment, and record what they took (spec 2026-10-12 Part 1).

    python scripts/praxis/check_load.py [--count 6] [--min-files 20] [--max-files 120] [--wait-quiet SECONDS]

Run it as you, on the machine both servers run on, from your checkout. It makes ``--count`` green copies of that
checkout's dev in your green root, puts one harmless change in each (a comment set apart by two blank lines at the
end of a different module whose covering tests number between ``--min-files`` and ``--max-files``, which keeps the
module passing ``ruff format`` and ``ruff check`` whatever its last line is), starts the check before the card on every
copy in the same second, reads the free disk of the greens' drive once before the checks start and once a second
while they run, and removes the copies when every check has answered. Each check writes its clocks to
``hand_in_clocks.jsonl`` the way a real hand-in does, so ``scripts/praxis_timeline.py`` counts it; this run's summary
goes to ``runtime/praxis_check_load/<stamp>.json``, with each check's selected files and the tests it saw with the
change and on dev. No card is made and nothing is handed in. Every file it writes has Unix line ends.

Every copy is removed even when a check raises or the run is interrupted. A copy that cannot be removed is printed
to stderr, listed under ``copies_left`` in the summary, and makes the exit code 1; it never hides a check's own error,
which is raised once the other copies have been removed.

Each check's own lowest free-disk reading is taken while it ran (its ``in_slot`` stage window exactly as the clocks
record it, else the whole call), and measured from the last reading before it began (``free_disk_start_bytes`` when
there is none), so disk freed earlier in the run, such as a dead check's leftovers cleared by the first check, is
never taken off its own use. With checks one at a time, or with one check, that is the most disk the check used
(``disk_peak_bytes``); ``--disk-out`` writes the largest of those and each check's selected-file count, aggregates
only, for the repo. The last line printed gives the start and end as local times and the folder the clocks went into,
ready for ``scripts/praxis_timeline.py --since``, ``--until`` and ``--catalog-root``. The entries and the printed
lines are built in ``check_load_record``.

Beside the disk, once a second, it reads how busy the machine is with other work (``check_load_machine``: the busy
CPU minus this run's own process tree, and how many headless browser processes of other work run), so each check's
entry says its other load over the same window as its disk, and ``quiet`` says at least 80% of it was read and no
second of it was over a quarter of the machine or had a headless browser process. The summary's ``quiet`` is true
only when every check's was; the lines it prints say first when the run was not quiet, which checks overlapped
other load, and which went unread. ``--wait-quiet SECONDS`` (0 for off, else at least 60) first waits, once the
copies are made, for 60 quiet seconds in a row, saying so each minute; past SECONDS it starts anyway and the summary
says it never got quiet. Run as a script, it joins a Windows job (``check_load_job``), so every process it started
ends when it ends (finished, stopped with Ctrl+C, or crashed) unless it asked to break away from the job.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.praxis import check_load_job, check_load_machine  # noqa: E402
from scripts.praxis.check_load_record import (  # noqa: E402
    check_entry,
    disk_record,
    load_summary,
    load_window,
    summary_lines,
    timeline_line,
)
from scripts.praxis.check_load_record import disk_window as _disk  # noqa: E402
from scripts.praxis.check_load_record import local_time as _local  # noqa: E402
from scripts.praxis.check_load_record import ran_window as _ran  # noqa: E402, F401  (an older import path)
from thomas.server import green_checkout, precard, proof  # noqa: E402
from thomas.server.precard import clocks  # noqa: E402

MARK = "# check load run: a comment, so the change is harmless\n"
SIZE_LIMIT = 780  # a module this long could pass the 800-line rule with one more line
START_TIMEOUT_S = 120.0
SAMPLE_S = 1.0
# What an ordinary fault in a check can be, as keeper_guard.CAPTURE_ERRORS lists it: kept, and raised when the run ends.
CHECK_ERRORS = (
    OSError,
    green_checkout.GreenUnavailable,
    ValueError,
    TypeError,
    LookupError,
    AttributeError,
    RuntimeError,
    ArithmeticError,
    ImportError,
    subprocess.SubprocessError,
)


def tests_texts(blue: Path) -> dict[str, str]:
    folder = Path(blue) / proof.TESTS_DIR
    return {
        path.relative_to(blue).as_posix(): path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(folder.rglob("*.py"))
    }


def pick_modules(
    blue: Path, *, count: int, min_files: int, max_files: int, texts: dict[str, str] | None = None
) -> list[tuple[str, int]]:
    """Up to *count* modules under thomas/, each covered by between *min_files* and *max_files* test files."""
    if count < 1:
        return []
    texts = tests_texts(blue) if texts is None else texts
    picked: list[tuple[str, int]] = []
    for path in sorted((Path(blue) / "thomas").rglob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            lines = len(path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError):
            continue
        if lines >= SIZE_LIMIT:
            continue
        rel = path.relative_to(blue).as_posix()
        covered = len(proof.select_from(texts, [rel], cap=max_files + 1).files)
        if min_files <= covered <= max_files:
            picked.append((rel, covered))
            if len(picked) == count:
                break
    return picked


def _mark(target: Path) -> None:
    """End *target* with :data:`MARK` after two blank lines, byte for byte, so no other line of it changes.

    ``ruff format`` wants two blank lines before a comment that follows a def or a class, and the check runs it on this
    change. The new lines use the module's own line end, so a module with Windows line ends is not left with two kinds.
    """
    data = target.read_bytes()
    first = data.find(b"\n")
    eol = b"\r\n" if first > 0 and data[first - 1 : first] == b"\r" else b"\n"
    ended = b"" if not data or data.endswith(b"\n") else eol
    apart = eol * 2 if data else b""
    target.write_bytes(data + ended + apart + MARK.rstrip("\n").encode("utf-8") + eol)


def _one(
    green: Any,
    module: str,
    catalog: Path,
    stamp: str,
    start: threading.Barrier,
    out: dict[str, dict[str, Any]],
    errors: list[BaseException],
) -> None:
    try:
        start.wait(timeout=START_TIMEOUT_S)
        began = time.time()
        with clocks.recording(catalog, f"load-{green.execution_id}") as record:
            clocks.note("execution_id", green.execution_id)
            clocks.note("load_run", stamp)
            with clocks.stage("check_for_hand_in"):
                checked = precard.check_before_card(green.execution_id)
        out[green.execution_id] = check_entry(green.execution_id, module, record, checked, began)
    except CHECK_ERRORS as exc:  # the check's own error: kept for the end of the run, never lost with this thread
        errors.append(exc)
        print(f"the check on {green.execution_id} raised {type(exc).__name__}: {exc}", file=sys.stderr)


def _remove_all(greens: list[Any]) -> list[dict[str, str]]:
    """Try to remove every copy, whatever happens to the others, and return the ones that would not go."""
    left: list[dict[str, str]] = []
    for green in greens:
        try:
            green_checkout.remove_green(green)
        except OSError as exc:  # also GreenKept: the keeper could not save the copy, so it stays for a sweep
            reason = f"{type(exc).__name__}: {exc}"
            left.append({"execution_id": green.execution_id, "work": str(green.work), "error": reason})
            print(f"could not remove the copy {green.execution_id} at {green.work}: {reason}", file=sys.stderr)
    return left


def _wait(threads: list[threading.Thread]) -> None:
    """Join in short turns: a join with no timeout can sit through Ctrl+C on Windows."""
    for thread in threads:
        while thread.is_alive():
            thread.join(0.5)


def run_load(
    blue: Path, catalog: Path, picked: list[tuple[str, int]], *, stamp: str, wait_quiet_s: float = 0.0, sampler=None
) -> dict[str, Any]:
    greens: list[Any] = []
    results: dict[str, dict[str, Any]] = {}
    errors: list[BaseException] = []
    samples: list[tuple[float, int]] = []
    readings: list[check_load_machine.Reading] = []
    sampler = check_load_machine.Sampler() if sampler is None else sampler
    waited: dict[str, Any] | None = None
    done = threading.Event()

    def watch() -> None:
        while True:
            samples.append((time.time(), shutil.disk_usage(green_checkout.green_root()).free))
            if done.wait(SAMPLE_S):
                return

    began = time.time()
    start_free: int | None = None
    try:
        for number, (module, _covered) in enumerate(picked, start=1):
            green = green_checkout.create_green(blue=blue, execution_id=f"load-{stamp}-{number}")
            greens.append(green)  # before anything else can fail, so the copy is removed whatever happens next
            _mark(green.work / module)
        if wait_quiet_s > 0:
            waited = check_load_machine.wait_quiet(sampler, wait_quiet_s, every_s=SAMPLE_S)
        start_free = shutil.disk_usage(green_checkout.green_root()).free  # every copy made, no check started
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        reader = check_load_machine.watch(sampler, SAMPLE_S, done, readings)
        start = threading.Barrier(len(greens))
        threads = [
            threading.Thread(
                target=_one, args=(green, module, Path(catalog), stamp, start, results, errors), daemon=True
            )
            for green, (module, _covered) in zip(greens, picked)
        ]
        for thread in threads:
            thread.start()
        _wait(threads)
        done.set()
        watcher.join(timeout=5)
        reader.join(timeout=5)
        if errors:
            raise errors[0]
        unanswered = [green.execution_id for green in greens if green.execution_id not in results]
        if unanswered:
            raise RuntimeError(f"the check on {', '.join(unanswered)} ended without an answer; see its error above")
    finally:
        done.set()
        left = _remove_all(greens)
    checks = [results[green.execution_id] for green in greens if green.execution_id in results]
    for entry in checks:
        _disk(entry, samples, start_free)
        load_window(entry, readings)
    peaks = [entry["disk_peak_bytes"] for entry in checks if entry["disk_peak_bytes"] is not None]
    ended = time.time()
    return {
        "stamp": stamp,
        "started_at": began,
        "ended_at": ended,
        "started_at_local": _local(began),
        "ended_at_local": _local(ended),
        "checks": checks,
        "free_disk_start_bytes": start_free,
        "free_disk_min_bytes": min((free for _at, free in samples), default=None),
        "check_disk_peak_bytes": max(peaks) if peaks else None,
        "copies_left": left,
        **load_summary(checks, readings, waited, getattr(sampler, "own_from", None)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start several checks before the card at once and time them.")
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--min-files", type=int, default=20)
    parser.add_argument("--max-files", type=int, default=120)
    parser.add_argument("--blue", default=str(_REPO_ROOT), help="the checkout whose dev the copies are made from")
    parser.add_argument("--out-dir", default=str(_REPO_ROOT / "runtime" / "praxis_check_load"))
    parser.add_argument("--disk-out", default="", help="also write the disk figures (aggregates only) to this file")
    parser.add_argument(
        "--wait-quiet", type=float, default=0.0, metavar="SECONDS", help="first wait for a quiet machine"
    )
    args = parser.parse_args(argv)
    if args.count < 1 or not check_load_machine.wait_allowed(args.wait_quiet):
        parser.error("--count must be at least 1, and --wait-quiet 0 (off) or a number of seconds of at least 60")
    if precard.turned_off():
        print(f"The check before the card is turned off here ({precard.CHECK_ENV}); unset it to run a load run.")
        return 2
    blue = Path(args.blue)
    picked = pick_modules(blue, count=args.count, min_files=args.min_files, max_files=args.max_files)
    if len(picked) < args.count:
        print(f"Only {len(picked)} modules have between {args.min_files} and {args.max_files} covering test files.")
        return 2
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    result = run_load(blue, blue, picked, stamp=stamp, wait_quiet_s=args.wait_quiet)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stamp}.json").write_text(json.dumps(result, indent=1), encoding="utf-8", newline="\n")
    if args.disk_out:
        target = Path(args.disk_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(disk_record(result), indent=1, sort_keys=True) + "\n"
        target.write_text(text, encoding="utf-8", newline="\n")
    for line in summary_lines(result):
        print(line)
    print(f"wrote {out / f'{stamp}.json'}")
    for left in result["copies_left"]:
        print(f"COPY LEFT BEHIND, remove it by hand: {left['work']} ({left['error']})")
    print(timeline_line(result, blue))
    return 1 if result["copies_left"] else 0


if __name__ == "__main__":
    check_load_job.join_job()  # every process the run starts ends with it, and its CPU counts ended children
    raise SystemExit(main())
