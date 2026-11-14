"""Loading one installed plugin off disk, as the kernel wants it.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md). Split out of
``plugin_supervisor`` along the responsibility that was actually separate:
*reading the code that is on disk right now* has different failure modes from
*holding mounts and changing them*, and the supervisor reads much better when
every ``except`` around third-party code lives on this side of the line.

The one rule here: a load never raises. It returns a :class:`LoadedPlugin`
carrying either an adapter or the reason there is none, because the caller is a
reload — and "your edit did not import, the previous version is still running"
is an answer, not an exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from thomas.server.plugin_kernel_mount import PLUGIN_LOAD_ERRORS, MountedLegacyPlugin


@dataclass(frozen=True)
class LoadedPlugin:
    """What came back from disk: an adapter, or why there isn't one.

    Callers ask ``adapter is None`` rather than a friendlier ``ok`` property: the
    two mean the same thing, and the explicit test is the one a type checker can
    narrow at the three call sites that go on to use the adapter.
    """

    adapter: MountedLegacyPlugin | None
    fingerprint: str = ""
    error: str = ""


def fingerprint_plugin(path: Path) -> str:
    """The content digest of a plugin's source. Equal digests, equal code."""
    from thomas.plugins.source_fingerprint import source_fingerprint

    return source_fingerprint(path)


def load_adapter(name: str, path: Path) -> LoadedPlugin:
    """Import the plugin as it is on disk now and wrap it for the kernel."""
    from thomas.plugins.runtime import load_plugin_instance

    fingerprint = fingerprint_plugin(path)
    # The runtime loader never raises — it logs a plugin's own import failure at
    # debug and returns None. Without collecting the reasons, every broken edit
    # would be reported as "no entrypoint", which is the wrong sentence for a
    # file with a typo in it and the only sentence the status surface shows you.
    reasons: list[str] = []
    try:
        instance = load_plugin_instance(name, path, errors=reasons)
    except PLUGIN_LOAD_ERRORS as exc:
        return LoadedPlugin(None, fingerprint, f"{type(exc).__name__}: {exc}")
    if instance is None:
        return LoadedPlugin(None, fingerprint, "; ".join(reasons) or "no recognizable plugin entrypoint on disk")
    try:
        return LoadedPlugin(MountedLegacyPlugin(instance), fingerprint)
    except PLUGIN_LOAD_ERRORS as exc:
        return LoadedPlugin(None, fingerprint, f"{type(exc).__name__}: {exc}")


def installed_plugin_paths(install_root: str | Path | None) -> dict[str, Path]:
    """Name -> directory for every enabled plugin, or ``{}`` if unreadable."""
    from thomas.plugins.runtime import enabled_plugin_paths

    try:
        return enabled_plugin_paths(install_root)
    except PLUGIN_LOAD_ERRORS:
        return {}


__all__ = ["LoadedPlugin", "fingerprint_plugin", "installed_plugin_paths", "load_adapter"]
