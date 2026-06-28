"""Engine-side verification — the RUN/TEST step of the reason→edit→verify loop.

The dispatched agent is edit-only (it has no shell), but the build is a LOOP,
not a one-shot edit. After the agent's edit pass the *engine* — ordinary Python
in this process — runs a REAL check over the files the run changed and reflects
its REAL exit code back into the same streamed transcript. Nothing here is ever
fabricated: the pass/fail shown is the genuine returncode of a genuine subprocess.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .bridge_config import emergency_stop_active
from .bridge_prompts import compose_fix_prompt
from .forge_event_stream import FORGE_EVENT_KEY

# A small, self-contained verifier program: byte-compile each changed file and
# import each changed package module. A syntax error (py_compile) or an import
# error raises -> the subprocess exits non-zero -> the run is honestly a failure.
_VERIFY_SRC = (
    "import importlib, json, sys, py_compile\n"
    "files = json.loads(sys.argv[1])\n"
    "mods = json.loads(sys.argv[2])\n"
    "for f in files:\n"
    "    py_compile.compile(f, doraise=True)\n"
    "    print('compiled ' + f)\n"
    "for m in mods:\n"
    "    importlib.import_module(m)\n"
    "    print('imported ' + m)\n"
    "print('VERIFY_OK: ' + str(len(files)) + ' compiled, ' + str(len(mods)) + ' imported')\n"
)


def _is_test_file(path: str) -> bool:
    """True for a pytest-shaped path (``tests/`` dir or ``test_*`` / ``*_test.py``)."""
    p = str(path).replace("\\", "/")
    base = p.rsplit("/", 1)[-1]
    return base.startswith("test_") or base.endswith("_test.py") or "/tests/" in p or p.startswith("tests/")


def _importable_module_for(cwd: str | Path, path: str) -> str:
    """Dotted module name for ``path`` IFF it lives in a real package under ``cwd``.

    Only nested package modules (a top dir containing ``__init__.py``) are
    importable safely from the worktree; top-level scripts and non-identifier
    paths return ``""`` and are byte-compiled only (not executed).
    """
    p = str(path).replace("\\", "/")
    if not p.endswith(".py"):
        return ""
    segs = p[:-3].split("/")
    if segs and segs[-1] == "__init__":
        segs = segs[:-1]
    if len(segs) < 2 or not all(s.isidentifier() for s in segs):
        return ""
    if not (Path(cwd) / segs[0] / "__init__.py").exists():
        return ""
    return ".".join(segs)


def verify_python_changes(
    cwd: str | Path,
    changed_files: list[str],
    emit: Callable[[dict[str, Any]], None],
    *,
    timeout: int = 120,
    run_check: Any = None,
) -> tuple[bool, int, str]:
    """Run a REAL verification subprocess over the changed python files.

    Emits the check as a forge ``tool`` call and its result as a forge
    ``tool_result`` carrying the REAL exit code. Returns ``(ok, returncode, summary)``.

    * changed test files -> run them with ``pytest`` (executes the tests).
    * else -> byte-compile every changed ``.py`` and import the changed package
      modules (executes them) in ONE subprocess with ONE real exit code.

    ``run_check(cmd, cwd, timeout) -> (rc, out)`` is injectable for tests.
    Defensive: a check that cannot even be launched surfaces honestly as a failed
    tool result, never crashes the stream.
    """
    import subprocess
    import sys

    files = [f for f in (changed_files or []) if str(f).endswith(".py")]
    if not files:
        return True, 0, "no python files changed — nothing to verify"

    tests = [f for f in files if _is_test_file(f)]
    if tests:
        cmd = [sys.executable, "-m", "pytest", *tests, "-q"]
        label = "pytest " + " ".join(tests)
    else:
        modules = [m for m in (_importable_module_for(cwd, f) for f in files) if m]
        cmd = [sys.executable, "-c", _VERIFY_SRC, json.dumps(files), json.dumps(modules)]
        label = "verify: byte-compile + import (" + ", ".join(files) + ")"

    emit({FORGE_EVENT_KEY: "tool", "name": "run", "text": label[:200]})
    try:
        if run_check is not None:
            rc, out = run_check(cmd, str(cwd), timeout)
        else:
            proc = subprocess.run(  # noqa: S603 - cmd is python + repo-relative files we computed
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            rc, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, TypeError) as exc:
        emit({FORGE_EVENT_KEY: "tool_result", "text": f"verification could not run: {exc}", "is_error": True})
        return False, 1, f"verification could not run: {exc}"

    ok = rc == 0
    body = str(out or "").strip()
    detail = f"exit {rc}" + (("\n" + body) if body else "")
    emit({FORGE_EVENT_KEY: "tool_result", "text": detail[:500], "is_error": not ok})
    return ok, rc, detail[-1500:]


def _verify_and_iterate(
    cwd: str | Path,
    snap_before: dict[str, str],
    emit: Callable[[dict[str, Any]], None],
    run_pass: Callable[[str], tuple[int, str]],
    goal: str,
    *,
    verifier: Any = None,
    max_fix_iters: int = 2,
) -> int:
    """Verify THIS run's changes; on failure, feed the failure back for bounded fixes.

    ``run_pass(prompt) -> (rc, out)`` runs one more edit pass through the SAME CLI.
    Returns the final returncode: ``0`` when verification ultimately passes (or
    there was nothing to verify), else the non-zero exit of the failing check or
    the failing fix pass. Never raises — a fix pass that errors surfaces honestly.
    """
    from thomas.forge.anvil import forge_code_git

    verify = verifier or verify_python_changes
    changed = forge_code_git.delta_since(cwd, snap_before)
    if not changed:
        return 0  # nothing this run touched -> caller surfaces the no-op honestly

    ok, rc, summary = verify(cwd, changed, emit)
    iters = 0
    limit = max(0, int(max_fix_iters))
    while not ok and iters < limit:
        # A fix pass re-invokes the agent, so the kill switch gates it too: if an
        # operator drops the STOP file mid-build, stop iterating and surface the
        # last real failure rather than spawning another build.
        if emergency_stop_active():
            emit({FORGE_EVENT_KEY: "error", "text": "emergency stop active — halting fix loop"})
            return rc or 1
        iters += 1
        emit({FORGE_EVENT_KEY: "meta", "text": f"verification failed (exit {rc}); fix pass {iters}/{limit}"})
        try:
            frc, _out = run_pass(compose_fix_prompt(goal, summary))
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            emit({FORGE_EVENT_KEY: "error", "text": f"fix pass could not run: {exc}"})
            return rc or 1
        if frc != 0:
            return frc
        changed = forge_code_git.delta_since(cwd, snap_before)
        if not changed:
            return 0
        ok, rc, summary = verify(cwd, changed, emit)
    return 0 if ok else (rc or 1)
