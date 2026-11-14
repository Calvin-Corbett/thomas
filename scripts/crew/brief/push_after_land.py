"""Push ``dev`` to GitHub after a landing: on by default, one at a time, and one push for a run of landings.

``land_worker`` calls :func:`push_after_landing` once a landing has finished and the queue's lease is released, so the landing's
result is already final and nothing here can change it or hold up the next landing. What this adds to ``push_dev``:

* On unless you turn it off. The switch is a saved setting in the app's own settings store
  (``advanced.runtime.push_dev_after_landing``, true unless set to false), read straight from that store without changing it.
  No environment variable turns a push on, and none is read at all.
* One push for a run of landings. While another landing is still in the line, this one pushes nothing: the push after the
  last of them sends the tip, which holds the earlier ones too.
* A push already running makes this one wait for it, not start a second one. ``push_dev`` answers ``busy`` while its lock is
  held; this polls until the lock is free, then pushes whatever the tip is by then (usually nothing, already sent).
* It never raises: a failure comes back as an :class:`Outcome` that says what stopped.

The outcome is saved for the app to show (``thomas.core.github_push_status``). Nothing is recorded or said for a repository with no ``dev-origin`` remote (a scratch repository has no GitHub to push to).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from subprocess import SubprocessError

from scripts.crew.brief import push_dev
from scripts.crew.brief.git_reads import run_git

SETTING = "push_dev_after_landing"
POLL_S = 10.0
PUSH_FAILED = (OSError, ValueError, RuntimeError, LookupError, TypeError, SubprocessError)


@dataclass
class Outcome:
    status: str  # off | deferred | pushing | waiting | pushed | up_to_date | refused | blocked | no_remote | no_branch
    message: str
    sha: str = ""
    output: str = ""


def _nothing(_outcome: Outcome) -> None:
    return None


def save_outcome(outcome: Outcome) -> None:
    """Write the outcome where the app's landing-health reading finds it. A failed write is said, never raised."""
    try:
        from thomas.core import github_push_status

        github_push_status.record(outcome.status, outcome.message, sha=outcome.sha, output=outcome.output)
    except (ImportError, OSError, ValueError) as exc:
        print(f"could not save the push outcome: {exc}", file=sys.stderr)


def a_push_was_put_off() -> bool:
    """Whether an earlier landing left its push to a later one (so a later landing that ends without landing must send it)."""
    try:
        from thomas.core import github_push_status

        return github_push_status.read_state().get("status") == "deferred"
    except (ImportError, OSError, ValueError):
        return False


def pushing_is_on(db_path: str | Path | None = None) -> bool:
    """Whether the saved setting asks for a push after a landing. True unless it says false; unreadable means true."""
    try:
        if db_path is None:
            from thomas.preferences.store import get_db_path

            db_path = get_db_path()
        path = Path(db_path)
        if not path.is_file():
            return True
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("SELECT data_json FROM preferences WHERE user_id = ?", ("default",)).fetchone()
        finally:
            con.close()
        if not row:
            return True
        runtime = ((json.loads(row[0]) or {}).get("advanced") or {}).get("runtime") or {}
        return runtime.get(SETTING, True) is not False
    except (ImportError, OSError, sqlite3.Error, ValueError, TypeError, AttributeError):
        return True


def push_after_landing(
    root: Path,
    *,
    agent: str,
    others_waiting: bool = False,
    remote: str = "dev-origin",
    branch: str = "dev",
    db_path: str | Path | None = None,
    push: Callable[..., push_dev.PushResult] = push_dev.push_landed,
    sleep: Callable[[float], None] = time.sleep,
    poll: float = POLL_S,
    record: Callable[[Outcome], None] = save_outcome,
    say: Callable[[str], None] = _nothing,  # type: ignore[assignment]
) -> Outcome:
    """The push that follows a landing. Returns what happened; never raises."""
    root = Path(root)
    try:
        if run_git(root, ("remote", "get-url", remote)).returncode != 0:
            return Outcome("no_remote", f"nothing pushed: remote `{remote}` is not configured here")
    except (OSError, ValueError, SubprocessError) as exc:
        return Outcome("no_remote", f"nothing pushed: could not look for remote `{remote}`: {exc}")
    if not pushing_is_on(db_path):
        out = Outcome("off", "pushing to GitHub after a landing is turned off in your settings: nothing was pushed")
        record(out)
        say(out.message)
        return out
    if others_waiting:
        out = Outcome("deferred", "another landing is waiting: the push after the last one will carry this one too")
        record(out)
        say(out.message)
        return out
    record(Outcome("pushing", "pushing to GitHub"))
    while True:
        try:
            result = push(root, agent=agent, remote=remote, branch=branch)
        except PUSH_FAILED as exc:
            out = Outcome("blocked", f"not pushed: the push could not run: {type(exc).__name__}: {exc}")
            break
        if result.status != "busy":
            out = Outcome(result.status, result.message, result.sha, result.output)
            break
        record(Outcome("waiting", result.message, result.sha))
        say("a push is already running: waiting for it, then pushing the tip")
        sleep(poll)
    record(out)
    say(out.message)
    return out
