"""Start the Thomas server as the cage account: the opt-in caged mode (Project 4).

Run by the ThomasCagedServer scheduled task as thomas-agent. It is the ordinary
server with four differences, all set here so the task needs no environment of
its own:

* ``THOMAS_OWNER_DESK=1`` -- this server has no desktop to show the Windows
  sign-in on, so every approval goes through the owner's desk, which runs as you
  (scripts/cage/owner_desk.py).
* ``CODEX_HOME`` points at your own ``.codex`` folder, shared with the cage
  account as you chose, so both use one login and a token refresh on one side
  never logs the other out.
* a port of its own (8898 by default), so it runs beside your usual server on
  8899 until it has proven itself; the owner-mode start stays the rollback.
* its own Claude sign-in, once scripts/cage/enable_cage_claude.ps1 has made
  ``C:\\ProgramData\\ThomasCage\\claude`` and you signed in there: the Claude CLI
  copied beside it is put first on ``PATH`` and uses that folder, never your
  own ``.claude``.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Where enable_cage_claude.ps1 puts the cage's Claude: its sign-in in claude\,
# a copy of the CLI in bin\. Nothing here is under your profile.
CAGE_ROOT = Path(r"C:\ProgramData\ThomasCage")


def claude_env(cage_root: Path | None = None, *, path: str | None = None) -> dict[str, str]:
    """The cage's own Claude, once its sign-in folder exists; else nothing.

    ``CLAUDE_CONFIG_DIR`` is where the CLI keeps (and refreshes) its sign-in, so
    it never looks in a ``.claude`` folder; nonessential traffic is off, so it
    asks the fence only for the model and the sign-in refresh.
    """
    root = Path(cage_root or CAGE_ROOT)
    config = root / "claude"
    if not config.is_dir():
        return {}
    current = os.environ.get("PATH", "") if path is None else path
    return {
        "CLAUDE_CONFIG_DIR": str(config),
        "PATH": os.pathsep.join(part for part in (str(root / "bin"), current) if part),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    }


CONSOLE_LOG = "thomas.log.console"
CONSOLE_LOG_MAX_BYTES = 20 * 1024 * 1024


def record_console(data_dir: Path) -> Path:
    """Send this process's console into ``<data dir>/logs/thomas.log.console``, appended.

    ``<data dir>/logs`` is where ``thomas serve`` points ``THOMAS_LOG_FILE``
    (``config.apply_runtime_data_env_defaults``), which is the folder the log export reads.

    The task that starts this server keeps no console, and ``thomas serve`` logs only to
    it: warnings, tracebacks and the supervisor's own "[thomas] Stopped by user." were all
    lost, so the six times the keepalive found this server gone on 2026-09-25 and 26 left
    no record of why. The name starts with ``thomas.log`` so ``GET /api/logs/export``
    includes it. A file past :data:`CONSOLE_LOG_MAX_BYTES` is kept as ``.1`` and restarted.
    """
    path = Path(data_dir) / "logs" / CONSOLE_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.stat().st_size > CONSOLE_LOG_MAX_BYTES:
            path.replace(path.with_name(CONSOLE_LOG + ".1"))
    except OSError:
        pass  # no file yet, or it cannot be moved: keep appending
    stream = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 -- open for the process's life
    sys.stdout = sys.stderr = stream
    return path


def run_recorded(serve: Callable[[], object]) -> None:
    """Run the server and write, in the console log, when it started and how it ended."""
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[caged] {started} pid {os.getpid()} starting", flush=True)
    try:
        serve()
    finally:  # nothing is caught: the exception on its way out, if any, is only named
        exc = sys.exc_info()[1]
        if isinstance(exc, KeyboardInterrupt):
            how = "stopped by a console Ctrl+C (KeyboardInterrupt)"
        elif isinstance(exc, SystemExit):
            how = f"exited (SystemExit {exc.code!r})"
        elif exc is not None:
            how = f"crashed: {type(exc).__name__}: {exc}"
        else:
            how = "returned"
        print(f"[caged] {time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()} {how}", flush=True)


def ignore_console_ctrl_c() -> bool:
    """Make this process, and every process it starts, ignore a console Ctrl+C. Windows only.

    Nobody sits at this server's console: it is a background task. But every Build runner and
    every test run of the check before your card is its child on that same console, and a
    Ctrl+C sent to "this console" by any one of them reaches all of them. On 2026-09-26 its
    log read "[thomas] Stopped by user." at 22:19:08 with no user anywhere, and a Build run it
    hosted had died with KeyboardInterrupt at 20:37; the keepalive restarted the server six
    times on 2026-09-25 and 26, cutting off every run it hosted. ``SetConsoleCtrlHandler(NULL,
    TRUE)`` turns Ctrl+C off for the process, and child processes inherit that. Task
    Scheduler can still end the server, and ``/api/server/restart`` can still restart it.
    """
    if os.name != "nt":
        return False
    import ctypes

    return bool(ctypes.windll.kernel32.SetConsoleCtrlHandler(None, True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Thomas server as the cage account.")
    parser.add_argument("--port", type=int, default=8898)
    parser.add_argument("--codex-home", default="", help="your .codex folder, shared with the cage account")
    args = parser.parse_args(argv)
    os.environ["THOMAS_OWNER_DESK"] = "1"
    if args.codex_home:
        os.environ["CODEX_HOME"] = args.codex_home
        # Your projects, scratch and task folders live in your own ~/.thomas (beside
        # that .codex). Build works there, not in a second, empty copy under the cage
        # account's home; enable_build_projects.ps1 gives it access to exactly those.
        os.environ.setdefault("THOMAS_OWNED_ROOT", str(Path(args.codex_home).parent / ".thomas"))
    os.chdir(REPO_ROOT)
    sys.path.insert(0, str(REPO_ROOT))
    from thomas.core.config import resolve_thomas_data_dir

    # Its own memory, in the cage account's own data folder: your server's lives
    # in the repo's runtime/, and a second server there would claim its
    # serve.lock -- and the cage account needs no write access to your memory.
    os.environ.setdefault("THOMAS_MEMORY_ROOT", str(resolve_thomas_data_dir() / "runtime"))
    record_console(resolve_thomas_data_dir())
    print(f"[caged] a console Ctrl+C is ignored: {ignore_console_ctrl_c()}", flush=True)
    # Before anything starts a child: the whole tree stays under its share of this PC (2026-10-25).
    from scripts.cage.cpu_cap import cap_this_process_tree

    print(f"[caged] {cap_this_process_tree()}", flush=True)
    # Behind the network fence its only way out is the owner's proxy; the model
    # clients (httpx) read these, so model calls keep working and nothing else leaves.
    from scripts.cage.egress_proxy import egress_env
    from scripts.cage.search_broker import broker_env

    os.environ.update(egress_env())
    # No search engine is on the fence's list: web.search and web.fetch go to your
    # search broker beside the proxy, which reads only pages a search returned.
    os.environ.update(broker_env())
    # Claude through the cage's own sign-in (Build's Claude family, the model list).
    os.environ.update(claude_env())
    from thomas.cli.main import main as thomas_main

    sys.argv = ["thomas", "serve", "--port", str(args.port)]
    run_recorded(thomas_main)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
