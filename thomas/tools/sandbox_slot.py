"""The sandbox slot: how a command is run, as a ladder of four outcomes.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md (slots). This describes the decision
``thomas/tools/shell.py`` makes before it runs a command. Nothing outside tests calls it yet, and
the shell keeps its own copy of the decision until a later wave moves it here.

``Sandbox.run`` follows the ladder: ``caged`` goes to the cage, ``local`` to ``run_contained``, ``refused`` and ``disabled``
run nothing. The cage returns stdout and stderr merged; the local run joins stdout then stderr.

The four outcomes, read from ``ShellTool.execute``:

- ``disabled``: ``tools.allow_shell`` is off, so the command does not run.
- ``caged``: the caged account is wanted and its runner answers, so the command runs as that account.
- ``refused``: the cage is required and its runner is silent, so the command does not run. Nothing falls back to the
  owner's own account.
- ``local``: no cage is wanted, or one is wanted ("auto") and the runner is silent, so the command runs as this process.

A slot that is missing never reads as ``local``. ``rung_for`` raises ``SandboxMissing`` instead, so a command is
refused rather than run on the owner's account because nobody provided a sandbox.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from thomas.core.kernel import SANDBOX, SandboxSeam, require

log = logging.getLogger(__name__)

DISABLED = "disabled"
CAGED = "caged"
REFUSED = "refused"
LOCAL = "local"

#: Every outcome, from the most closed to the most open.
RUNGS: tuple[str, ...] = (DISABLED, REFUSED, CAGED, LOCAL)

#: The outcomes after which a command has been run by something.
RUNS_COMMAND: frozenset[str] = frozenset({CAGED, LOCAL})


#: Outcomes of ``Sandbox.run``. ``refused`` and ``error`` mean nothing ran (or the cage could not say); ``timeout`` means
#: the clock ran out.
OK, TIMEOUT, ERROR = "ok", "timeout", "error"


@dataclass(frozen=True)
class SandboxResult:
    """What running a command came to. ``returncode`` is None when nothing ran or the clock ran out.

    ``output`` is stdout and stderr merged: the cage returns them merged, and the local run joins stdout then stderr
    so both rungs read the same. ``ran_as`` names the account that ran it (the cage reports it; local leaves it empty).
    """

    outcome: str  # ok | timeout | refused | error
    returncode: int | None
    output: str
    ran_as: str = ""


_CAGE_REQUIRED_WORDS = (
    "the cage is required and its runner is not answering, so nothing ran; nothing was run on this account"
)


_SWITCHED_OFF_WORDS = "running commands is switched off, so nothing ran"


class SandboxMissing(RuntimeError):
    """Nobody provides a sandbox, or the provider's answer is not one of the four outcomes. The command is refused."""


class Sandbox:
    """The default provider for the ``sandbox`` seam: the shell's own ladder, from the cage's posture and heartbeat."""

    name = "default-sandbox"

    def __init__(
        self,
        *,
        posture: Callable[[], str] | None = None,
        runner_alive: Callable[[], bool] | None = None,
        cage_run: Callable[..., Any] | None = None,
        local_run: Callable[..., tuple[int | None, str, str]] | None = None,
    ) -> None:
        self._posture = posture
        self._runner_alive = runner_alive
        self._cage_run = cage_run
        self._local_run = local_run

    def rung(self, *, allowed: bool = True) -> str:
        """Which of the four outcomes a command gets, for the same inputs the shell reads."""
        if not allowed:
            return DISABLED
        # Looked up on each call, so a changed environment variable or heartbeat is seen at once.
        from thomas.tools import cage_shell

        stance = self._posture() if self._posture is not None else cage_shell.posture()
        if stance == "off":
            return LOCAL
        alive = self._runner_alive() if self._runner_alive is not None else cage_shell.runner_alive()
        if alive:
            return CAGED
        return REFUSED if stance == "required" else LOCAL

    def run(
        self,
        command: str,
        *,
        cwd: str,
        timeout_s: float,
        allowed: bool,
        strict: bool = False,
        rung: str | None = None,
    ) -> SandboxResult:
        """Run *command* on the rung ``rung()`` gives. Only ``caged`` and ``local`` run anything.

        *allowed* has no default: it is whether this caller may run commands at all (``tools.allow_shell`` for the shell),
        and forgetting it is a ``TypeError`` rather than a silent yes. ``allowed=False`` runs nothing.

        *rung* is an outcome the caller already read, so one command is decided once and a heartbeat that dies between two
        reads cannot move it from one rung to another. It must be one of the four; ``allowed=False`` still wins over it.

        A cage that raises is an ``error`` result and the command is not run here instead; ``strict`` lets the error through.
        """
        try:
            if rung is not None and rung not in RUNGS:
                raise SandboxMissing(f"the rung {rung!r} is not one of {', '.join(RUNGS)}")
            decided = (DISABLED if not allowed else rung) if rung is not None else self.rung(allowed=allowed)
        except Exception as exc:
            log.exception("the sandbox could not decide; the command was not run")
            if strict:
                raise
            return SandboxResult(ERROR, None, f"the sandbox could not decide, so nothing ran: {exc}")
        if decided == CAGED:
            return self._run_caged(command, cwd, timeout_s, strict)
        if decided == LOCAL:
            return self._run_local(command, cwd, timeout_s, strict)
        if decided == REFUSED:
            return SandboxResult(REFUSED, None, _CAGE_REQUIRED_WORDS)
        return SandboxResult(REFUSED, None, _SWITCHED_OFF_WORDS)

    def _run_caged(self, command: str, cwd: str, timeout_s: float, strict: bool) -> SandboxResult:
        try:
            if self._cage_run is not None:
                reply = self._cage_run(command, cwd=cwd, timeout_s=timeout_s)
            else:
                from thomas.tools import cage_shell

                reply = cage_shell.run_caged(command, cwd=cwd, timeout_s=timeout_s)
        except Exception as exc:
            log.exception("the cage failed; the command was not run here instead")
            if strict:
                raise
            return SandboxResult(ERROR, None, f"the cage failed, so nothing ran: {exc}")
        code = reply.returncode if reply.outcome == OK else None
        if reply.outcome in (OK, TIMEOUT):
            return SandboxResult(reply.outcome, code, reply.output, reply.ran_as)
        if reply.outcome in ("no_runner", "invalid"):
            return SandboxResult(REFUSED, None, reply.output, reply.ran_as)
        return SandboxResult(ERROR, None, reply.output, reply.ran_as)

    def _run_local(self, command: str, cwd: str, timeout_s: float, strict: bool) -> SandboxResult:
        try:
            if self._local_run is not None:
                code, out, err = self._local_run(command, cwd=cwd, timeout=timeout_s)
            else:
                from thomas.core.contained_process import run_contained

                code, out, err = run_contained(command, cwd=cwd, timeout=timeout_s)
        except Exception as exc:
            log.exception("the command could not be started")
            if strict:
                raise
            return SandboxResult(ERROR, None, f"the command could not be started: {exc}")
        output = out + err
        if code is None:
            return SandboxResult(TIMEOUT, None, output)
        return SandboxResult(OK, code, output)


class RefusingSandbox:
    """A provider for a host that has no sandbox: every command is refused, none runs locally."""

    name = "refusing-sandbox"

    def rung(self, *, allowed: bool = True) -> str:
        return DISABLED if not allowed else REFUSED

    def run(
        self,
        command: str,
        *,
        cwd: str,
        timeout_s: float,
        allowed: bool,
        strict: bool = False,
        rung: str | None = None,
    ) -> SandboxResult:
        return SandboxResult(REFUSED, None, "this host has no sandbox, so nothing ran")


_sandbox = Sandbox()


def sandbox() -> Sandbox:
    """The process-wide sandbox slot."""
    return _sandbox


def sandbox_from(ctx: Any) -> SandboxSeam:
    """The sandbox a context provides. Raises ``SandboxMissing`` when there is none; never a local default."""
    if not ctx.has(SANDBOX):
        raise SandboxMissing("no sandbox is provided, so the command was refused; nothing was run on this account")
    return require(ctx, SANDBOX, SandboxSeam)


def rung_for(ctx: Any, *, allowed: bool = True, strict: bool = False) -> str:
    """The outcome for a command in this context, or ``SandboxMissing`` when no usable sandbox answers.

    ``strict`` lets a provider's own error through instead of turning it into a refusal.
    """
    provider = sandbox_from(ctx)
    try:
        answer = provider.rung(allowed=allowed)
    except Exception as exc:
        log.exception("the sandbox could not answer; the command is refused")
        if strict:
            raise
        raise SandboxMissing(f"the sandbox could not answer, so the command was refused: {exc}") from exc
    if answer not in RUNGS:
        raise SandboxMissing(f"the sandbox answered {answer!r}, which is not one of {', '.join(RUNGS)}; refused")
    return answer


def run(ctx: Any, command: str, *, cwd: str, timeout_s: float, allowed: bool, strict: bool = False) -> SandboxResult:
    """Run *command* through the sandbox a context provides, or the process-wide one when *ctx* is None.

    *allowed* has no default; ``allowed=False`` runs nothing and does not ask the provider. A missing sandbox, or a
    provider that cannot run commands, is a ``refused`` result; nothing runs locally instead.
    """
    if not allowed:
        return SandboxResult(REFUSED, None, _SWITCHED_OFF_WORDS)
    if ctx is None:
        provider: Any = sandbox()
    else:
        try:
            provider = sandbox_from(ctx)
        except SandboxMissing as exc:
            return SandboxResult(REFUSED, None, str(exc))
    runner = getattr(provider, "run", None)
    if runner is None:
        return SandboxResult(REFUSED, None, "the sandbox cannot run commands, so nothing ran")
    try:
        return runner(command, cwd=cwd, timeout_s=timeout_s, allowed=allowed)
    except Exception as exc:
        log.exception("the sandbox failed; the command was not run here instead")
        if strict:
            raise
        return SandboxResult(ERROR, None, f"the sandbox failed, so nothing ran: {exc}")
