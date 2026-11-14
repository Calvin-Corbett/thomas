"""The default provider for each of the three non-runtime plugin systems.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

A *provider* is the object a caller resolves by name instead of importing:
``extension_catalog``, ``agent_plugin_installer``, ``desktop_plugin_installer``.
These three are the ones in place when nobody has mounted a replacement. The
mounting, resolving and swapping machinery is in
``thomas/server/plugin_systems_kernel.py``, which re-exports every name here so
callers have one import site; this module holds the providers themselves because
the two together are past the per-file growth cap
(``scripts/forge/gates/commit_growth_guard.py``, 300 net lines).

Each provider answers ``describe()``, which is what the ``/api/plugins/kernel``
status route prints. A swapped-in provider therefore shows up by name, which is
what makes a live swap something you can see rather than something you trust.

Every import of the underlying implementation is deferred into the method that
needs it. These are leaves of the dependency tree being wrapped, and importing
them at module scope would drag the marketplace runtime into every process that
merely wants to know what is mounted.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Canonical service names. Nobody types the string twice.
EXTENSION_CATALOG = "extension_catalog"
AGENT_PLUGIN_INSTALLER = "agent_plugin_installer"
DESKTOP_PLUGIN_INSTALLER = "desktop_plugin_installer"

SYSTEM_SERVICES: tuple[str, ...] = (EXTENSION_CATALOG, AGENT_PLUGIN_INSTALLER, DESKTOP_PLUGIN_INSTALLER)


class ExtensionCatalog:
    """The default provider for ``extension_catalog``.

    ``kind`` is ``catalog`` and ``hooks_execute`` is False because that is the
    measured truth from 3.3: the packs' ``hooks.py`` files are validated for
    existence and never imported. The provider states it so a reader of the
    status surface does not have to infer it from silence.
    """

    name = "extensions"
    kind = "catalog"
    hooks_execute = False

    def load(self, root: Path | None = None) -> dict[str, Any]:
        from thomas.plugins.extension_catalog_runtime import load_extension_catalog

        return load_extension_catalog(root=root)

    def packs(self, root: Path | None = None) -> list[Any]:
        try:
            catalog = self.load(root=root)
        except (OSError, ValueError, TypeError) as exc:
            log.debug("extension catalog unreadable: %s", exc)
            return []
        return list(catalog.get("packs") or catalog.get("extensions") or [])

    def describe(self) -> dict[str, Any]:
        return {
            "provider": type(self).__name__,
            "name": self.name,
            "kind": self.kind,
            "hooks_execute": self.hooks_execute,
            "count": len(self.packs()),
        }


class AgentPluginInstaller:
    """The default provider for ``agent_plugin_installer``.

    ``accepts`` and ``install`` are the contract a replacement provider has to
    meet, and both run in production: ``_install_bundle_auto`` in
    ``thomas/server/routes/marketplace_catalog_aiohttp.py`` resolves this service
    and asks it whether it claims the uploaded bundle before handing it over.
    ``tests/test_marketplace_kernel_swap.py`` swaps a recording provider in while
    the app is serving and reads back the bundle, the config and the source it
    was given.
    """

    name = "agent-plugins"
    kind = "installer"

    def accepts(self, bundle_bytes: bytes) -> bool:
        """Whether this installer claims the bundle.

        The detector lives in ``agent_plugins_manifest``, not in the adapter:
        the adapter imports four other names from it and has never exported
        this one, so importing it from there raised on every call.
        """
        from thomas.server.agent_plugins_manifest import bundle_is_agent_plugin

        return bool(bundle_is_agent_plugin(bundle_bytes))

    def install(self, config: Any, bundle_bytes: bytes, *, source: dict[str, Any]) -> dict[str, Any]:
        from thomas.server.agent_plugins_adapter import install_agent_plugin_bytes

        return install_agent_plugin_bytes(config, bundle_bytes, source=source)

    def describe(self) -> dict[str, Any]:
        return {"provider": type(self).__name__, "name": self.name, "kind": self.kind}


class DesktopPluginInstaller:
    """The default provider for ``desktop_plugin_installer``."""

    name = "desktop-plugins"
    kind = "installer"

    def install(
        self,
        config: Any,
        bundle_bytes: bytes,
        *,
        source: dict[str, Any] | None = None,
        require_signature: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from thomas.server.desktop_plugins_runtime import install_plugin_bundle_bytes

        return install_plugin_bundle_bytes(
            config,
            bundle_bytes,
            source=source,
            require_signature=require_signature,
            **kwargs,
        )

    def describe(self) -> dict[str, Any]:
        return {"provider": type(self).__name__, "name": self.name, "kind": self.kind}


#: service name -> the provider used when nobody has registered another.
DEFAULT_PROVIDERS: dict[str, Any] = {
    EXTENSION_CATALOG: ExtensionCatalog,
    AGENT_PLUGIN_INSTALLER: AgentPluginInstaller,
    DESKTOP_PLUGIN_INSTALLER: DesktopPluginInstaller,
}


__all__ = [
    "AGENT_PLUGIN_INSTALLER",
    "DEFAULT_PROVIDERS",
    "DESKTOP_PLUGIN_INSTALLER",
    "EXTENSION_CATALOG",
    "SYSTEM_SERVICES",
    "AgentPluginInstaller",
    "DesktopPluginInstaller",
    "ExtensionCatalog",
]
