"""CAP-060 L2: run code in an isolated per-task sandbox with resource limits
and guaranteed teardown.

Proves, against the hermetic :class:`FakeSandboxProvider` (no daemon, no
network, injected clock):

- A per-task sandbox is created with the resource-limit spec recorded on it.
- Code executed inside the sandbox runs and returns output.
- Per-task ISOLATION: task A cannot read task B's sandbox filesystem/env, and a
  foreign/forged handle is rejected.
- GUARANTEED TEARDOWN: the sandbox is destroyed on normal completion AND when
  ``exec`` raises inside the context manager -- the fake reports zero live
  sandboxes afterward (no leak).
- DETERMINISM: an injected clock produces reproducible creation timestamps.
"""

from __future__ import annotations

import itertools

import pytest

from thomas.tools.sandbox_runtime import (
    ExecResult,
    FakeSandboxProvider,
    ResourceSpec,
    Sandbox,
    SandboxError,
    SandboxManager,
    SubprocessSandboxProvider,
)


def _fixed_clock(start: int = 1000, step: int = 5):
    """A deterministic monotonic clock: 1000, 1005, 1010, ..."""
    counter = itertools.count(start, step)
    return lambda: float(next(counter))


def test_per_task_sandbox_created_with_resource_spec_recorded() -> None:
    provider = FakeSandboxProvider()
    manager = SandboxManager(provider, clock=_fixed_clock())
    spec = ResourceSpec(cpus=2.0, memory_mb=256, disk_mb=512, network="none")

    with manager.task_sandbox("task-A", spec) as box:
        assert isinstance(box.sandbox, Sandbox)
        assert box.task_id == "task-A"
        assert box.sandbox.task_id == "task-A"
        # Resource limits are recorded on the sandbox handle.
        assert box.resource_spec is spec
        assert box.sandbox.resource_spec.cpus == 2.0
        assert box.sandbox.resource_spec.memory_mb == 256
        assert box.sandbox.resource_spec.network == "none"
        # The spec limits are visible from inside the sandbox env, too.
        assert box.exec("getenv THOMAS_CPUS").stdout == "2.0"
        assert box.exec("getenv THOMAS_MEMORY_MB").stdout == "256"


def test_code_runs_in_sandbox_and_returns_output() -> None:
    provider = FakeSandboxProvider()
    manager = SandboxManager(provider, clock=_fixed_clock())

    with manager.task_sandbox("task-A") as box:
        result = box.exec("echo hello-from-sandbox")
        assert isinstance(result, ExecResult)
        assert result.ok
        assert result.exit_code == 0
        assert result.stdout == "hello-from-sandbox"

    # Convenience one-shot run also returns output and tears down.
    out = manager.run("task-solo", "echo one-shot")
    assert out.stdout == "one-shot"
    assert provider.live_count == 0


def test_isolation_task_a_cannot_read_task_b_filesystem() -> None:
    provider = FakeSandboxProvider()
    manager = SandboxManager(provider, clock=_fixed_clock())

    # Task A writes a secret into its OWN sandbox filesystem.
    with manager.task_sandbox("task-A") as box_a:
        assert box_a.exec("write /data/secret alpha-secret").ok
        assert box_a.exec("read /data/secret").stdout == "alpha-secret"

        # While A is live, B runs concurrently in a separate sandbox and cannot
        # see A's file -- separate namespaces, no shared store.
        with manager.task_sandbox("task-B") as box_b:
            missing = box_b.exec("read /data/secret")
            assert not missing.ok
            assert missing.exit_code == 1
            # B's own writes stay in B and never appear in A.
            assert box_b.exec("write /data/secret beta-secret").ok
            assert box_b.exec("read /data/secret").stdout == "beta-secret"
        # A still sees only its own value; B's write did not leak in.
        assert box_a.exec("read /data/secret").stdout == "alpha-secret"


def test_isolation_foreign_handle_is_rejected() -> None:
    provider = FakeSandboxProvider()
    manager = SandboxManager(provider, clock=_fixed_clock())

    with manager.task_sandbox("task-A") as box_a:
        real = box_a.sandbox
        # A forged handle that reuses A's id but is a different object (as a
        # different task might construct) cannot address A's namespace.
        forged = Sandbox(
            sandbox_id=real.sandbox_id,
            task_id="task-B",
            resource_spec=real.resource_spec,
            created_at=real.created_at,
        )
        with pytest.raises(SandboxError, match="handle mismatch"):
            provider.exec(forged, "read /data/secret")

    # A totally unknown sandbox id is rejected as well.
    unknown = Sandbox("no-such-id", "task-Z", ResourceSpec(), created_at=0.0)
    with pytest.raises(SandboxError, match="foreign or never created"):
        provider.exec(unknown, "echo hi")


def test_teardown_guaranteed_on_normal_completion() -> None:
    provider = FakeSandboxProvider()
    manager = SandboxManager(provider, clock=_fixed_clock())

    with manager.task_sandbox("task-A") as box:
        sandbox_id = box.sandbox.sandbox_id
        assert provider.live_count == 1

    # Destroyed on the normal exit of the context manager.
    assert provider.live_count == 0
    assert provider.live_ids() == []
    assert sandbox_id in provider.destroyed_ids
    assert manager.active_tasks == []


def test_teardown_guaranteed_when_exec_raises() -> None:
    provider = FakeSandboxProvider()
    manager = SandboxManager(provider, clock=_fixed_clock())

    class BoomError(RuntimeError):
        pass

    with pytest.raises(BoomError):
        with manager.task_sandbox("task-A") as box:
            assert provider.live_count == 1
            box.exec("write /data/x 1")
            raise BoomError("work blew up mid-task")

    # Even though the body raised, the sandbox was still destroyed: zero leaks.
    assert provider.live_count == 0
    assert provider.live_ids() == []
    assert manager.active_tasks == []
    # A subsequent task can reuse the same task id (the old sandbox is gone).
    with manager.task_sandbox("task-A") as box2:
        assert box2.exec("read /data/x").exit_code == 1  # fresh namespace


def test_run_convenience_tears_down_even_on_exec_error() -> None:
    provider = FakeSandboxProvider()
    manager = SandboxManager(provider, clock=_fixed_clock())

    # An unknown op returns rc=127 (does not raise), still must tear down.
    result = manager.run("task-A", "definitely-not-an-op")
    assert result.exit_code == 127
    assert provider.live_count == 0


def test_duplicate_active_task_is_rejected() -> None:
    provider = FakeSandboxProvider()
    manager = SandboxManager(provider, clock=_fixed_clock())

    with manager.task_sandbox("task-A"):
        with pytest.raises(SandboxError, match="already has an active sandbox"):
            with manager.task_sandbox("task-A"):
                pass
    # After the outer context exits, the task id frees up again.
    assert manager.active_tasks == []


def test_determinism_injected_clock_records_reproducible_timestamps() -> None:
    def build_timestamps() -> list[float]:
        provider = FakeSandboxProvider()
        manager = SandboxManager(provider, clock=_fixed_clock(start=1000, step=5))
        stamps: list[float] = []
        for name in ("t1", "t2", "t3"):
            with manager.task_sandbox(name) as box:
                stamps.append(box.sandbox.created_at)
        return stamps

    first = build_timestamps()
    second = build_timestamps()
    assert first == [1000.0, 1005.0, 1010.0]
    assert first == second  # fully reproducible under the injected clock


def test_resource_spec_renders_container_flags() -> None:
    spec = ResourceSpec(cpus=1.5, memory_mb=1024, disk_mb=2048, network="none")
    flags = spec.docker_flags()
    assert "--cpus=1.5" in flags
    assert "--memory=1024m" in flags
    assert "--storage-opt=size=2048m" in flags
    assert "--network=none" in flags


def test_subprocess_provider_builds_isolated_run_argv_without_daemon() -> None:
    """Live-lane argv construction is verifiable with an injected runner.

    This does NOT touch a real container daemon: the runner is a stub. It only
    proves the real provider forwards the resource-limit flags and per-task
    isolation to the container runtime CLI.
    """
    calls: list[list[str]] = []

    def fake_runner(argv):
        import subprocess

        calls.append(argv)
        if argv[1] == "run":
            return subprocess.CompletedProcess(argv, 0, stdout="container123\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    provider = SubprocessSandboxProvider(runtime="docker", image="python:3.12-slim", runner=fake_runner)
    spec = ResourceSpec(cpus=2.0, memory_mb=256, disk_mb=512, network="none")
    sandbox = provider.create("task-A", spec, created_at=1.0)

    assert sandbox.sandbox_id == "container123"
    assert sandbox.resource_spec is spec
    run_argv = calls[0]
    assert run_argv[:3] == ["docker", "run", "-d"]
    assert "--cpus=2.0" in run_argv
    assert "--memory=256m" in run_argv
    assert "--network=none" in run_argv

    provider.exec(sandbox, "echo hi")
    assert calls[1][:2] == ["docker", "exec"]
    assert calls[1][2] == "container123"

    provider.destroy(sandbox)
    assert calls[2] == ["docker", "rm", "-f", "container123"]
    assert sandbox.alive is False
