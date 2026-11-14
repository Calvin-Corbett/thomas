"""The last push of dev to GitHub, in plain words: what was pushed and when, or what stopped it.

The landing worker (``scripts/crew/brief/push_after_land.py``) writes one small file in the data folder each time a push
starts, waits, is skipped or ends. :func:`collect_github_push` reads it back, adds how far GitHub is behind (a local read of
the remote-tracking branch; never the network), and returns one sentence a person can read without a command or a log, for
``GET /api/landing-health``.

Nothing here raises: an unreadable file is said in words, and a number that could not be read is ``None``, never 0.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from thomas.core.config import resolve_thomas_data_dir
from thomas.core.git_process import run_git

STATE_NAME = "github_push.json"
REMOTE = "dev-origin"
BRANCH = "dev"
#: A push that says it is running for longer than this is taken as dead (the same age push_dev gives its lock).
RUNNING_MAX_AGE_S = 2 * 3600.0
_REPO_ROOT = Path(__file__).resolve().parents[2]
_QUIET_PREFIXES = ("error: failed to push", "hint:", "to ", "! [")
_READ_TRIES = 4


def state_path(data_dir: str | Path | None = None) -> Path:
    """The state file: in ``data_dir`` when given, else in the app's data folder."""
    return (Path(data_dir) if data_dir else resolve_thomas_data_dir()) / STATE_NAME


def read_state(data_dir: str | Path | None = None) -> dict[str, Any]:
    """The saved state, or {} when there is none. A read refused during a replace is tried again."""
    path = state_path(data_dir)
    for attempt in range(_READ_TRIES):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            return row if isinstance(row, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            time.sleep(0.05 * (attempt + 1))
    return {"status": "unreadable"}


def one_line_reason(output: str, fallback: str = "") -> str:
    """The line of a failed push's output that says why: the last one that is not git's own wrapper text."""
    lines = [ln.strip().removeprefix("remote:").strip() for ln in (output or "").splitlines() if ln.strip()]
    lines = [ln for ln in lines if ln]
    useful = [ln for ln in lines if not ln.lower().startswith(_QUIET_PREFIXES)]
    pick = (useful or lines or [fallback.strip()])[-1]
    return pick[:240]


def record(
    status: str,
    message: str,
    *,
    sha: str = "",
    output: str = "",
    data_dir: str | Path | None = None,
    now: float | None = None,
) -> None:
    """Save the outcome. The last time it really pushed is carried over until the next push replaces it."""
    before = read_state(data_dir)
    at = time.time() if now is None else now
    row: dict[str, Any] = {
        "status": status,
        "message": message[:600],
        "sha": sha,
        "at": at,
        "reason": one_line_reason(output, message) if status in ("blocked", "refused") else "",
        "last_pushed_at": before.get("last_pushed_at"),
        "last_pushed_sha": before.get("last_pushed_sha", ""),
    }
    if status == "pushed":
        row["last_pushed_at"], row["last_pushed_sha"] = at, sha
    path = state_path(data_dir)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _clock(ts: float, now: float) -> str:
    then, today = time.localtime(ts), time.localtime(now)
    hour = then.tm_hour % 12 or 12
    stamp = f"{hour}:{then.tm_min:02d} {'am' if then.tm_hour < 12 else 'pm'}"
    midnight = time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))
    if ts >= midnight:
        return f"today {stamp}"
    if ts >= midnight - 86400.0:
        return f"yesterday {stamp}"
    return f"{time.strftime('%b', then)} {then.tm_mday}, {stamp}"


def _landings(count: int) -> str:
    return f"{count} landing" if count == 1 else f"{count} landings"


def _behind(root: Path) -> int | None:
    done = run_git(
        ("rev-list", "--count", f"refs/remotes/{REMOTE}/{BRANCH}..refs/heads/{BRANCH}"), cwd=root, timeout=5.0
    )
    try:
        return int(done.output()) if done.ok else None
    except ValueError:
        return None


def _has_remote(root: Path) -> bool:
    return run_git(("remote", "get-url", REMOTE), cwd=root, timeout=5.0).ok


def describe(state: dict[str, Any], behind: int | None, now: float, *, has_remote: bool = True) -> tuple[str, str]:
    """(level, sentence): level is ok, watch or act. ``behind`` is how many landings GitHub lacks, if known."""
    status, at = str(state.get("status") or ""), state.get("at")
    when = _clock(float(at), now) if isinstance(at, (int, float)) else ""
    lag = f"GitHub is behind by {_landings(behind)}" if behind else "GitHub is behind"
    why = str(state.get("reason") or state.get("message") or "no reason given")
    if not state:
        if not has_remote:
            return "watch", "GitHub is not set up on this machine (no dev-origin remote), so nothing is pushed there."
        return "watch", "Nothing has been pushed to GitHub from this app yet."
    if status == "unreadable":
        return "watch", "The record of the last push to GitHub could not be read just now."
    if status in ("pushing", "waiting") and isinstance(at, (int, float)) and now - float(at) > RUNNING_MAX_AGE_S:
        return "watch", f"A push to GitHub started {when} and never finished; the next landing will try again."
    if status == "pushing":
        return "watch", f"Pushing to GitHub now (started {when})."
    if status == "waiting":
        return "watch", f"A push to GitHub is waiting for the one already running (since {when})."
    if status == "deferred":
        return "watch", "A push to GitHub will run when the landing still in line has finished."
    if status == "off":
        tail = f" {lag}." if behind else ""
        return "watch", f"Pushing to GitHub after a landing is turned off in your settings.{tail}"
    if status == "blocked":
        return "act", f"{lag}: a check stopped the push: {why}"
    if status == "refused":
        return "act", f"{lag}: GitHub refused the push: {why}"
    if status in ("pushed", "up_to_date"):
        last = state.get("last_pushed_at")
        stamp = _clock(float(last), now) if isinstance(last, (int, float)) else when
        if behind:
            verb = "is" if behind == 1 else "are"
            return "watch", f"Last pushed to GitHub: {stamp}. {_landings(behind)} since then {verb} not there yet."
        if status == "up_to_date":
            return "ok", f"GitHub is up to date (checked {when})."
        return "ok", f"Last pushed to GitHub: {stamp}."
    return "watch", f"The last push to GitHub ended as `{status or 'unknown'}`."


def collect_github_push(
    repo_root: str | Path | None = None, data_dir: str | Path | None = None, now: float | None = None
) -> dict[str, Any]:
    """The reading for the landing-health response. Never raises, never touches the network."""
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    clock = time.time() if now is None else now
    state = read_state(data_dir)
    behind: int | None = None
    has_remote = True
    try:
        behind = _behind(root)
        if not state:
            has_remote = _has_remote(root)
    except (OSError, ValueError) as exc:
        return {
            "status": "unknown",
            "level": "watch",
            "sentence": f"Thomas could not read how far GitHub is behind: {exc}",
            "behind": None,
        }
    level, sentence = describe(state, behind, clock, has_remote=has_remote)
    return {
        "status": state.get("status") or "none",
        "level": level,
        "sentence": sentence,
        "behind": behind,
        "at": state.get("at"),
        "sha": state.get("sha", ""),
        "last_pushed_at": state.get("last_pushed_at"),
        "last_pushed_sha": state.get("last_pushed_sha", ""),
        "reason": state.get("reason", ""),
    }
