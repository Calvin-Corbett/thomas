"""Phase 3.3 — the plugin systems move onto the kernel.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`. Phase 3.2 built the host;
this is the part that puts tenants in it.

**What the spec assumed, and what is actually there.** §3.2 says "remount the
four existing plugin systems onto one kernel". Reading them establishes that
they are not four peer runtimes:

- ``thomas/plugins`` (p097-p123) is the only one that dispatches at run time —
  it loads live instances and calls their hook methods. That one genuinely
  remounts. This module holds the adapter that makes one of those instances a
  kernel plugin; ``plugin_supervisor`` is what mounts them, and since 3.5 that is
  the only mount there is — a one-shot variant lived here until nothing in the
  running app called it.
- ``extensions/`` is a **catalog, not a runtime**. ``extension_catalog_runtime``
  checks that each pack's ``hooks.py`` *exists* and never imports it; no code
  path in the repository loads pack code at all. The 533 packs' ``before_tool``
  and ``after_tool`` have never been called once. That is recorded here and
  pinned by a test rather than quietly fixed by switching on 528 handlers that
  each stamp a constant into a dict.
- ``agent_plugins_*`` and ``desktop_plugins_*`` are **installers** — they place
  skills, register MCP servers, write registry rows and build surface URLs.
  They have no hook dispatch to move.

So the honest shape of 3.3 is: remount the one runtime, and make the other
three's real status legible instead of implied.

**Why mounting matters here.** Before this, every hook dispatch re-read the
manifest and rebuilt instances (``get_enabled_plugin_instances`` on each call).
Mounted, a plugin's hooks are kernel subscriptions: registered once, dispatched
by the bus, and removed exactly when the plugin unmounts. A plugin that
implements no hooks and no tools contributes neither hooks nor tools; a plugin
exposing ``get_tools`` contributes its tools until unmount.
"""

from __future__ import annotations

import logging
from typing import Any

from thomas.agent.hook_events import HookEvent, event_names_for
from thomas.agent.kernel_wiring import get_kernel
from thomas.core.kernel import Kernel

log = logging.getLogger(__name__)

#: Set while installed plugins are mounted on the kernel. The hook bridge reads
#: it to know the bus already carries them, so it must not ALSO run the legacy
#: per-call scan and fire every hook twice.
INSTALLED_PLUGINS_MOUNTED = "installed_plugins_mounted"

#: Every wire name the loop dispatches: canonical events plus the legacy aliases
#: shipped plugins subscribe to. Derived from the loop's own surface so the two
#: cannot drift apart.
ALL_HOOK_NAMES: tuple[str, ...] = tuple(dict.fromkeys(name for event in HookEvent for name in event_names_for(event)))

#: How loading or adapting third-party plugin code fails without it being a bug
#: in Thomas. Public because the supervisor mounts through the same adapter and
#: must treat the same failures the same way; two copies of this tuple would
#: drift into two different definitions of "a plugin that did not load".
PLUGIN_LOAD_ERRORS = (
    ImportError,
    AttributeError,
    KeyError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


class MountedLegacyPlugin:
    """A legacy plugin instance, wrapped as a kernel plugin.

    Hook lookup and calling conventions are delegated to the existing
    ``p108`` helpers, so a plugin that worked through ``run_hook`` behaves
    identically on the bus — including the four argument shapes ``_call_hook``
    tolerates.
    """

    inject: tuple[str, ...] = ()

    def __init__(self, instance: Any) -> None:
        from thomas.plugins.p108_plugin_hook_runner_core import _get_hook_callable, _plugin_id

        self.instance = instance
        self.name = str(_plugin_id(instance))
        self.hooks: tuple[str, ...] = tuple(
            name for name in ALL_HOOK_NAMES if _get_hook_callable(instance, name) is not None
        )

    def __repr__(self) -> str:
        return f"<MountedLegacyPlugin {self.name!r} hooks={len(self.hooks)}>"

    def apply(self, ctx: Any, config: Any) -> None:
        for hook_name in self.hooks:
            ctx.on(hook_name, self._handler(hook_name))
        tool_source = getattr(self.instance, "get_tools", None)
        if callable(tool_source):
            tools = list(tool_source())
            if tools:
                from thomas.agent.kernel_tool_provider import MountedTools
                from thomas.core.kernel import TOOLS, ToolsSeam, require
                from thomas.tools.base import Tool
                from thomas.tools.registry import ToolRegistry

                validated = ToolRegistry()
                for tool in tools:
                    if not isinstance(tool, Tool):
                        raise TypeError(f"Plugin {self.name!r} returned a non-Tool from get_tools()")
                    if not isinstance(tool.name, str) or not tool.name.strip():
                        raise ValueError(f"Plugin {self.name!r} returned a tool without a non-empty name")
                    validated.register(tool)
                provider = require(ctx, TOOLS, ToolsSeam)
                mounted = MountedTools(provider, tools)
                ctx.effect(mounted.withdraw)
                ctx.set(TOOLS, mounted)

    def _handler(self, hook_name: str):
        from thomas.plugins.p108_plugin_hook_runner_core import _call_hook, _get_hook_callable

        def handler(payload: dict[str, Any]) -> Any:
            fn = _get_hook_callable(self.instance, hook_name)
            if fn is None:
                return None
            return _call_hook(fn, hook=hook_name, payload=payload)

        handler.__name__ = f"{self.name}:{hook_name}"
        return handler


def plugin_systems_report(*, kernel: Kernel | None = None) -> dict[str, Any]:
    """What each of the four plugin systems actually is, and its live state.

    Written as a report rather than a docstring because the spec's "four plugin
    systems" framing implied four runtimes, and acting on that belief is how a
    catalog gets mistaken for a running feature.

    Phase 3.5: the three non-runtime systems are kernel services now, so this
    resolves the catalog through the kernel rather than importing it. Swap the
    provider and this report follows — which is what makes it a consumer of the
    seam rather than a description of one.
    """
    from thomas.server.plugin_systems_kernel import (
        AGENT_PLUGIN_INSTALLER,
        DESKTOP_PLUGIN_INSTALLER,
        EXTENSION_CATALOG,
        agent_plugin_installer,
        extension_catalog,
    )

    target = kernel or get_kernel()

    catalog = extension_catalog(kernel=target)
    agent_installer = agent_plugin_installer(kernel=target)
    try:
        packs = list(catalog.packs())
    except PLUGIN_LOAD_ERRORS as exc:
        log.debug("extension catalog unreadable: %s", exc)
        packs = []

    mounted = [fork for fork in target.mounted() if isinstance(fork.plugin, MountedLegacyPlugin)]
    return {
        "installed_plugins": {
            "kind": "runtime",
            "mounted_on_kernel": target.root.has(INSTALLED_PLUGINS_MOUNTED),
            "plugins": [fork.name for fork in mounted],
            "contributing_no_hooks": [fork.name for fork in mounted if not fork.plugin.hooks],
        },
        "extension_packs": {
            "kind": "catalog-only",
            "mounted_on_kernel": target.root.has(EXTENSION_CATALOG),
            "provider": type(catalog).__name__,
            "count": len(packs),
            "hooks_execute": bool(getattr(catalog, "hooks_execute", False)),
            "note": (
                "extension_catalog_runtime validates that each pack ships hooks.py "
                "and never imports it; no code path in the repository loads pack "
                "code, so their before_tool/after_tool have never run"
            ),
        },
        "agent_plugins": {
            "kind": "installer",
            "mounted_on_kernel": target.root.has(AGENT_PLUGIN_INSTALLER),
            "provider": type(agent_installer).__name__,
            "installs_through_the_service": True,
            "note": (
                "installs skills and registers MCP servers; no hook dispatch. Its "
                "production caller — _install_bundle_auto in "
                "routes/marketplace_catalog_aiohttp.py — resolves this service for "
                "both questions it asks a bundle: does this installer claim it, "
                "and install it. An import goes through the provider named here"
            ),
        },
        "desktop_plugins": {
            "kind": "installer",
            "mounted_on_kernel": target.root.has(DESKTOP_PLUGIN_INSTALLER),
            "note": (
                "registry rows and surface URLs; no hook dispatch. Installs through "
                "the thomas/server/desktop_plugins facade resolve the kernel service"
            ),
        },
    }
