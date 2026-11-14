"""The agent loop becomes replaceable without changing the callers.

Phase 3.2 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

Ten sites construct ``AgentLoop(...)`` directly today, so nothing can substitute
a different driver — not a test double, not a remote runner, not an instrumented
loop. These tests pin the replacement and, just as importantly, that the default
path still hands back exactly what the constructor would have.
"""

from __future__ import annotations

import pytest

from thomas.agent.kernel_wiring import (
    AgentLoopFactory,
    build_agent_loop,
    default_kernel,
    get_kernel,
    set_kernel,
)
from thomas.core.kernel import AGENT_LOOP, TOOLS, seam_report


@pytest.fixture(autouse=True)
def _isolate_process_kernel():
    """Never let one test's kernel leak into the next, or into a real run."""
    set_kernel(None)
    yield
    set_kernel(None)


class _FakeLoop:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


class _RecordingFactory:
    name = "recording-loop"

    def __init__(self) -> None:
        self.builds: list[tuple] = []
        self.defaults: list = []

    def build(self, *args, default=None, **kwargs):
        # A registered provider is free to ignore ``default`` entirely — that is
        # what overriding the seam means. It is recorded here, not forwarded.
        self.defaults.append(default)
        self.builds.append((args, kwargs))
        return _FakeLoop(*args, **kwargs)


def test_a_registered_factory_replaces_the_constructor() -> None:
    factory = _RecordingFactory()
    kernel = default_kernel(loop_factory=factory)

    loop = build_agent_loop("CONFIG", "LLM", "TOOLS", thread_id="t1", ctx=kernel.root)

    assert isinstance(loop, _FakeLoop)
    assert factory.builds == [(("CONFIG", "LLM", "TOOLS"), {"thread_id": "t1"})]


def test_every_argument_reaches_the_factory_untouched() -> None:
    """The ten call sites pass different kwargs; none may be dropped in transit."""
    factory = _RecordingFactory()
    kernel = default_kernel(loop_factory=factory)

    build_agent_loop(
        "CONFIG",
        "LLM",
        "TOOLS",
        system_prompt="be brief",
        autonomy_level=1,
        max_parallel_tools=3,
        non_coder_profile=True,
        ctx=kernel.root,
    )

    args, kwargs = factory.builds[0]
    assert args == ("CONFIG", "LLM", "TOOLS")
    assert kwargs == {
        "system_prompt": "be brief",
        "autonomy_level": 1,
        "max_parallel_tools": 3,
        "non_coder_profile": True,
    }


def test_the_default_kernel_fills_the_agent_loop_seam() -> None:
    kernel = default_kernel()
    assert kernel.root.has(AGENT_LOOP)
    assert isinstance(kernel.root[AGENT_LOOP], AgentLoopFactory)
    assert AGENT_LOOP not in seam_report(kernel)["unfilled"]


def test_the_process_kernel_is_created_once_and_is_usable() -> None:
    first = get_kernel()
    second = get_kernel()
    assert first is second
    assert first.root.has(AGENT_LOOP)


def test_a_plugin_can_take_over_the_loop_seam_and_give_it_back() -> None:
    """The whole point: swap the driver, then unwind cleanly."""
    kernel = default_kernel()
    original = kernel.root[AGENT_LOOP]
    factory = _RecordingFactory()

    class LoopOverride:
        name = "loop-override"
        inject = (AGENT_LOOP,)

        def apply(self, ctx, config) -> None:
            ctx.set(AGENT_LOOP, factory)

    fork = kernel.mount(LoopOverride())
    assert kernel.root[AGENT_LOOP] is factory
    assert isinstance(build_agent_loop("C", "L", "T", ctx=kernel.root), _FakeLoop)

    fork.dispose()

    assert kernel.root[AGENT_LOOP] is original


def test_optional_seams_are_registered_when_a_host_has_them() -> None:
    kernel = default_kernel(tools="REGISTRY", llm="CLIENT")
    report = seam_report(kernel)
    assert kernel.root[TOOLS] == "REGISTRY"
    assert report["unfilled"] == ["sessions", "runs"]


def test_the_default_factory_constructs_the_real_agent_loop(monkeypatch) -> None:
    """Guards the passthrough.

    The seam could look healthy while the default provider quietly built the
    wrong object — a proxy passing for the real thing, a shape this repo has hit
    before. This pins that the default targets ``thomas.agent.loop.AgentLoop``
    and forwards every argument to it.
    """
    import thomas.agent.loop as loop_module

    seen: dict = {}

    class Sentinel:
        def __init__(self, *args, **kwargs) -> None:
            seen["args"] = args
            seen["kwargs"] = kwargs

    monkeypatch.setattr(loop_module, "AgentLoop", Sentinel)

    built = AgentLoopFactory().build("CONFIG", "LLM", "TOOLS", thread_id="t9")

    assert isinstance(built, Sentinel)
    assert seen == {"args": ("CONFIG", "LLM", "TOOLS"), "kwargs": {"thread_id": "t9"}}


def test_the_default_factory_honours_the_class_the_call_site_names() -> None:
    """The compatibility path that keeps a dozen existing tests working.

    Call sites pass ``default=AgentLoop`` — their own module-level name — so the
    long-standing practice of substituting a fake with
    ``monkeypatch.setattr(worker_runtime, "AgentLoop", Fake)`` still governs the
    default path. Removing this silently broke five test files the first time.
    """
    seen: dict = {}

    class CallerLocalLoop:
        def __init__(self, *args, **kwargs) -> None:
            seen["args"] = args
            seen["kwargs"] = kwargs

    built = AgentLoopFactory().build("C", "L", "T", default=CallerLocalLoop, run_id="r1")

    assert isinstance(built, CallerLocalLoop)
    assert seen == {"args": ("C", "L", "T"), "kwargs": {"run_id": "r1"}}


def test_a_registered_provider_outranks_the_call_sites_default() -> None:
    """Both mechanisms stack, and the registered one wins."""
    factory = _RecordingFactory()
    kernel = default_kernel(loop_factory=factory)

    class NeverBuilt:
        def __init__(self, *args, **kwargs) -> None:  # pragma: no cover
            raise AssertionError("the registered provider should have won")

    loop = build_agent_loop("C", "L", "T", default=NeverBuilt, ctx=kernel.root)

    assert isinstance(loop, _FakeLoop)
    assert factory.defaults == [NeverBuilt]


def test_the_files_slot_is_on_the_default_kernel() -> None:
    from thomas.core.kernel import FS, FsSeam
    from thomas.tools.fs_scope import scopes

    kernel = default_kernel()
    assert kernel.root[FS] is scopes()
    assert isinstance(kernel.root[FS], FsSeam)
    assert default_kernel(fs="SCOPES").root[FS] == "SCOPES"


def test_the_sandbox_slot_is_on_the_default_kernel() -> None:
    from thomas.core.kernel import SANDBOX, SandboxSeam
    from thomas.tools.sandbox_slot import sandbox

    kernel = default_kernel()
    assert kernel.root[SANDBOX] is sandbox()
    assert isinstance(kernel.root[SANDBOX], SandboxSeam)
    assert default_kernel(sandbox_slot="BOX").root[SANDBOX] == "BOX"
    assert "sandbox" not in seam_report(kernel)["unfilled"]
