"""CAP-060: isolated per-task sandbox/VM runtime -- hermetic core.

Runs code in an isolated *per-task* sandbox with resource limits and a
**guaranteed teardown**. This module is the hermetic core of the capability:
the provider SPI, the lifecycle manager, the resource-limit spec, and the
isolation/teardown policy are all real, complete, and tested. Only the physical
provisioning of a container/VM is gated behind an injectable adapter.

Architecture
------------
- :class:`ResourceSpec` -- cpu/mem/disk/net limits recorded on every sandbox.
- :class:`Sandbox` -- an opaque handle: which task owns it, its resource spec,
  when it was created, and whether it is still alive.
- :class:`SandboxProvider` -- the SPI: ``create`` / ``exec`` / ``destroy``.
  Two implementations ship here:
    * :class:`SubprocessSandboxProvider` -- the **real default** (LIVE LANE).
      It shells to a container runtime (``docker``/``podman``) with
      ``--cpus`` / ``--memory`` / ``--network`` flags using only stdlib
      :mod:`subprocess`. It needs a running container daemon, so it is NOT
      exercised by the hermetic test suite (see the class docstring).
    * :class:`FakeSandboxProvider` -- a hermetic, in-memory provider that
      enforces per-sandbox namespacing (isolated filesystem + env per
      sandbox). Used by the tests to prove isolation and teardown.
- :class:`SandboxManager` -- the lifecycle manager. It hands out one sandbox
  per task, records the resource spec, runs code inside, and **guarantees**
  the sandbox is destroyed on normal completion AND when ``exec`` raises, via a
  ``try/finally`` context manager -- no leaked sandboxes.

Everything is deterministic: the manager takes an injected monotonic clock and
an injected provider. No network, no wall-clock, no ambient state.

This module depends only on the standard library (tools layer rule).
"""

from __future__ import annotations

import logging
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class SandboxError(RuntimeError):
    """Raised when a sandbox operation is invalid (bad/foreign/dead handle)."""


@dataclass(frozen=True)
class ResourceSpec:
    """Resource limits applied to a sandbox at creation time.

    Attributes:
        cpus: CPU quota (e.g. ``1.5`` cores). Maps to ``docker run --cpus``.
        memory_mb: Memory ceiling in megabytes. Maps to ``--memory``.
        disk_mb: Disk/storage ceiling in megabytes. Maps to ``--storage-opt``.
        network: Network mode. ``"none"`` isolates the sandbox from the
            network (the safe default); ``"bridge"`` allows egress.
    """

    cpus: float = 1.0
    memory_mb: int = 512
    disk_mb: int = 1024
    network: str = "none"

    def docker_flags(self) -> list[str]:
        """Render this spec as container-runtime CLI flags (live lane)."""
        return [
            f"--cpus={self.cpus}",
            f"--memory={self.memory_mb}m",
            f"--storage-opt=size={self.disk_mb}m",
            f"--network={self.network}",
        ]


@dataclass
class Sandbox:
    """Opaque handle to one provisioned sandbox.

    Attributes:
        sandbox_id: Provider-unique id for this sandbox instance.
        task_id: The task that owns this sandbox (isolation boundary).
        resource_spec: The :class:`ResourceSpec` this sandbox was created with.
        created_at: Injected-clock timestamp of creation.
        alive: ``False`` once the sandbox has been destroyed.
    """

    sandbox_id: str
    task_id: str
    resource_spec: ResourceSpec
    created_at: float
    alive: bool = True


@dataclass
class ExecResult:
    """Result of running code inside a sandbox."""

    exit_code: int
    stdout: str
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@runtime_checkable
class SandboxProvider(Protocol):
    """SPI for a sandbox backend: create, exec, destroy.

    A provider is the injectable runtime edge. The manager depends only on this
    protocol, so the physical runtime (real container vs. hermetic fake) is
    swapped without touching lifecycle/isolation/policy logic.
    """

    def create(self, task_id: str, spec: ResourceSpec, *, created_at: float) -> Sandbox:
        """Provision an isolated sandbox for ``task_id`` with ``spec``."""

    def exec(self, sandbox: Sandbox, code: str) -> ExecResult:
        """Run ``code`` inside ``sandbox`` and return its output."""

    def destroy(self, sandbox: Sandbox) -> None:
        """Tear down ``sandbox``; idempotent. Must not leak the instance."""


# ---------------------------------------------------------------------------
# Live lane: real container-runtime provider (NOT run in the hermetic tests)
# ---------------------------------------------------------------------------

# A runner is the single stdlib edge we shell through. Default targets the real
# system via subprocess.run; tests never touch this provider.
CommandRunner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` via stdlib subprocess (no shell), capturing text output."""
    return subprocess.run(  # noqa: S603 -- argv list, no shell, live lane
        argv,
        capture_output=True,
        text=True,
        check=False,
    )


class SubprocessSandboxProvider:
    """Real default provider: shells to docker/podman (LIVE LANE).

    Live-lane requirements (honest gate -- NOT exercised by the test suite):
        * A running container daemon: Docker Engine or Podman on ``PATH``.
        * Permission to run containers (docker socket / rootless podman).
        * A base image to launch (default ``python:3.12-slim``).

    Isolation and resource limits are enforced by the container runtime itself:
    ``create`` runs ``<runtime> run -d`` with the :class:`ResourceSpec` rendered
    to ``--cpus`` / ``--memory`` / ``--storage-opt`` / ``--network`` flags;
    ``exec`` uses ``<runtime> exec``; ``destroy`` uses ``<runtime> rm -f`` for a
    guaranteed teardown. Each task gets its own container, so one task cannot
    read another's filesystem or environment.

    The command edge is injectable (``runner``) purely so the argv construction
    is unit-testable without a daemon; the DEFAULT targets the real system.
    """

    def __init__(
        self,
        *,
        runtime: str = "docker",
        image: str = "python:3.12-slim",
        runner: CommandRunner | None = None,
    ) -> None:
        self.runtime = runtime
        self.image = image
        self._runner = runner or _default_runner
        self._counter = 0

    def _run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        result = self._runner(argv)
        if result.returncode != 0:
            logger.warning(
                "container command failed (%s): rc=%s stderr=%s",
                " ".join(argv[:3]),
                result.returncode,
                (result.stderr or "").strip()[:200],
            )
        return result

    def create(self, task_id: str, spec: ResourceSpec, *, created_at: float) -> Sandbox:
        self._counter += 1
        name = f"thomas-sbx-{task_id}-{self._counter}"
        argv = [self.runtime, "run", "-d", "--name", name, *spec.docker_flags(), self.image, "sleep", "infinity"]
        proc = self._run(argv)
        if proc.returncode != 0:
            raise SandboxError(f"failed to create sandbox for task {task_id}: {proc.stderr.strip()}")
        container_id = (proc.stdout or name).strip()
        return Sandbox(sandbox_id=container_id, task_id=task_id, resource_spec=spec, created_at=created_at)

    def exec(self, sandbox: Sandbox, code: str) -> ExecResult:
        if not sandbox.alive:
            raise SandboxError(f"sandbox {sandbox.sandbox_id} is not alive")
        argv = [self.runtime, "exec", sandbox.sandbox_id, "sh", "-c", code]
        proc = self._run(argv)
        return ExecResult(exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)

    def destroy(self, sandbox: Sandbox) -> None:
        if not sandbox.alive:
            return
        self._run([self.runtime, "rm", "-f", sandbox.sandbox_id])
        sandbox.alive = False


# ---------------------------------------------------------------------------
# Hermetic fake provider: in-memory, namespace-enforcing (used by tests)
# ---------------------------------------------------------------------------


@dataclass
class _FakeInstance:
    """In-memory state for one fake sandbox: its own filesystem + env."""

    sandbox: Sandbox
    filesystem: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)


class FakeSandboxProvider:
    """Hermetic provider that enforces per-sandbox namespacing.

    Each sandbox gets its own private filesystem and environment keyed by
    ``sandbox_id``. There is deliberately no shared/global store, so one
    sandbox physically cannot address another's data -- that IS the isolation
    guarantee, proven by the tests.

    ``exec`` interprets a tiny, deterministic command language (one op per
    input, whitespace-separated) so behaviour is fully reproducible:

        ``echo <text...>``        -> write ``<text>`` to stdout
        ``write <path> <text...>``-> store ``<text>`` at ``<path>``
        ``read <path>``           -> stdout the stored value, or rc=1 if absent
        ``setenv <key> <val>``    -> set an env var in this sandbox
        ``getenv <key>``          -> stdout the env value, or rc=1 if unset

    ``live_count`` exposes how many sandboxes are currently alive so tests can
    assert guaranteed teardown (zero leaks).
    """

    def __init__(self) -> None:
        self._instances: dict[str, _FakeInstance] = {}
        self._counter = 0
        self.created_ids: list[str] = []
        self.destroyed_ids: list[str] = []

    # -- introspection for tests -------------------------------------------
    @property
    def live_count(self) -> int:
        return sum(1 for inst in self._instances.values() if inst.sandbox.alive)

    def live_ids(self) -> list[str]:
        return [sid for sid, inst in self._instances.items() if inst.sandbox.alive]

    # -- SPI ---------------------------------------------------------------
    def create(self, task_id: str, spec: ResourceSpec, *, created_at: float) -> Sandbox:
        self._counter += 1
        sandbox_id = f"fake-sbx-{task_id}-{self._counter}"
        sandbox = Sandbox(
            sandbox_id=sandbox_id,
            task_id=task_id,
            resource_spec=spec,
            created_at=created_at,
        )
        # Seed the sandbox env from the spec so the recorded limits are visible
        # from inside (mirrors real containers exposing their own environment).
        inst = _FakeInstance(sandbox=sandbox)
        inst.env["THOMAS_TASK_ID"] = task_id
        inst.env["THOMAS_CPUS"] = str(spec.cpus)
        inst.env["THOMAS_MEMORY_MB"] = str(spec.memory_mb)
        inst.env["THOMAS_NETWORK"] = spec.network
        self._instances[sandbox_id] = inst
        self.created_ids.append(sandbox_id)
        return sandbox

    def _resolve(self, sandbox: Sandbox) -> _FakeInstance:
        inst = self._instances.get(sandbox.sandbox_id)
        if inst is None:
            raise SandboxError(f"unknown sandbox {sandbox.sandbox_id!r} (foreign or never created)")
        if inst.sandbox is not sandbox:
            # A handle addressing a real id but not the instance we created is
            # a forged/foreign handle -- reject it (isolation enforcement).
            raise SandboxError(f"handle mismatch for sandbox {sandbox.sandbox_id!r}")
        if not sandbox.alive:
            raise SandboxError(f"sandbox {sandbox.sandbox_id!r} is not alive")
        return inst

    def exec(self, sandbox: Sandbox, code: str) -> ExecResult:
        inst = self._resolve(sandbox)
        parts = code.strip().split(maxsplit=2)
        if not parts:
            return ExecResult(exit_code=0, stdout="")
        op = parts[0]
        if op == "echo":
            return ExecResult(exit_code=0, stdout=parts[1] if len(parts) > 1 else "")
        if op == "write":
            if len(parts) < 3:
                return ExecResult(exit_code=2, stdout="", stderr="usage: write <path> <text>")
            inst.filesystem[parts[1]] = parts[2]
            return ExecResult(exit_code=0, stdout="")
        if op == "read":
            if len(parts) < 2:
                return ExecResult(exit_code=2, stdout="", stderr="usage: read <path>")
            path = parts[1]
            if path not in inst.filesystem:
                return ExecResult(exit_code=1, stdout="", stderr=f"{path}: No such file")
            return ExecResult(exit_code=0, stdout=inst.filesystem[path])
        if op == "setenv":
            if len(parts) < 3:
                return ExecResult(exit_code=2, stdout="", stderr="usage: setenv <key> <val>")
            inst.env[parts[1]] = parts[2]
            return ExecResult(exit_code=0, stdout="")
        if op == "getenv":
            if len(parts) < 2:
                return ExecResult(exit_code=2, stdout="", stderr="usage: getenv <key>")
            key = parts[1]
            if key not in inst.env:
                return ExecResult(exit_code=1, stdout="", stderr=f"{key}: unset")
            return ExecResult(exit_code=0, stdout=inst.env[key])
        return ExecResult(exit_code=127, stdout="", stderr=f"unknown op: {op}")

    def destroy(self, sandbox: Sandbox) -> None:
        inst = self._instances.get(sandbox.sandbox_id)
        if inst is None or not inst.sandbox.alive:
            return  # idempotent
        inst.sandbox.alive = False
        # Wipe the private namespace so nothing survives teardown.
        inst.filesystem.clear()
        inst.env.clear()
        self.destroyed_ids.append(sandbox.sandbox_id)


# ---------------------------------------------------------------------------
# Lifecycle manager
# ---------------------------------------------------------------------------


def _monotonic_clock() -> float:
    import time

    return time.monotonic()


@dataclass
class TaskSandbox:
    """A task-bound sandbox handed out by :class:`SandboxManager`.

    Wraps a :class:`Sandbox` handle plus its provider so callers run code
    without re-passing the provider, and cannot address another task's sandbox.
    """

    task_id: str
    sandbox: Sandbox
    _provider: SandboxProvider

    def exec(self, code: str) -> ExecResult:
        return self._provider.exec(self.sandbox, code)

    @property
    def resource_spec(self) -> ResourceSpec:
        return self.sandbox.resource_spec


class SandboxManager:
    """Per-task sandbox lifecycle with guaranteed teardown.

    The manager is provider-agnostic (inject a real or fake provider) and
    clock-agnostic (inject a monotonic clock for deterministic timestamps).
    It gives:

    1. **Per-task isolation** -- :meth:`task_sandbox` creates one sandbox owned
       by exactly one ``task_id``; the provider enforces the namespace so task
       A cannot read task B's filesystem/env.
    2. **Resource limits** -- the :class:`ResourceSpec` passed to
       :meth:`task_sandbox` is forwarded to ``create`` and recorded on the
       sandbox.
    3. **Guaranteed teardown** -- :meth:`task_sandbox` is a context manager that
       destroys the sandbox in a ``finally`` block, so it is torn down on normal
       completion AND when the body (or ``exec``) raises. No leaked sandboxes.
    """

    def __init__(
        self,
        provider: SandboxProvider,
        *,
        clock: Callable[[], float] = _monotonic_clock,
    ) -> None:
        self._provider = provider
        self._clock = clock
        self._active: dict[str, Sandbox] = {}

    @property
    def active_tasks(self) -> list[str]:
        """Task ids that currently hold a live sandbox through this manager."""
        return list(self._active)

    @contextmanager
    def task_sandbox(self, task_id: str, spec: ResourceSpec | None = None) -> Iterator[TaskSandbox]:
        """Create an isolated sandbox for ``task_id`` and guarantee teardown.

        Args:
            task_id: The owning task. One live sandbox per task at a time.
            spec: Resource limits; defaults to a conservative
                network-isolated :class:`ResourceSpec`.

        Yields:
            A :class:`TaskSandbox` bound to the new sandbox.

        Raises:
            SandboxError: If ``task_id`` already holds a live sandbox.
        """
        if task_id in self._active:
            raise SandboxError(f"task {task_id!r} already has an active sandbox")
        resource_spec = spec if spec is not None else ResourceSpec()
        sandbox = self._provider.create(task_id, resource_spec, created_at=self._clock())
        self._active[task_id] = sandbox
        try:
            yield TaskSandbox(task_id=task_id, sandbox=sandbox, _provider=self._provider)
        finally:
            # Guaranteed teardown: runs on success AND on any exception raised
            # inside the with-body (including exec failures).
            self._provider.destroy(sandbox)
            self._active.pop(task_id, None)

    def run(self, task_id: str, code: str, spec: ResourceSpec | None = None) -> ExecResult:
        """Convenience: create a sandbox, run ``code`` once, tear down.

        The sandbox is always destroyed, even if ``exec`` raises.
        """
        with self.task_sandbox(task_id, spec) as box:
            return box.exec(code)
