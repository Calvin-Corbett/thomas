"""One plugin-hook dispatcher, for every surface that runs an agent.

Phase 3.2 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md). Two defects this
module closes, both measured on 2026-09-08:

**The dispatcher existed on one surface.** ``chat_request_execution`` defined it
as a local closure and passed it in; ``worker_runtime`` passed nothing at all.
So the web chat path fired ``before_model``/``before_tool``/``after_tool``/
``after_response`` and every background task fired none — a plugin's view of
Thomas depended on which surface happened to be executing. One implementation,
imported by both, is the fix; adding a second copy would have been the bug.

**The response was thrown away.** The old closure called ``run_hook(...)``
without assigning it, and ``AgentLoop._run_plugin_hook`` documented that "any
return value is ignored". Meanwhile all 528 bundled ``pack-*`` extensions define
``before_tool``/``after_tool`` that build a modified payload and return it. Here
each plugin's ``output`` mapping is folded into the payload and handed back, so
a hook participates instead of spectating.

This lives under ``thomas/server/`` rather than ``thomas/agent/`` deliberately:
``thomas/_architecture.py`` lists ``plugins`` in ``server.depends_on`` and not in
``agent.depends_on``. The agent tier must not import the plugin tier, which is
what the closure it replaces was working around.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from thomas.agent.kernel_wiring import get_kernel
from thomas.core.kernel import Kernel

log = logging.getLogger(__name__)

#: Loading and calling a plugin runs third-party code. These are the ways that
#: fails without being a bug in Thomas; anything else propagates.
_PLUGIN_HOOK_ERRORS = (
    ImportError,
    AttributeError,
    KeyError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


def resolve_plugins_install_root() -> str | None:
    """Where installed plugins live. Same precedence the server always used."""
    env_dir = os.getenv("THOMAS_PLUGINS_DIR")
    if env_dir:
        return env_dir
    home = os.getenv("THOMAS_HOME")
    if home:
        return str(Path(home).expanduser() / "plugins")
    try:
        return str(Path.home() / ".thomas" / "plugins")
    except (OSError, RuntimeError):
        return None


def make_plugin_hook_runner(
    *,
    install_root: str | None = None,
    kernel: Kernel | None = None,
):
    """Build the ``hook_runner`` an ``AgentLoop`` accepts.

    Dispatches to installed legacy plugins and to kernel subscribers, folding
    every mapping either returns into the payload, and returns the result. Cheap
    when nothing is installed and nothing subscribes: one dict copy.

    A failing plugin never breaks a turn — the payload comes back as far as it
    got. Failures log at warning, not debug, because a plugin that silently does
    nothing is the condition this phase exists to make visible.
    """

    async def run(name: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        merged: dict[str, Any] = dict(payload or {})
        scope = (kernel or get_kernel()).root

        # Phase 3.3: once installed plugins are mounted, their hooks ARE kernel
        # subscriptions and the fold below carries them. Re-running the legacy
        # scan here would call every hook a second time. The marker is a kernel
        # service set by the mount, so it disappears the moment they unmount and
        # this falls back to the scan for hosts that never mounted.
        from thomas.server.plugin_kernel_mount import INSTALLED_PLUGINS_MOUNTED

        legacy_scan = not scope.has(INSTALLED_PLUGINS_MOUNTED)

        if legacy_scan:
            root = install_root if install_root is not None else resolve_plugins_install_root()
            try:
                from thomas.plugins.p108_plugin_hook_runner_core import HookRunRequest, run_hook
                from thomas.plugins.runtime import get_enabled_plugin_instances

                for plugin in get_enabled_plugin_instances(root):
                    # One plugin per call, folding between: ``run_hook`` hands
                    # every plugin it is given the same payload, so two plugins
                    # writing the same key would both work from the original and
                    # only the last would survive. This lane has to compose the
                    # same way the mounted one below does, or which plugins are
                    # heard would depend on whether the host mounted them.
                    response = run_hook(
                        HookRunRequest(hook=name, payload=merged, strict=False, continue_on_error=True),
                        plugins=[plugin],
                    )
                    for result in response.results:
                        output = getattr(result, "output", None)
                        if isinstance(output, Mapping):
                            merged.update(output)
            except _PLUGIN_HOOK_ERRORS as exc:
                log.warning("plugin hook %r dispatch failed (non-fatal): %s", name, exc)

        # ``fold``, not ``emit``: mounted plugins are subscribers now, and a hook
        # is a chain rather than a broadcast. Emitting hands every plugin the
        # same payload, so two plugins that each add to the same key both work
        # from the original and the later merge keeps only the last — mounting a
        # second plugin would silently cancel the first one's contribution.
        return await scope.fold(name, merged)

    return run
