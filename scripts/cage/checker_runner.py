"""Launch a job's test processes under a separate, lower-privilege account (review B1).

The checker service runs as ``thomas-checker`` and is the only account that writes the ``results`` and ``state``
folders the promoter trusts. A change's own code runs while it is checked, so it must not run as that account, or it
could write its own PASSED, or another job's. ``scripts/cage/enable_window.ps1`` creates ``thomas-runner``: an account
that may read the repo and write only inside a job's copy, and that has no grant on ``jobs``, ``results`` or ``state``.
This module launches every test process as that account.

Fail closed. The service calls :meth:`Runner.available` before a job and answers UNAVAILABLE when there is no isolated
identity, so a change's tests are never run as the account that writes the answer. The isolated account is named in
``<state>/runner.json`` (written by the setup, in a folder only the checker may write), and its credential is read by
the Windows launcher (:mod:`scripts.cage.checker_launch`) from the checker's own credential store, which the runner
account cannot read. Tests inject ``launch``; nothing here creates an account, changes an ACL or starts a real process.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.cage import checker_jobs as cj
from scripts.cage import checker_run as cr

from thomas.server import proof
from thomas.server.proof.environment import NOT_STARTED

SCHEMA = 1
CONFIG_NAME = "runner.json"
# A launcher runs one command as the runner account and gives back (exit code, output), like
# thomas.server.proof.environment.run_quietly, and never raises for what the command did.
Launch = Callable[..., tuple[int, str]]


@dataclass(frozen=True)
class Identity:
    """The account a test runs as, and where its credential is kept for the launcher to read."""

    account: str  # e.g. "THISPC\\thomas-runner"
    credential: str  # the name the checker's credential store keeps the runner's logon under


def read_identity(state_root: Path) -> Identity | None:
    """The runner identity the setup recorded, or None when it is absent or not a well-formed record."""
    try:
        raw = cj.read_json(Path(state_root) / CONFIG_NAME)
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return None
    account, credential = raw.get("account"), raw.get("credential")
    if not isinstance(account, str) or not account.strip() or not isinstance(credential, str) or not credential.strip():
        return None
    return Identity(account.strip(), credential.strip())


class Runner:
    """The checker's isolated test-runner: available only when a separate identity is configured and launchable."""

    def __init__(self, state_root: Path, *, launch: Launch | None = None, identity: Identity | None = None) -> None:
        self.state_root = Path(state_root)
        self._identity = identity if identity is not None else read_identity(self.state_root)
        self._launch = launch  # tests inject this; production resolves the Windows launcher lazily

    @property
    def configured(self) -> bool:
        return self._identity is not None

    def available(self) -> bool:
        """True only when a separate identity is configured and a launcher for it can be used on this platform."""
        return self._identity is not None and self._resolve_launch() is not None

    def reason(self) -> str:
        """Why the checker cannot run a change's tests under a separate identity, for the UNAVAILABLE answer."""
        if self._identity is None:
            return f"no runner identity is recorded at {self.state_root / CONFIG_NAME}; run enable_window.ps1"
        if self._resolve_launch() is None:
            return "no launcher can run a process as the runner account on this platform"
        return ""

    def _resolve_launch(self) -> Launch | None:
        if self._launch is not None:
            return self._launch
        import os

        if os.name != "nt":
            return None
        try:
            from scripts.cage.checker_launch import run_as
        except ImportError:
            return None
        return run_as

    def run(self, command: list[str], *, cwd: Path, env: dict[str, str], timeout_s: float) -> tuple[int, str]:
        """Run *command* as the runner account. Never raises: an identity or launcher that is gone answers
        NOT_STARTED, so a run that could not happen is read as "did not run", never as a pass."""
        launch = self._resolve_launch()
        if launch is None or self._identity is None:
            return NOT_STARTED, f"the checker could not run this as its isolated identity: {self.reason()}"
        try:
            return launch(list(command), cwd=Path(cwd), env=dict(env), timeout_s=timeout_s, identity=self._identity)
        except OSError as exc:
            return NOT_STARTED, f"the runner account could not start the test process: {exc}"

    def tools(self) -> cr.Tools:
        """A :class:`~scripts.cage.checker_run.Tools` whose every test process runs through :meth:`run`.

        Only the subprocess launch is the runner's; selection, confirmation and report reading stay in the checker
        process (which cannot be influenced by a test's own code)."""
        run = self.run

        def run_tests(*args: Any, **kwargs: Any) -> proof.ProofRun:
            return proof.run_tests(*args, run=run, **kwargs)

        def run_one(*args: Any, **kwargs: Any) -> str:
            return proof.run_one(*args, run=run, **kwargs)

        return cr.Tools(run_tests=run_tests, run_one=run_one, run=run)


__all__ = ["CONFIG_NAME", "SCHEMA", "Identity", "Runner", "read_identity"]
