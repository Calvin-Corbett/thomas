"""Default command runners for the sites that take an injected runner, run through the sandbox slot.

``thomas/core/acceptance_contract.py`` and ``thomas/agent/subtask_graph.py`` run commands that an agent wrote. They take
a runner so tests can inject one; the runner they fell back to started a process as the server's own account whatever the
cage posture said. These two functions are the new fallback. ``thomas/core`` cannot import the slot (it lives in
``thomas/tools``), so the seam stays in core and the default lives here.

Each call looks the slot up when it runs, reads the ladder once, and runs by what it read, whatever the folder is:

- ``local`` (posture off, or auto with a silent runner): the site's own previous runner, unchanged.
- ``caged``: the command runs as the caged account, in the folder the site already used, with the same timeout. The cage
  can read the live checkout, the greens and ``~/.thomas`` but only write under ``~/.thomas/projects``; a command that
  needs to write elsewhere fails with the cage's own permission error, shown in its output. That is the cage working, so
  nothing falls back to this account because of the folder.
- ``refused`` (posture required, runner silent) or an ``error`` answer: nothing ran, and that is a failed result that
  no ``expected_returncode`` can turn into a pass. ``contract_runner`` gives exit 127 or 124 (the contract only passes on
  0); ``argv_runner`` gives ``COMMAND_NOT_RUN`` or ``COMMAND_TIMED_OUT``, which no criterion expects, and the subtask
  verifier fails them before it compares codes.

Neither site has ever checked ``tools.allow_shell``: the caller decides whether commands run at all (``run_commands`` for
the contract, the command allowlist for the subtask checks), so both pass ``allowed=True`` to the sandbox on purpose.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from thomas.tools import sandbox_slot as slot

log = logging.getLogger(__name__)

#: The exit code the contract already gives a command that could not start, and one that ran out of time.
COULD_NOT_RUN, TIMED_OUT = 127, 124

#: What ``argv_runner`` gives a command the sandbox did not run, and one that ran out of time. Negative, because a real
#: process never exits with them and a criterion's ``expected_returncode`` is never one; ``CommandRerunVerifier`` also
#: fails them before comparing, so even ``expected_returncode=-127`` cannot count a command that did not run as a pass.
COMMAND_NOT_RUN, COMMAND_TIMED_OUT = -127, -124

_OUTPUT_TAIL = 1500


def _not_run_text(result: slot.SandboxResult) -> str:
    return (result.output or "").strip() or f"the sandbox answered {result.outcome}, so nothing ran"


def contract_runner(command: str, cwd: Path, timeout: float, *, strict: bool = False) -> tuple[int, str]:
    """``Runner`` for ``acceptance_contract``: ``(exit code, output tail)`` of a shell command in the workspace."""
    from thomas.core import acceptance_contract as ac

    try:
        rung = slot.sandbox().rung(allowed=True)  # allowed=True: the caller's run_commands already decided to run it
        if rung == slot.LOCAL:
            return ac.default_runner(command, cwd, timeout)  # looked up now, so the site's own runner stays patchable
        result = slot.sandbox().run(command, cwd=str(cwd), timeout_s=timeout, allowed=True, rung=rung)
    except Exception as exc:
        log.exception("the sandbox could not run a contract command; nothing was run here instead")
        if strict:
            raise
        return COULD_NOT_RUN, f"the sandbox failed, so nothing ran: {exc}"
    if result.outcome == slot.OK and result.returncode is not None:
        return int(result.returncode), result.output[-_OUTPUT_TAIL:]
    if result.outcome == slot.TIMEOUT:
        return TIMED_OUT, f"timed out after {int(timeout)}s"
    return COULD_NOT_RUN, _not_run_text(result)


def argv_runner(
    argv: Sequence[str],
    cwd: str | None,
    timeout_seconds: int,
    *,
    local: Callable[[list[str], str | None, int], tuple[int, str, str]],
    pin: Callable[[list[str]], list[str]],
    snippet: Callable[[str], str],
    strict: bool = False,
) -> tuple[int, str, str]:
    """``CommandRunner`` for ``subtask_graph``: ``(exit code, stdout, stderr)`` of an argv in a folder.

    *local* is the site's previous runner, used on the ``local`` rung; *pin* maps a bare ``python`` to the interpreter.
    """
    args = list(argv)
    try:
        rung = slot.sandbox().rung(allowed=True)  # allowed=True: the command allowlist is this site's only gate
        if rung == slot.LOCAL:
            return local(args, cwd, timeout_seconds)
        if not cwd:
            return COMMAND_NOT_RUN, "", "no project folder is given, so the command was not run in the cage"
        command = subprocess.list2cmdline(pin(args)) if os.name == "nt" else shlex.join(pin(args))
        result = slot.sandbox().run(
            command, cwd=str(cwd), timeout_s=max(1, int(timeout_seconds)), allowed=True, rung=rung
        )
    except Exception as exc:
        log.exception("the sandbox could not run a check; nothing was run here instead")
        if strict:
            raise
        return COMMAND_NOT_RUN, "", f"the sandbox failed, so nothing ran: {exc}"
    if result.outcome == slot.OK and result.returncode is not None:
        return int(result.returncode), snippet(result.output), ""
    if result.outcome == slot.TIMEOUT:
        return COMMAND_TIMED_OUT, snippet(result.output), "timed out"
    return COMMAND_NOT_RUN, "", _not_run_text(result)


def argv_ladder(
    argv: Sequence[str], cwd: str, timeout_s: float, *, allowed: bool, strict: bool = False
) -> tuple[str, int | None, str]:
    """Run an argv in a folder by the ladder: ``(status, exit code, output)``.

    ``status`` is ``local`` (nothing ran: the ladder says run it here, so the site runs its own code), ``ran`` (the cage
    ran it; output is stdout and stderr merged), ``timeout``, or ``not_run`` (refused, switched off or errored: nothing
    ran, output says why). *allowed* has no default; each site says what it honours.
    The ladder is read once, so the rung that is read is the rung that runs.
    """
    command = subprocess.list2cmdline(list(argv)) if os.name == "nt" else shlex.join(argv)
    try:
        rung = slot.sandbox().rung(allowed=allowed)
        if rung == slot.LOCAL:
            return "local", None, ""
        result = slot.sandbox().run(command, cwd=cwd, timeout_s=max(1, int(timeout_s)), allowed=allowed, rung=rung)
    except Exception as exc:
        log.exception("the sandbox could not run a check; nothing was run here instead")
        if strict:
            raise
        return "not_run", None, f"the sandbox failed, so nothing ran: {exc}"
    if result.outcome == slot.OK and result.returncode is not None:
        return "ran", int(result.returncode), result.output
    if result.outcome == slot.TIMEOUT:
        return "timeout", None, result.output
    return "not_run", None, _not_run_text(result)
