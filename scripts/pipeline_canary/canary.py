"""Notice dev moving, measure when the check machinery changed, and raise or clear the alarm.

Every lane moves the same ref (the promoter's cards and window, commit.py, taps, ship.py), so the canary reads
``refs/heads/dev`` itself and none bypasses it. State is ``state.json`` (last commit checked, last commit found good,
what the canary holds, the alarm while one stands) and ``history.jsonl`` (one line per measurement).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from scripts.pipeline_canary import measure
from scripts.pipeline_canary.judge import judge

# Run from pythonw by a scheduled task: without this each child opened a console window over the desktop.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

WATCHED = ("thomas/server/precard", "thomas/server/proof")
Measure = Callable[[Path, str, Path], measure.Measurement]


class Actions(Protocol):
    def alarm(self, alarm: dict[str, Any]) -> dict[str, bool]: ...

    def clear(self, holds: dict[str, bool]) -> None: ...

    def tell(self, title: str, body: str) -> None: ...


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False, creationflags=NO_WINDOW
    )
    if done.returncode:
        raise ValueError((done.stderr or "").strip().splitlines()[-1:] or [f"git {args[0]} failed"])
    return done.stdout.strip()


def head(repo: Path) -> str:
    return _git(repo, "rev-parse", "--verify", "refs/heads/dev")


def suspects(repo: Path, good: str, tip: str) -> list[str]:
    """The commits after *good* up to *tip* that changed a watched path, oldest first."""
    return [line for line in _git(repo, "log", "--format=%H", "--reverse", f"{good}..{tip}", "--", *WATCHED).split()]


def load_state(data: Path) -> dict[str, Any]:
    try:
        found = json.loads((Path(data) / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def save_state(data: Path, state: dict[str, Any]) -> None:
    Path(data).mkdir(parents=True, exist_ok=True)
    temporary = Path(data) / f"state.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, Path(data) / "state.json")


def _record(data: Path, role: str, found: measure.Measurement) -> None:
    Path(data).mkdir(parents=True, exist_ok=True)
    line = {"at": time.time(), "role": role, **found.as_dict()}
    with (Path(data) / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")


def _files(found: measure.Measurement) -> int:
    return found.files + found.left_out


def _default_measure(repo: Path, commit: str, root: Path) -> measure.Measurement:
    return measure.measure(repo, commit, root)


def _baseline(repo: Path, data: Path, scratch: Path, tip: str, measure_fn: Measure) -> str:
    found = measure_fn(repo, tip, scratch)
    _record(data, "baseline", found)
    if found.seconds is None:
        return f"no baseline yet: {found.error}"
    save_state(data, {"last_checked": tip, "last_good": tip, "holds": {}, "alarm": None})
    measure.prune(scratch, [tip])
    return f"baseline {tip[:8]}: {found.seconds:.1f} s, {_files(found)} test files"


def _judged(repo: Path, data: Path, scratch: Path, good: str, tip: str, measure_fn: Measure):
    """Measure *good* and *tip* back to back; a ratio-only alarm is measured once more before it counts."""
    before, after = measure_fn(repo, good, scratch), measure_fn(repo, tip, scratch)
    _record(data, "good", before)
    _record(data, "new", after)
    reasons = judge(before, after)
    if reasons and after.seconds is not None and all(reason.startswith("it took") for reason in reasons):
        before, after = measure_fn(repo, good, scratch), measure_fn(repo, tip, scratch)
        _record(data, "good", before)
        _record(data, "new", after)
        reasons = judge(before, after)
    return before, after, reasons


def run_once(repo: Path, data: Path, scratch: Path, act: Actions, *, measure_fn: Measure | None = None) -> str:
    """One pass: one line saying what it found and did. Never lands, never restarts anything."""
    measure_fn = measure_fn or _default_measure
    state = load_state(data)
    tip = head(repo)
    if not state.get("last_good"):
        return _baseline(repo, data, scratch, tip, measure_fn)
    if tip == state.get("last_checked"):
        return "dev has not moved"
    standing = state.get("alarm")
    try:
        found = suspects(repo, state["last_good"], tip)
        # With an alarm standing the bad commit stays in that range: measure again only for a new watched commit.
        fresh = suspects(repo, state["last_checked"], tip) if standing else found
    except ValueError:  # the good commit is no longer in dev's history: start again from here
        return _baseline(repo, data, scratch, tip, measure_fn)
    if not fresh:
        state["last_checked"] = tip
        if standing:
            save_state(data, state)
            return "dev moved without a change to the check machinery; the alarm still stands"
        state["last_good"] = tip
        save_state(data, state)
        return "dev moved without a change to the check machinery"
    before, after, reasons = _judged(repo, data, scratch, state["last_good"], tip, measure_fn)
    measure.prune(scratch, [state["last_good"], tip])
    if before.seconds is None:
        if after.seconds is None:
            return f"could not measure either commit: {before.error}; {after.error}"
        return _baseline(repo, data, scratch, tip, measure_fn)
    if not reasons:
        if standing:
            act.clear(dict(state.get("holds") or {}))
        save_state(data, {"last_checked": tip, "last_good": tip, "holds": {}, "alarm": None})
        measure.prune(scratch, [tip])
        return f"fine {tip[:8]}: {after.seconds:.1f} s against {before.seconds:.1f} s, {_files(after)} test files"
    alarm = {
        "at": time.time(),
        "head": tip,
        "good": before.as_dict(),
        "new": after.as_dict(),
        "reasons": reasons,
        "suspects": found,
    }
    holds = dict(state.get("holds") or {}) if standing else act.alarm(alarm)
    state.update(last_checked=tip, alarm=alarm, holds=holds)
    save_state(data, state)
    return f"ALARM {tip[:8]}{' still' if standing else ''}: " + "; ".join(reasons)


__all__ = ["WATCHED", "Actions", "head", "load_state", "run_once", "save_state", "suspects"]
