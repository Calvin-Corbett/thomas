"""Send a shell command to the caged account, and wait for its output.

The other half of ``scripts/cage/shell_runner.py``. Thomas's ``shell.exec``
hands the command to this, which drops it in the cage channel and waits. The
runner executes it as ``thomas-agent``, which can read and execute the repo but
cannot write Thomas's own code -- so a shell command cannot change him, however
the command is spelled. Nothing here parses or judges the command: this is a
privilege boundary, not a pattern list, and patterns are words.

Posture -- pinned in the cage root, else ``THOMAS_CAGE_SHELL``:

* ``auto`` (default): use the cage when its runner is alive, else run locally.
  Honest about what it is -- a step toward the wall, not the wall, because
  anything that can stop the runner gets an uncaged shell back.
* ``required``: the cage or nothing. If the runner is not answering, the shell
  refuses and says so. This is the wall.
* ``off``: never use the cage.

The pin (``<cage root>/posture``) is written by the elevated enabler into a
directory only Administrators can write, and it is a FLOOR: the environment and
the config may tighten it, never loosen it. thomas.toml cannot serve that
purpose -- the server runs as the owner's account and can rewrite a repo file
whenever it likes, and the protected-files gate only sees that afterwards, in a
diff. What is off-limits to the account is a different kind of statement from
what is off-limits by rule.

That boundary is about *persisted settings*, and is worth saying plainly: code
already executing inside the server process can still reach around any check
written in Python, here or anywhere else. What the cage stops is the shell --
every ``shell.exec`` runs as an account that cannot write Thomas's own code.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

CAGE_ROOT_ENV = "THOMAS_CAGE_ROOT"
POSTURE_ENV = "THOMAS_CAGE_SHELL"
DEFAULT_CAGE_ROOT = Path(r"C:\ProgramData\ThomasCage")
# Where pins live. NOT the cage root: the owner's account holds FullControl on
# ThomasCage (it has to, to manage the channels), and FullControl on a folder
# includes delete-child -- which removes any file inside it regardless of that
# file's own permissions. Measured 2026-09-22: an unelevated process deleted an
# Administrators-only file there with a plain File.Delete, and a deleted pin is
# a posture back in the hands of the environment. ProgramData only lets ordinary
# users create folders, never remove someone else's, so a folder an elevated
# script creates and owns is one the owner's unelevated processes cannot empty.
DEFAULT_PIN_ROOT = Path(r"C:\ProgramData\ThomasPins")
POSTURE_NAME = "posture"
# Strictness order. A pinned posture is a floor on this scale, so tightening is
# always allowed and loosening never is.
POSTURE_RANK = {"off": 0, "auto": 1, "required": 2}
HEARTBEAT_NAME = "runner.heartbeat"
# The runner beats every 5s; three missed beats means it is not there.
HEARTBEAT_STALE_S = 20.0
POLL_EVERY_S = 0.2


@dataclass(frozen=True)
class CagedResult:
    outcome: str  # ok | timeout | invalid | error | no_runner
    returncode: int
    output: str
    ran_as: str = ""


_LIVE_CAGE_ROOT = DEFAULT_CAGE_ROOT  # the real one, kept even when a test points DEFAULT_CAGE_ROOT elsewhere


def cage_root() -> Path:
    """The cage's folder: :data:`CAGE_ROOT_ENV`, else :data:`DEFAULT_CAGE_ROOT`.

    A test never reaches the live cage. On 2026-10-24 a copy of a test run outside tests/ (where conftest points this
    at a temp folder) and a fixture shared across tests wrote fake hand-ins into the live inbox, and the promoter made
    a card of one. Under pytest the live folder is refused instead of written to.
    """
    root = Path(os.environ.get(CAGE_ROOT_ENV) or DEFAULT_CAGE_ROOT)
    if os.environ.get("PYTEST_CURRENT_TEST") and root == _LIVE_CAGE_ROOT:
        raise RuntimeError(
            f"a test reached the live cage {root}: set {CAGE_ROOT_ENV} to a temp folder first "
            "(tests/conftest.py does this for each test, not for a fixture shared across tests)"
        )
    return root


@lru_cache(maxsize=1)
def _configured_posture() -> str:
    """``[tools] cage_shell`` from thomas.toml, or "" when it says nothing.

    Today this always answers "". ``ToolsConfig`` has no ``cage_shell`` field,
    and the loader builds it from explicit keyword arguments, so the key would
    be read from the file and dropped on the floor -- a setting that looks live
    and does nothing. The reader stays because it costs one getattr and starts
    working the day the field exists; the posture that actually decides
    anything is the pin, which no amount of config editing can lower.

    Cached: read on every shell call otherwise, and the file does not change
    under a running server. Deliberately forgiving -- an unreadable config
    answers "" (auto), because a broken config must not take the shell down.
    """
    try:
        from thomas.core.config import load_config

        override = os.environ.get("THOMAS_CONFIG")
        cfg = load_config(Path(override)) if override else load_config()
        return str(getattr(getattr(cfg, "tools", None), "cage_shell", "") or "").strip().lower()
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError):
        return ""


def _pin_roots(root: Path | None) -> tuple[Path, ...]:
    """Every root a pin is honoured from: the effective one and the default.

    Both, because ``THOMAS_CAGE_ROOT`` is an environment variable: pointing it
    at an empty directory would otherwise retire a pin simply by looking
    somewhere else.
    """
    effective = root or cage_root()
    roots: list[Path] = []
    # The pin root first: the only one an unelevated process cannot empty. The
    # others stay readable because the strictest pin wins, so an old pin can
    # only ever tighten -- never loosen -- what the pin root says.
    for candidate in (Path(DEFAULT_PIN_ROOT), Path(effective), Path(DEFAULT_CAGE_ROOT)):
        if all(candidate.resolve() != seen.resolve() for seen in roots):
            roots.append(candidate)
    return tuple(roots)


def pinned_posture(root: Path | None = None) -> str:
    """The strictest posture pinned on disk, or "" when nothing pins one.

    Not cached: an administrator changes this while the server runs, and a stale
    answer here would be a posture nobody chose.
    """
    best = ""
    for base in _pin_roots(root):
        path = base / POSTURE_NAME
        if not path.exists():
            continue
        try:
            # utf-8-sig: a BOM is not whitespace, so strip() leaves it in place
            # and the posture stops being recognised. A pin must not be retired
            # by whatever editor last touched it.
            raw = path.read_text(encoding="utf-8-sig").strip().lower()
        except (OSError, ValueError):
            raw = ""
        # A pin that exists but does not say anything recognised is read as the
        # strictest posture, not as no pin at all. Only an administrator can put
        # that file there, so its presence is the decision; a typo, a truncated
        # write or an unreadable byte must not be the difference between a wall
        # and nothing. Loud and wrong beats quietly absent.
        value = raw if raw in POSTURE_RANK else "required"
        if not best or POSTURE_RANK[value] > POSTURE_RANK[best]:
            best = value
    return best


def posture(root: Path | None = None) -> str:
    """auto, required or off -- environment over config, but never under the pin."""
    raw = str(os.environ.get(POSTURE_ENV) or "").strip().lower() or _configured_posture()
    chosen = raw if raw in POSTURE_RANK else "auto"
    pinned = pinned_posture(root)
    if pinned and POSTURE_RANK[pinned] > POSTURE_RANK[chosen]:
        return pinned
    return chosen


def runner_alive(root: Path | None = None) -> bool:
    """True when the caged runner has beaten recently."""
    beat = (root or cage_root()) / "shell" / HEARTBEAT_NAME
    try:
        return (time.time() - beat.stat().st_mtime) <= HEARTBEAT_STALE_S
    except OSError:
        return False


def end_green(execution_id: str, *, root: Path | None = None) -> CagedResult:
    """End the named project's recorded processes and return its remaining PID report."""
    if not runner_alive(root):
        if posture(root) != "required":
            return CagedResult("ok", 0, "no caged runner; no caged processes to end")
        return CagedResult("no_runner", -1, "the caged runner is not responding")
    return run_caged("", cwd="", timeout_s=10.0, root=root, extra={"action": "end_green", "green": execution_id})


def end_project_processes(project_root: Path) -> str:
    """Clean up shell children belonging to a private Build project, not other projects."""
    root = project_root.resolve()
    project = next(
        (
            parent.name
            for parent in (root, *root.parents)
            if parent.parent.name.lower() == "work" and parent.parent.parent.name.lower() == "green"
        ),
        "",
    )
    if not project:
        return "no caged project process group"
    result = end_green(project)
    if result.outcome == "ok" and result.returncode == 0:
        return result.output
    return f"cleanup unavailable: {result.output or result.outcome}"


def run_caged(
    command: str, *, cwd: str, timeout_s: float, root: Path | None = None, extra: dict | None = None
) -> CagedResult:
    """Run *command* as the caged account. Never runs it here.

    A reply that never arrives is a timeout, not a fall-back to running it
    locally: silently doing the thing the cage exists to prevent would be the
    one outcome worse than failing.
    """
    base = root or cage_root()
    inbox, outbox = base / "shell" / "inbox", base / "shell" / "outbox"
    request_id = uuid.uuid4().hex[:16]
    payload = {
        "id": request_id,
        "command": str(command),
        "cwd": str(cwd or ""),
        "timeout_s": float(timeout_s),
        "created_at": time.time(),
        **(extra or {}),
    }
    try:
        inbox.mkdir(parents=True, exist_ok=True)
        outbox.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(inbox), suffix=".part")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, inbox / f"{request_id}.json")
    except OSError as exc:
        log.warning("cage shell: could not submit the command: %s", exc)
        return CagedResult("no_runner", -1, f"the cage channel is not writable: {exc}")

    reply_path = outbox / f"{request_id}.json"
    # The runner's own timeout bounds the command; this waits a little longer so
    # a slow disk does not read as a hang.
    deadline = time.time() + float(timeout_s) + 15.0
    while time.time() < deadline:
        try:
            if reply_path.exists():
                reply = json.loads(reply_path.read_text(encoding="utf-8"))
                reply_path.unlink(missing_ok=True)
                # `or -1` would turn a successful exit code 0 into a failure.
                code = reply.get("returncode")
                return CagedResult(
                    str(reply.get("outcome") or "error"),
                    int(code) if isinstance(code, (int, float)) else -1,
                    str(reply.get("output") or ""),
                    str(reply.get("ran_as") or ""),
                )
        except (OSError, ValueError):
            pass  # half-written or briefly locked; look again
        time.sleep(POLL_EVERY_S)

    (inbox / f"{request_id}.json").unlink(missing_ok=True)
    return CagedResult("timeout", -1, f"the caged runner did not answer within {timeout_s:g}s")


__all__ = [
    "CAGE_ROOT_ENV",
    "CagedResult",
    "DEFAULT_CAGE_ROOT",
    "POSTURE_ENV",
    "cage_root",
    "end_green",
    "end_project_processes",
    "posture",
    "run_caged",
    "runner_alive",
]
