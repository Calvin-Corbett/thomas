"""What a proof runs with: an interpreter, and an environment that cannot reach your real data.

You said, of the check before your card: "Never let the check write my real data (unset every THOMAS_*
variable it inherits and give it its own data folder), never use the running copy's git index, and never
block the server's loop." :func:`sandbox_env` is the first two of those. Every ``THOMAS_*`` and ``GIT_*``
variable the server inherited is dropped, and the only ones put back name folders inside the proof's own
scratch space -- so a test that writes a database, a runtime folder or a green writes it there and nowhere
else, and no git call can be aimed at the running copy's index by an inherited ``GIT_DIR``.

The ratchet's proof step, not on dev yet, runs the same tests in a copy for the same reason and
must not write your data either, so this is one of the pieces it is meant to call rather than repeat.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from thomas.core import git_launcher

# An interpreter to prove with, named outright. Without it a proof looks for the repo's own ``.venv``: that
# is where pytest, ruff and the project's dependencies actually are.
PYTHON_ENV = "THOMAS_PROOF_PYTHON"
# Dropped from every child: the data variables; the git ones that would silently aim a git call at
# another repository (``GIT_DIR``, ``GIT_INDEX_FILE``); and the pytest ones, because a proof run started
# from inside a pytest session would otherwise inherit that session's ``PYTEST_ADDOPTS``; and the fast_tests
# ones, because an inherited FAST_TESTS_SELECT would narrow a nested run to the wrong files.
_DROPPED = ("THOMAS_", "GIT_", "PYTEST_", "FAST_TESTS_")
# Returned instead of an exit code when a command never produced one.
TIMED_OUT = -1001
NOT_STARTED = -1002
# What the pool's run answers when its ledger gave a shard no place and the shard was not started. Apart from
# NOT_STARTED (a command that would not launch), so only the pool's refusal reads as "try again later".
REFUSED = -1003


def interpreter(repo: Path) -> str:
    """The Python a proof runs with: :data:`PYTHON_ENV` if it names a real file, else *repo*'s ``.venv``, else "".

    "" is not a failure of the change -- it means this machine cannot prove anything here, and the caller
    says so rather than passing a change it never checked.
    """
    named = str(os.environ.get(PYTHON_ENV) or "").strip()
    if named:
        return named if Path(named).is_file() else ""
    for rel in (Path(".venv") / "Scripts" / "python.exe", Path(".venv") / "bin" / "python"):
        candidate = Path(repo) / rel
        if candidate.is_file():
            return str(candidate)
    return ""


def sandbox_env(work: Path, data_dir: Path, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment a proof's commands run in: your variables dropped, a data folder of its own.

    ``PYTHONPATH`` is *work*, so ``import thomas`` finds the copy being proven and never the running
    checkout an editable install would otherwise resolve to. ``PATH`` finds the real git ahead of Git for
    Windows' launcher (:func:`thomas.core.git_launcher.real_git_first`): a test that starts git starts one
    process, not two. Not when *extra* names ``MSYSTEM``: the real git would then add nothing its hooks need.
    """
    named = {str(k): str(v) for k, v in (extra or {}).items()}
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(_DROPPED)}
    if not any(key.upper() == "MSYSTEM" for key in named):
        env = git_launcher.real_git_first(env)
    # The tests' own Thomas folders, apart from the runner's reports and selection files beside them in *data_dir*:
    # tests/conftest.py treats THOMAS_DATA_DIR as real data, so with the reports inside it every shard that read its
    # selection file or wrote its report failed its session, all tests passed (exit 1, "contradicts its report").
    home = data_dir / "thomas"
    home.mkdir(parents=True, exist_ok=True)
    env.update(
        THOMAS_DATA_DIR=str(home),
        THOMAS_HOME=str(home),
        THOMAS_STATE_DIR=str(home),
        THOMAS_RUNTIME_DIR=str(home / "runtime"),
        THOMAS_DB_PATH=str(home / "thomas.db"),
        THOMAS_GREEN_ROOT=str(home / "green"),
        THOMAS_CAGE_ROOT=str(home / "cage"),
        THOMAS_PROJECT_ROOT=str(home / "board"),
        PYTHONPATH=str(work),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
    )
    # A test that imports numpy sets aside ~480 MB of commit for one math thread per CPU; one thread is enough
    # for the tests' vectors and every shard runs beside others (see thomas.memory.embedder._numpy).
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.update(named)
    return env


def run_quietly(command: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout_s: float) -> tuple[int, str]:
    """Run *command* and give back its exit code and output. Never raises.

    A command that timed out answers :data:`TIMED_OUT`, one that could not be started
    :data:`NOT_STARTED`; both carry a sentence a person can read in place of output.
    """
    try:
        done = subprocess.run(
            list(command),
            cwd=str(cwd),
            env=dict(env),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
            # Its own hidden console: a test that sends a console Ctrl+C reaches only this run, never the
            # server and the Build runs that shared its console (2026-09-26).
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        return TIMED_OUT, f"it did not finish within {timeout_s:g}s"
    except (OSError, ValueError) as exc:
        return NOT_STARTED, f"it could not be started: {exc}"
    return done.returncode, (done.stdout or "") + (done.stderr or "")


__all__ = ["NOT_STARTED", "PYTHON_ENV", "REFUSED", "TIMED_OUT", "interpreter", "run_quietly", "sandbox_env"]
