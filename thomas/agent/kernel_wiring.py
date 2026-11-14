"""Where Thomas's real implementations become kernel services.

Phase 3.2 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

The kernel deliberately imports no concrete Thomas providers. This module is the
other half of the seams in use: it registers concrete providers. It lives
under ``thomas/agent/`` because ``thomas/_architecture.py`` already allows
``agent -> tools`` and ``agent -> core``; putting it in ``core`` would add a
``core -> tools`` import, which the architecture carries as debt and asks nobody
to deepen.

**Why a factory rather than the loop itself.** Ten call sites construct
``AgentLoop(config, llm, tools, ...)`` directly today, each with a different set
of keyword arguments. A seam holding a *live loop* would have to be built before
anyone knew those arguments. So the seam holds something that can build one, and
``build_agent_loop`` is what the call sites use instead of the constructor. The
default loop provider passes constructor arguments through; the tools seam can
replace or augment the registry supplied for a turn.

**Why a process-wide kernel.** Those loop call sites live in the server, the CLI,
the forge and an integration; threading a kernel through all of them would be a
much larger change than this phase should make. ``get_kernel()`` is the
composition root, created on first use with the default providers already
registered. Tests and alternate hosts build their own with ``default_kernel()``.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from thomas.core.kernel import AGENT_LOOP, FS, LLM, SANDBOX, TOOLS, Context, Kernel, require
from thomas.core.kernel.seams import AgentLoopSeam, FsSeam, LLMSeam, SandboxSeam, ToolsSeam
from thomas.core.llm_slot import models
from thomas.tools.base import Tool, ToolResult
from thomas.tools.fs_scope import scopes
from thomas.tools.sandbox_slot import sandbox

log = logging.getLogger(__name__)

_kernel_lock = threading.Lock()
_kernel: Kernel | None = None

#: The service name of the ledger of tools rows lend to runs. Kept here, not in the seams, because only this file reads it.
LENT_TOOLS = "lent_tools"


class AgentLoopFactory:
    """The default provider for the ``agent_loop`` seam.

    Passes every argument through untouched to ``default`` — the class the call
    site itself names — falling back to ``thomas.agent.loop.AgentLoop``.

    ``default`` exists for a specific reason. Before the seam, call sites built
    ``AgentLoop`` directly, and a dozen tests substituted a fake by patching the
    module's re-exported name (``monkeypatch.setattr(worker_runtime,
    "AgentLoop", Fake)``) — a homemade seam. Honouring the caller's class keeps
    every one of those working, while a *registered* provider still overrides
    the whole thing. The two mechanisms stack instead of competing.

    Importing inside ``build`` keeps this module cheap and avoids a cycle: the
    loop package may itself want the kernel.
    """

    name = "default-agent-loop"

    def build(self, *args: Any, default: Any = None, **kwargs: Any) -> Any:
        target = default
        if target is None:
            from thomas.agent.loop import AgentLoop

            target = AgentLoop
        return target(*args, **kwargs)


def require_models() -> LLMSeam:
    """The models slot, checked against its seam where it is registered rather than inside a turn."""
    slot = models()
    if not isinstance(slot, LLMSeam):
        raise TypeError("thomas.core.llm_slot.models() does not satisfy LLMSeam")
    return slot


def require_fs() -> FsSeam:
    """The files slot, checked against its seam where it is registered rather than inside a turn."""
    slot = scopes()
    if not isinstance(slot, FsSeam):
        raise TypeError("thomas.tools.fs_scope.scopes() does not satisfy FsSeam")
    return slot


def require_sandbox() -> SandboxSeam:
    """The sandbox slot, checked against its seam where it is registered rather than inside a turn."""
    slot = sandbox()
    if not isinstance(slot, SandboxSeam):
        raise TypeError("thomas.tools.sandbox_slot.sandbox() does not satisfy SandboxSeam")
    return slot


def default_kernel(
    *,
    tools: Any | None = None,
    llm: Any | None = None,
    fs: Any | None = None,
    sandbox_slot: Any | None = None,
    loop_factory: Any | None = None,
) -> Kernel:
    """A kernel with Thomas's default providers registered.

    The agent-loop, models, files and sandbox seams are filled unconditionally: models is the
    process-wide ``thomas.core.llm_slot.models()``, which a host may replace by
    passing ``llm``. ``tools`` is registered when a host actually has it. The
    server registers a tools provider at startup, and an unfilled seam remains
    visible via ``seam_report``.
    """
    kernel = Kernel()
    kernel.root.set(AGENT_LOOP, loop_factory or AgentLoopFactory())
    if tools is not None:
        kernel.root.set(TOOLS, tools)
    kernel.root.set(FS, fs if fs is not None else require_fs())
    kernel.root.set(LLM, llm if llm is not None else require_models())
    kernel.root.set(SANDBOX, sandbox_slot if sandbox_slot is not None else require_sandbox())
    return kernel


def get_kernel() -> Kernel:
    """The process-wide kernel, created on first use."""
    global _kernel
    if _kernel is None:
        with _kernel_lock:
            if _kernel is None:
                _kernel = default_kernel()
    return _kernel


def set_kernel(kernel: Kernel | None) -> None:
    """Replace the process-wide kernel. For hosts and tests, not for turns."""
    global _kernel
    with _kernel_lock:
        _kernel = kernel


def register_tools_provider(tools: ToolsSeam, *, ctx: Context | None = None) -> Any:
    """Register the server's registry while retaining per-turn tool sets."""
    from thomas.agent.kernel_tool_provider import DefaultTools

    scope = ctx if ctx is not None else get_kernel().root
    return scope.set(TOOLS, DefaultTools(tools))


def resolve_tools_for_turn(base: Any, *, ctx: Context | None = None, allow_new: bool = False) -> Any:
    """Resolve a turn's tools; opt in to non-server registries before filtering."""
    scope = ctx if ctx is not None else get_kernel().root
    if not scope.has(TOOLS):
        return base
    provider = require(scope, TOOLS, ToolsSeam)
    if allow_new:
        from thomas.agent.kernel_tool_provider import MountedTools

        if isinstance(provider, MountedTools):
            return provider.for_turn(base, allow_new=True)
    return provider.for_turn(base) if hasattr(provider, "for_turn") else provider


def build_agent_loop(
    *args: Any,
    ctx: Context | None = None,
    default: Any = None,
    **kwargs: Any,
) -> Any:
    """Build an agent loop through the seam instead of the constructor.

    Drop-in for ``AgentLoop(...)``: same arguments, except that the constructor
    and the tools passed to it can be replaced through their kernel seams.

    Call sites pass ``default=AgentLoop`` — their own module-level name — so the
    default provider builds exactly what they used to, and the long-standing
    practice of substituting a fake by patching that name keeps working.
    """
    scope = ctx if ctx is not None else get_kernel().root
    factory = require(scope, AGENT_LOOP, AgentLoopSeam)
    # Resolve on every construction; restricted registries retain their boundary.
    if len(args) >= 3 or "tools" in kwargs:
        base = args[2] if len(args) >= 3 else kwargs["tools"]
        tools = resolve_tools_for_turn(base, ctx=scope)
        if len(args) >= 3:
            args = (*args[:2], tools, *args[3:])
        else:
            kwargs["tools"] = tools
    return factory.build(*args, default=default, **kwargs)


class _Lending:
    """One row's loan of tools. ``active`` goes false the moment the row stops, and never true again."""

    def __init__(self, owner: str, tools: tuple[Tool, ...]) -> None:
        self.owner = owner
        self.tools = tools
        self.active = True


class LentTool(Tool):
    """A row's tool as a run holds it: it answers while the row runs and refuses once the row has stopped.

    A run keeps the registry it was built with, so a tool a row lent is still in a registry after the row stops. This
    wrapper is what makes it stop answering there. It refuses a call and runs nothing; a call already running is not cut.
    """

    def __init__(self, tool: Tool, lending: _Lending) -> None:
        self.inner = tool
        self.lending = lending
        self.name = tool.name
        self.category = tool.category
        self.description = tool.description
        self.parameters = tool.parameters

    def __getattr__(self, attr: str) -> Any:
        """Any other attribute the loop reads off a tool (such as optional_empty_path_keys) is the inner tool's."""
        if attr in ("inner", "lending") or attr.startswith("__"):
            raise AttributeError(attr)
        return getattr(self.inner, attr)

    def _refusal(self) -> ToolResult:
        return ToolResult(ok=False, error=f"{self.name} is not available: {self.lending.owner} is turned off")

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        if not self.lending.active:
            return self._refusal()
        return await self.inner.execute(args)

    async def safe_execute(self, args: dict[str, Any]) -> ToolResult:
        if not self.lending.active:
            return self._refusal()
        return await self.inner.safe_execute(args)


class _LentLedger:
    """Every lending that is live, in the order the rows turned on."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lendings: list[_Lending] = []

    def add(self, lending: _Lending) -> None:
        with self._lock:
            held = {tool.name: other.owner for other in self._lendings for tool in other.tools}
            for tool in lending.tools:
                if tool.name in held:
                    raise ValueError(f"{lending.owner} cannot lend {tool.name!r}: {held[tool.name]} already lends it")
            self._lendings.append(lending)

    def withdraw(self, lending: _Lending) -> None:
        with self._lock:
            lending.active = False
            if lending in self._lendings:
                self._lendings.remove(lending)

    def tools(self) -> list[Tool]:
        with self._lock:
            return [LentTool(tool, lending) for lending in self._lendings for tool in lending.tools]

    def __len__(self) -> int:
        with self._lock:
            return len(self._lendings)


def _ledger_for(ctx: Context, *, create: bool) -> _LentLedger | None:
    root = ctx.kernel.root
    with _kernel_lock:
        if root.has(LENT_TOOLS):
            return root.get(LENT_TOOLS)
        if not create:
            return None
        ledger = _LentLedger()
        root.set(LENT_TOOLS, ledger)
        return ledger


def contribute_tools(ctx: Context, tools: Any, *, owner: str) -> Any:
    """Lend ``tools`` to the runs built from now on, until ``ctx`` is disposed. A row calls this in ``apply``.

    Nothing is added to a registry already built: a run asks ``contributed_tools`` when it is built. Stopping the row
    ends the loan, and the tools a run already holds refuse from then on. A name another row lends, or that is not a
    ``Tool`` with a name, raises here so the row reads failed. Returns the call that ends the loan early.
    """
    held = tuple(tools)
    for tool in held:
        if not isinstance(tool, Tool):
            raise TypeError(f"{owner} lent something that is not a Tool: {type(tool).__name__}")
        if not isinstance(tool.name, str) or not tool.name.strip():
            raise ValueError(f"{owner} lent a tool without a name")
    if len({tool.name for tool in held}) != len(held):
        raise ValueError(f"{owner} lent two tools with one name")
    ledger = _ledger_for(ctx, create=True)
    lending = _Lending(owner, held)
    ledger.add(lending)
    return ctx.effect(lambda: ledger.withdraw(lending))


def contributed_tools(ctx: Context | None = None) -> list[Tool]:
    """The tools rows lend right now, each wrapped so it refuses after its row stops. Empty when no row lends."""
    scope = ctx if ctx is not None else get_kernel().root
    ledger = _ledger_for(scope, create=False)
    return ledger.tools() if ledger is not None else []
