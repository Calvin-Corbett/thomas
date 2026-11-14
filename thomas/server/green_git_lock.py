"""A copy's git lock left behind by a git that was killed, and when it is safe to remove (2026-11-13).

Measured in ``hand_in_clocks.jsonl``: copy ``thomas-7d997486ee9a`` ended every check "unavailable" within a minute,
because ``git add --all`` met an ``index.lock`` that no git held any more. A git that is killed -- by the 600 s timeout
on a copy's git calls, or with the server -- leaves its lock behind, and nothing removed it, so every retry failed the
same way. A lock is removed only when it is older than any git call on a copy may run (``STALE_AFTER_S``, longer than
that timeout) and no git process that could hold it is running; otherwise it stays and the failure says why.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a dependency; without it no lock is ever taken as free
    psutil = None  # type: ignore[assignment]

LOCK_EXISTS = "index.lock': File exists"
# A copy's git call is stopped after 600 s (green_checkout._GIT_TIMEOUT_S), so a younger lock may still be held.
STALE_AFTER_S = 15 * 60.0


def _inside(text: str, places: list[str]) -> bool:
    folded = os.path.normcase(text.replace("/", os.sep))
    return any(place in folded for place in places)


def _same_user(proc: object, me: str) -> bool:
    """Could this process write the copy's git folder? Only you, SYSTEM and Administrators may; a process that says
    it runs as another account cannot. One that will not say is taken as able to."""
    try:
        return (proc.username() or "").lower() == me  # type: ignore[attr-defined]
    except (psutil.Error, OSError):
        return True


def git_holds(git_dir: Path, work: Path) -> bool:
    """Is a git process running that could hold this copy's lock? One whose working folder or command line names the
    copy's git folder or work tree, or one that runs as you and whose folder and command line cannot be read."""
    if psutil is None:  # pragma: no cover
        return True
    places = [os.path.normcase(str(Path(p).resolve())) for p in (git_dir, work)]
    try:
        me = (psutil.Process().username() or "").lower()
        for proc in psutil.process_iter(["name"]):
            if (proc.info["name"] or "").lower() not in ("git.exe", "git"):
                continue
            try:
                seen = [proc.cwd(), *proc.cmdline()]
            except (psutil.Error, OSError):
                if _same_user(proc, me):
                    return True
                continue
            if any(_inside(str(item), places) for item in seen):
                return True
    except (psutil.Error, OSError):
        return True
    return False


def clear_if_stale(
    git_dir: Path,
    work: Path,
    *,
    now: float | None = None,
    held: Callable[[Path, Path], bool] | None = None,
) -> str:
    """Remove the copy's ``index.lock`` when it is abandoned. Returns '' when it was removed (or is already gone), or
    why it was left in place."""
    held = held or git_holds
    lock = Path(git_dir) / "index.lock"
    try:
        age = (time.time() if now is None else now) - lock.stat().st_mtime
    except FileNotFoundError:
        return ""
    except OSError as exc:
        return f"the copy's git lock {lock} could not be read ({exc}), so it was left in place"
    if age < STALE_AFTER_S:
        return (
            f"the copy's git lock {lock} is {age:.0f} s old, younger than the {STALE_AFTER_S:.0f} s a git call on a "
            "copy may run, so it was left in place"
        )
    if held(Path(git_dir), Path(work)):
        return f"the copy's git lock {lock} is {age:.0f} s old but a git process may still hold it, so it was left in place"
    try:
        lock.unlink()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        return f"the copy's git lock {lock} is abandoned ({age:.0f} s old) but could not be removed: {exc}"
    return ""
