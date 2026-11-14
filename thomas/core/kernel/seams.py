"""The seams: what a provider must offer, and what a consumer may assume.

Phase 3.2 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

A seam is three roles — a definition, a provider, and a consumer. This module
holds the *definitions* only, which is why it imports nothing: the providers
live in ``thomas/agent/kernel_wiring.py``, where depending on ``tools`` and
``core`` is already permitted by ``thomas/_architecture.py``. Putting them here
would add a ``core -> tools`` import, the inversion the architecture already
carries as debt and asks nobody to deepen.

Two failure shapes this module exists to prevent:

- **Two names for one thing.** Thomas has a recurring bug where one reader asks
  for a catalog root and another walks project roots, and the empty answer reads
  as clean. Service names are constants here so a typo is an ImportError rather
  than a silently absent service.
- **A consumer that gets something almost right.** ``require()`` resolves a seam
  and checks it structurally, so a provider missing a method fails where it is
  registered rather than deep inside a turn.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable

# -- canonical service names -------------------------------------------------
# The only spellings. Consumers import these; nobody types the string.

TOOLS = "tools"
LLM = "llm"
SESSIONS = "sessions"
RUNS = "runs"
AGENT_LOOP = "agent_loop"
FS = "fs"
SANDBOX = "sandbox"

#: Every seam the kernel knows how to describe, in report order.
SEAMS: tuple[str, ...] = (TOOLS, LLM, SESSIONS, RUNS, AGENT_LOOP, FS, SANDBOX)

# -- named calls (thomas.core.kernel.late) -----------------------------------
# The tools a run gets from its config: the server shell provides them, a worker asks.
TOOL_SET = "tool_set"
# Mirror a handed-in change's cards into the chat that asked: self-change provides it, chat asks.
FOLLOW_SELF_CHANGE = "follow_self_change"
# One pass of the self-project queue: self-change's routes provide it, the park loop asks.
PROJECT_QUEUE_TICK = "project_queue_tick"
# Start or steer delegated work: chat provides them, Slack and Work ask.
START_DELEGATION = "start_delegation"
STEER_DELEGATION = "steer_delegation"
# A delegation's record as a reader gets it: chat provides it, Work asks.
DELEGATION_RECORD = "delegation_record"
# The chat's settings in Build's words: chat provides them, the ratchet asks.
BUILD_SETTINGS = "build_settings"
# A chat follows its project again after a restart: chat provides it, self-change asks.
FOLLOW_AFTER_RESTART = "follow_after_restart"

#: Every named call, each with exactly one provider.
CALLS: tuple[str, ...] = (
    TOOL_SET,
    FOLLOW_SELF_CHANGE,
    PROJECT_QUEUE_TICK,
    START_DELEGATION,
    STEER_DELEGATION,
    DELEGATION_RECORD,
    BUILD_SETTINGS,
    FOLLOW_AFTER_RESTART,
)


# -- structural contracts ----------------------------------------------------
# Deliberately minimal: each lists what a *consumer* actually calls, not
# everything today's implementation happens to expose. A wider protocol would
# make a legitimate alternative provider impossible to write.


@runtime_checkable
class ToolsSeam(Protocol):
    """Tool lookup and execution. Satisfied today by ``thomas.tools.ToolRegistry``."""

    def get(self, name: str) -> Any | None: ...

    def list_tools(self, category: str | None = None) -> list[Any]: ...

    async def execute(self, name: str, args: Mapping[str, Any]) -> Any: ...


@runtime_checkable
class LLMSeam(Protocol):
    """Hands out model clients. As with AGENT_LOOP the seam is the factory: a client is built per model config.

    Satisfied by ``thomas.core.llm_slot.Models``. What a client offers is ``llm_slot.ModelClient``.
    """

    def open(self, config: Any, /, *, default: Any = None, **options: Any) -> Any: ...

    def profile(self, app_config: Any, name: str | None = None, /, *, default: Any = None, **options: Any) -> Any: ...

    def adapter(self, provider: str, stream: Callable[..., Any]) -> Callable[[], None]: ...


@runtime_checkable
class SessionsSeam(Protocol):
    """Gives out stores. The seam is the factory, because a store belongs to a folder.

    Satisfied by ``thomas.chat.session_slot.Sessions``.
    """

    def store(self, root: Any, *, surface: str = "chat") -> Any: ...


@runtime_checkable
class SessionStoreSeam(Protocol):
    """What a store offers. Satisfied by ``thomas.chat.session_store.SessionStore``.

    ``load`` raises when a file is there and cannot be read: that is never the same answer as no session. ``lock``,
    ``path_of`` and ``files`` leak the file layout, which is accepted because Thomas has one backend.
    """

    async def load(self, session_id: str) -> Any | None: ...

    async def load_meta(self, session_id: str) -> Any | None: ...

    async def save(self, session_id: str, conversation: Any, meta: Any = None, *, force: bool = False) -> bool: ...

    async def delete(self, session_id: str) -> bool: ...

    async def list_sessions(self) -> list[str]: ...

    def lock(self, session_id: str) -> Any: ...

    def path_of(self, session_id: str) -> Any: ...

    def files(self) -> list[Any]: ...


@runtime_checkable
class RunsSeam(Protocol):
    """The append-only run log the honesty spine writes.

    Satisfied today by the ``thomas.marketplace.observability.run_store`` module itself.
    """

    def create_run(self, metadata: Any) -> str: ...

    def append_event(self, run_id: str, event_type: str, payload: Any, t_ms: int, seq: int) -> None: ...

    def finalize_run(self, run_id: str, *args: Any, **kwargs: Any) -> Any: ...

    def stream_replay(self, run_id: str) -> Any: ...


@runtime_checkable
class AgentLoopSeam(Protocol):
    """A driver that turns a request into a stream of events.

    The seam is the *factory*, not the loop: consumers ask for a loop built for
    their config rather than importing ``AgentLoop`` and constructing it, which
    is what ten call sites do today.
    """

    def build(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class FsSeam(Protocol):
    """Hands out path scopes. The seam is the factory, because a scope belongs to a root.

    Satisfied by ``thomas.tools.fs_scope.Scopes``. A scope decides what a root lets through; it opens nothing.
    """

    def scope(self, root: Any, /) -> Any: ...


@runtime_checkable
class SandboxSeam(Protocol):
    """Says how a command is run: ``disabled``, ``caged``, ``refused`` or ``local``. It runs nothing.

    Satisfied by ``thomas.tools.sandbox_slot.Sandbox``. A host with no sandbox provides none, and a consumer then
    refuses the command; it never reads an absent sandbox as ``local``.
    """

    def rung(self, *, allowed: bool = True) -> str: ...


# -- resolution --------------------------------------------------------------


class SeamViolation(TypeError):
    """A provider was registered that does not satisfy its seam."""


def require(ctx: Any, name: str, protocol: type | None = None) -> Any:
    """Resolve a seam, checking the provider structurally.

    Raises ``ServiceNotFound`` when nobody provides it and ``SeamViolation``
    when somebody provides the wrong shape — both at the point of use, with the
    seam named, rather than as an attribute error several frames down.
    """
    provider = ctx[name]
    if protocol is not None and not isinstance(provider, protocol):
        missing = [attr for attr in getattr(protocol, "__protocol_attrs__", ()) if not hasattr(provider, attr)]
        raise SeamViolation(
            f"provider for seam {name!r} ({type(provider).__name__}) does not satisfy "
            f"{protocol.__name__}; missing: {', '.join(sorted(missing)) or 'unknown'}"
        )
    return provider


def seam_report(kernel: Any) -> dict[str, Any]:
    """Which seams are filled, and who is still waiting on what.

    The point of the kernel is that absence is visible. This is the surface a
    boot check or a status route reads to say so out loud instead of letting an
    unfilled seam pass for a working one.

    ``root_effects`` is the root scope's undo count. Hot swap mounts and unmounts
    while Thomas runs, so a number that climbs with every reload is the signature
    of teardown that does not put everything back; printing it turns that from
    something you measure by hand into something the status route says.
    """
    root = kernel.root
    filled = {name: root.has(name) for name in SEAMS}
    pending = [{"plugin": fork.name, "missing": list(fork.missing)} for fork in kernel.pending()]
    return {
        "seams": filled,
        "unfilled": [name for name, ok in filled.items() if not ok],
        "pending_plugins": pending,
        "mounted": [fork.name for fork in kernel.mounted()],
        "root_effects": root.pending_effects,
    }
