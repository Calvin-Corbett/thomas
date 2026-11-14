"""The other three plugin systems, mounted as kernel plugins.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

Phase 3.3 established what these three actually are: ``extensions/`` is a
catalog, and ``agent_plugins_*`` / ``desktop_plugins_*`` are installers. None of
them dispatches hooks, so none of them had anything to remount. That finding is
still true, and it is not a reason to leave them off the kernel — it only
changes *what* they contribute. They contribute a **service**: an object a
caller resolves by name instead of importing, which therefore can be replaced
while Thomas runs.

Each becomes a one-service kernel plugin. Mounting is reversible (the service
withdraws when the plugin unmounts), listable (``kernel.mounted()``), and
swappable (``MountedSystems.swap``), which are the three properties the
installed-plugin runtime got in 3.3 and these did not.

**Who calls what, so nothing here reads as busier than it is.**
``MountedSystems.status`` is read by the ``/api/plugins/kernel`` status route, and
so is every provider's ``describe()``. ``MountedSystems.swap`` is called from
``tests/test_plugin_systems_kernel.py``, from
``tests/test_plugin_kernel_routes.py`` (where a swapped provider is read back off
the status route), and from ``tests/test_marketplace_kernel_swap.py`` (where one
is read back off ``/api/marketplace/plugins`` and the import route), and from
nowhere else: no HTTP surface replaces a provider,
because a provider is an object rather than something a request can name, and
nobody asked to install one over the wire. The swap exists
because it is the only correct way to replace one — it keeps this handle pointing
at the fork that is answering, which a caller reaching for the kernel's ``swap``
directly gets wrong — and because "these three are replaceable while Thomas runs"
has to be a thing the code can actually do to be worth saying.

**Who resolves what, stated rather than implied.** A provider nobody resolves is
the defect this kernel exists to prevent, so:

- ``extension_catalog`` — resolved by ``plugin_systems_report``, the plugin
  status route, and ``_load_marketplace_catalog`` in
  ``thomas/server/routes/marketplace_catalog_packs.py``, which is what
  ``/api/marketplace/plugins`` and the sync fallback read. Swap it and the
  marketplace answers from the new provider on the next request.
- ``desktop_plugin_installer`` — resolved by ``thomas/server/desktop_plugins``,
  the facade the marketplace import route already imports from, so the live
  install path goes through the kernel without that route changing at all.
- ``agent_plugin_installer`` — resolved by ``_install_bundle_auto`` in
  ``thomas/server/routes/marketplace_catalog_aiohttp.py``, which asks the
  provider both of its questions: ``accepts`` for whether this installer claims
  the bundle, then ``install``. That redirect was blocked for the whole of 3.5
  by size rather than by design — the routes module was 1,190 lines, is not
  listed under ``allowed_large_files`` in ``docs/monolith_guard_baseline.json``,
  and the guard enforces its 800-line soft limit on every file a change touches,
  so the file could not be edited until it was split. It is four modules now
  (``marketplace_catalog_fields`` / ``_rows`` / ``_packs`` / ``_sync``) and the
  redirect landed. Note what was *not* done: turning
  ``agent_plugins_adapter.install_agent_plugin_bytes`` into a facade, the shape
  the desktop installer has. ``tests/test_install_transaction.py`` reads that
  function's source to check the install is transactional, so the seam belongs
  at the call site instead.

The three default providers live in ``thomas/server/plugin_system_providers.py``
and are re-exported here, so every caller keeps one import site. They are a
separate module because the two halves together exceed the per-file growth cap
(``scripts/forge/gates/commit_growth_guard.py``, 300 net lines); the seam is the
honest one either way — what a system *is* on one side, how it gets mounted,
resolved and swapped on the other.
"""

from __future__ import annotations

from typing import Any

from thomas.agent.kernel_wiring import get_kernel
from thomas.core.kernel import Kernel, SwapError, swap
from thomas.core.kernel.plugins import Fork
from thomas.server.plugin_system_providers import (
    AGENT_PLUGIN_INSTALLER,
    DEFAULT_PROVIDERS,
    DESKTOP_PLUGIN_INSTALLER,
    EXTENSION_CATALOG,
    SYSTEM_SERVICES,
    AgentPluginInstaller,
    DesktopPluginInstaller,
    ExtensionCatalog,
)


class SystemPlugin:
    """A kernel plugin whose whole contribution is one named service."""

    inject: tuple[str, ...] = ()

    def __init__(self, service: str, provider: Any) -> None:
        self.service = service
        self.provider = provider
        self.name = f"system:{service}"

    def __repr__(self) -> str:
        return f"<SystemPlugin {self.service!r} -> {type(self.provider).__name__}>"

    def apply(self, ctx: Any, config: Any) -> None:
        ctx.set(self.service, self.provider)


class MountedSystems:
    """The three systems' forks, keyed by service, and the way back."""

    def __init__(self, kernel: Kernel, forks: dict[str, Fork]) -> None:
        self.kernel = kernel
        self.forks = forks

    def __repr__(self) -> str:
        return f"<MountedSystems {len(self.forks)} system(s)>"

    @property
    def names(self) -> list[str]:
        return [fork.name for fork in self.forks.values()]

    def provider(self, service: str) -> Any:
        fork = self.forks.get(service)
        return getattr(fork.plugin, "provider", None) if fork is not None else None

    def swap(self, service: str, provider: Any) -> Fork:
        """Replace one system's provider while Thomas runs.

        The same ``swap`` the installed-plugin runtime uses: if the replacement
        cannot mount, the previous provider is still the one answering — and the
        handle is repointed at the fork it is answering under, so this object
        never holds a disposed fork for a live provider.
        """
        fork = self.forks[service]
        try:
            replacement = swap(fork, SystemPlugin(service, provider))
        except SwapError as exc:
            if exc.fork is not None:
                self.forks[service] = exc.fork
            raise
        self.forks[service] = replacement
        return replacement

    def status(self) -> list[dict[str, Any]]:
        """One row per system: is it mounted, and who is providing it.

        Read by the ``/api/plugins/kernel`` status route. A provider that is not
        the default one shows up here by name, which is what makes a swap
        something you can see rather than something you have to trust.
        """
        rows: list[dict[str, Any]] = []
        for service in SYSTEM_SERVICES:
            fork = self.forks.get(service)
            provider = self.provider(service)
            describe = getattr(provider, "describe", None)
            rows.append(
                {
                    "service": service,
                    "mounted": bool(fork is not None and fork.active),
                    "provider": describe() if callable(describe) else {},
                }
            )
        return rows

    def dispose(self) -> None:
        for fork in reversed(list(self.forks.values())):
            fork.dispose()
        self.forks = {}


def mount_plugin_systems(
    *,
    kernel: Kernel | None = None,
    providers: dict[str, Any] | None = None,
) -> MountedSystems:
    """Mount the catalog and the two installers as kernel plugins."""
    target = kernel or get_kernel()
    chosen = dict(providers or {})
    forks: dict[str, Fork] = {}
    for service in SYSTEM_SERVICES:
        provider = chosen.get(service) or DEFAULT_PROVIDERS[service]()
        forks[service] = target.mount(SystemPlugin(service, provider))
    return MountedSystems(target, forks)


def resolve_system(service: str, *, kernel: Kernel | None = None) -> Any:
    """The registered provider for ``service``, or the default one.

    Falling back rather than raising is deliberate: these three systems worked
    before there was a kernel, and a caller resolving one must not start
    depending on somebody having mounted it. The kernel makes the provider
    *replaceable*, not mandatory.
    """
    root = (kernel or get_kernel()).root
    provider = root.get(service, None)
    if provider is not None:
        return provider
    return DEFAULT_PROVIDERS[service]()


def extension_catalog(*, kernel: Kernel | None = None) -> Any:
    return resolve_system(EXTENSION_CATALOG, kernel=kernel)


def agent_plugin_installer(*, kernel: Kernel | None = None) -> Any:
    return resolve_system(AGENT_PLUGIN_INSTALLER, kernel=kernel)


def desktop_plugin_installer(*, kernel: Kernel | None = None) -> Any:
    return resolve_system(DESKTOP_PLUGIN_INSTALLER, kernel=kernel)


__all__ = [
    "AGENT_PLUGIN_INSTALLER",
    "DEFAULT_PROVIDERS",
    "DESKTOP_PLUGIN_INSTALLER",
    "EXTENSION_CATALOG",
    "SYSTEM_SERVICES",
    "AgentPluginInstaller",
    "DesktopPluginInstaller",
    "ExtensionCatalog",
    "MountedSystems",
    "SystemPlugin",
    "agent_plugin_installer",
    "desktop_plugin_installer",
    "extension_catalog",
    "mount_plugin_systems",
    "resolve_system",
]
