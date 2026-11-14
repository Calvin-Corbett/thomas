"""The Thomas kernel — one host for every plugin surface.

Phase 3.2 of ``docs/superpowers/specs/2026-08-24-praxis-first-design.md``, which
recorded the ask that started it: "everything's a plug in, and that's Thomas...
but I didn't have it actually built correctly."

What this package provides, and what Thomas had instead:

- **Reversible registration.** Everything a plugin sets, subscribes, or forks
  unwinds on unmount. ``thomas/tools/registry.py`` is a dict whose
  ``unregister`` is a manual delete with no record of ownership.
- **Dependency gating.** A plugin declaring ``inject`` mounts only when those
  services exist, and is listed in ``kernel.pending()`` while they do not. The
  alternative — mounting anyway and quietly doing nothing — is the shape behind
  Thomas's recurring "correct mechanism with no consumer" defects.
- **Events that hand back results.** ``emit`` returns what handlers returned, so
  a hook can participate. Today's hooks discard return values, which is why 528
  extension packs return payloads nothing reads.

This module imports nothing else from Thomas. It is the bottom of the tree.

    from thomas.core.kernel import Kernel

    kernel = Kernel()
    kernel.root.set("tools", registry)

    class Metrics:
        name = "metrics"
        inject = ("tools",)

        def apply(self, ctx, config):
            ctx.on("tool/call", self._record)

    fork = kernel.mount(Metrics())
    fork.dispose()   # subscription gone, nothing left behind
"""

from __future__ import annotations

from thomas.core.kernel.context import (
    Context,
    ContextDisposed,
    DisposalStack,
    Disposer,
    EventBus,
    KernelError,
    ServiceNotFound,
)
from thomas.core.kernel.hotswap import (
    SelfStop,
    SwapError,
    Unplugged,
    refuse_self_stop,
    stop,
    stop_would_wait,
    swap,
    unplug,
)
from thomas.core.kernel.plugins import (
    Fork,
    Kernel,
    Plugin,
    plugin_inject,
    plugin_name,
)
from thomas.core.kernel.profiles import (
    Entry,
    MountedProfile,
    Profile,
    ProfileError,
    apply_profile,
)
from thomas.core.kernel.seams import (
    AGENT_LOOP,
    FS,
    LLM,
    RUNS,
    SANDBOX,
    SEAMS,
    SESSIONS,
    TOOLS,
    AgentLoopSeam,
    FsSeam,
    LLMSeam,
    RunsSeam,
    SandboxSeam,
    SeamViolation,
    SessionsSeam,
    SessionStoreSeam,
    ToolsSeam,
    require,
    seam_report,
)

__all__ = [
    "AGENT_LOOP",
    "FS",
    "LLM",
    "RUNS",
    "SANDBOX",
    "SEAMS",
    "SESSIONS",
    "TOOLS",
    "AgentLoopSeam",
    "Context",
    "ContextDisposed",
    "DisposalStack",
    "Disposer",
    "Entry",
    "EventBus",
    "Fork",
    "MountedProfile",
    "Profile",
    "ProfileError",
    "apply_profile",
    "Kernel",
    "KernelError",
    "FsSeam",
    "LLMSeam",
    "Plugin",
    "SeamViolation",
    "SelfStop",
    "ServiceNotFound",
    "RunsSeam",
    "SandboxSeam",
    "SessionsSeam",
    "SessionStoreSeam",
    "SwapError",
    "ToolsSeam",
    "Unplugged",
    "plugin_inject",
    "plugin_name",
    "refuse_self_stop",
    "require",
    "seam_report",
    "stop",
    "stop_would_wait",
    "swap",
    "unplug",
]
