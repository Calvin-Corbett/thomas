"""The live plugin lane: unplug, replug, reload, all without a restart.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md), answering the part
of the original ask that the earlier phases did not reach:

    "everything's a plug in, and that's Thomas"

3.3 mounted the installed plugins at boot and unmounted them at shutdown. Every
question in between — turn this one off for a minute, I just edited that one,
pick up the one I installed while you were running — still ended in "restart
Thomas". This module is the supervisor that holds those mounts by name and can
change them while a turn is in flight.

**What each operation actually means here**

- ``unplug`` removes a plugin's subscriptions and *remembers it* — the kernel's
  own ``unplug`` returns a handle that can put it back. ``sync`` deliberately
  does not remount it afterwards: switching a plugin off and having the next
  disk scan switch it back on is not an off switch.
- ``reload`` re-reads the plugin's source from disk and swaps the running
  instance for the new one atomically. A reload whose new code raises leaves the
  *previous* version running and reports ``failed``, because the alternative —
  an unplugged plugin and a traceback — is a worse outcome than the edit simply
  not having landed.
- ``sync`` compares the install root against what is mounted: mounts what was
  installed or enabled since, unmounts what was removed or disabled, and reloads
  what changed on disk. This is the operation that makes a self-edit take effect
  with nothing else asked of you.

**Why the mount marker outlives an unplug.** ``plugin_hook_bridge`` skips its
legacy per-call manifest scan while ``INSTALLED_PLUGINS_MOUNTED`` is set. If
unplugging the last plugin dropped that marker, the scan would come back and
load the unplugged plugin straight off disk again — the off switch would turn
itself off. The marker therefore tracks *the supervisor*, not the count.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.agent.kernel_wiring import get_kernel
from thomas.core.kernel import Kernel, SwapError, swap, unplug
from thomas.core.kernel.plugins import Fork
from thomas.server.plugin_kernel_mount import INSTALLED_PLUGINS_MOUNTED, PLUGIN_LOAD_ERRORS
from thomas.server.plugin_loading import LoadedPlugin, fingerprint_plugin, installed_plugin_paths, load_adapter
from thomas.server.plugin_supervisor_entry import Supervised

log = logging.getLogger(__name__)


@dataclass
class PluginSupervisor:
    """Every installed plugin's mount, held by name and changeable in place."""

    kernel: Kernel
    install_root: str | Path | None
    plugins: dict[str, Supervised] = field(default_factory=dict)
    _marker: Any = None

    def __repr__(self) -> str:
        return f"<PluginSupervisor {len(self.mounted_names())} mounted, {len(self.unplugged_names())} unplugged>"

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> PluginSupervisor:
        """Mount every enabled plugin and claim the hook lane."""
        for name, path in self._enabled_paths().items():
            self._mount(Supervised(name=name, path=path))
        if self._marker is None:
            self._marker = self.kernel.root.set(INSTALLED_PLUGINS_MOUNTED, True)
        return self

    def dispose(self) -> None:
        """Unmount everything and hand the hook lane back to the legacy scan."""
        for entry in reversed(list(self.plugins.values())):
            if entry.fork is not None:
                entry.fork.dispose()
            entry.fork = None
            entry.held = None
        self.plugins.clear()
        if self._marker is not None:
            self._marker()
            self._marker = None

    # -- what the boot-time mount exposed, so the app handle is interchangeable --

    @property
    def names(self) -> list[str]:
        return list(self.plugins)

    @property
    def forks(self) -> list[Fork]:
        return [entry.fork for entry in self.plugins.values() if entry.fork is not None]

    @property
    def contributing_nothing(self) -> list[str]:
        return [entry.name for entry in self.plugins.values() if entry.mounted and not entry.hooks]

    def mounted_names(self) -> list[str]:
        return [entry.name for entry in self.plugins.values() if entry.mounted]

    def unplugged_names(self) -> list[str]:
        return [entry.name for entry in self.plugins.values() if not entry.mounted and entry.held is not None]

    # -- live operations ---------------------------------------------------

    def unplug(self, name: str) -> bool:
        """Take one plugin off the bus, keeping the way back. Idempotent."""
        entry = self.plugins.get(name)
        if entry is None or not entry.mounted:
            return False
        entry.held = unplug(entry.fork)  # type: ignore[arg-type]
        entry.fork = None
        log.info("plugin %r unplugged", name)
        return True

    def replug(self, name: str) -> bool:
        """Put an unplugged plugin back, re-reading its code from disk first.

        Re-reading is the honest default: between the unplug and the replug the
        file may have changed, and replugging the object that came off would
        quietly run code that is no longer what is installed.
        """
        entry = self.plugins.get(name)
        if entry is None or entry.mounted:
            return False
        held, entry.held = entry.held, None
        loaded = self._load(entry)
        if loaded.adapter is None:
            entry.held = held
            return False
        try:
            entry.fork = held.replug(loaded.adapter) if held is not None else self.kernel.mount(loaded.adapter)
        except (SwapError, *PLUGIN_LOAD_ERRORS) as exc:
            entry.error = f"{type(exc).__name__}: {exc}"
            entry.held = held
            log.warning("plugin %r could not be replugged: %s", name, exc)
            return False
        entry.fingerprint = loaded.fingerprint
        entry.error = ""
        log.info("plugin %r replugged", name)
        return True

    def reload(self, name: str, *, force: bool = False) -> str:
        """Swap a running plugin for the version currently on disk.

        Returns ``reloaded``, ``unchanged``, ``replugged``, ``failed`` or
        ``unknown`` — a word rather than a bool, because "it did nothing because
        the code is identical" and "it did nothing because it broke" are the two
        answers a caller most needs to tell apart.
        """
        entry = self.plugins.get(name)
        if entry is None:
            return "unknown"
        current = fingerprint_plugin(entry.path)
        if not entry.mounted:
            return "replugged" if self.replug(name) else "failed"
        if current == entry.fingerprint and not force:
            return "unchanged"
        loaded = self._load(entry)
        if loaded.adapter is None:
            return "failed"
        try:
            entry.fork = swap(entry.fork, loaded.adapter)  # type: ignore[arg-type]
        except SwapError as exc:
            # The old version is running again under a *new* fork. Taking it
            # from the error keeps this entry pointing at the live mount rather
            # than at the disposed handle the swap started from — and the
            # fingerprint stays on that old version, so asking again re-tries
            # the edit instead of calling it ``unchanged``.
            entry.fork = exc.fork
            entry.error = str(exc)
            log.warning("plugin %r failed to reload: %s", name, exc)
            return "failed"
        entry.fingerprint = loaded.fingerprint
        entry.error = ""
        log.info("plugin %r reloaded", name)
        return "reloaded"

    def sync(self) -> dict[str, list[str]]:
        """Reconcile what is mounted with what is installed, enabled and saved."""
        report: dict[str, list[str]] = {"mounted": [], "unmounted": [], "reloaded": [], "failed": []}
        on_disk = self._enabled_paths()

        for name in list(self.plugins):
            if name in on_disk:
                continue
            entry = self.plugins.pop(name)
            if entry.fork is not None:
                entry.fork.dispose()
            report["unmounted"].append(name)

        for name, path in on_disk.items():
            entry = self.plugins.get(name)
            if entry is None:
                fresh = Supervised(name=name, path=path)
                self._mount(fresh)
                report["mounted" if fresh.mounted else "failed"].append(name)
                continue
            entry.path = path
            if entry.held is not None:
                continue  # deliberately off; a disk scan does not overrule that
            outcome = self.reload(name)
            if outcome == "reloaded":
                report["reloaded"].append(name)
            elif outcome == "replugged":
                # It was known but not running — a mount that failed earlier and
                # whose code has since been fixed. That is a mount, not a reload.
                report["mounted"].append(name)
            elif outcome == "failed":
                report["failed"].append(name)
        return report

    def status(self) -> dict[str, Any]:
        """Everything a status surface needs, without importing a plugin."""
        return {
            "install_root": str(self.install_root or ""),
            "supervised": True,
            "mounted": self.mounted_names(),
            "unplugged": self.unplugged_names(),
            "contributing_no_hooks": self.contributing_nothing,
            "plugins": [entry.row() for entry in self.plugins.values()],
        }

    # -- internals ---------------------------------------------------------

    def _enabled_paths(self) -> dict[str, Path]:
        return installed_plugin_paths(self.install_root)

    def _load(self, entry: Supervised) -> LoadedPlugin:
        """The plugin as it is on disk now, or the reason there is none.

        Deliberately does not touch ``entry.fingerprint``. The fingerprint names
        *the version that is answering*, so it advances only where a mount, a
        replug or a swap has actually succeeded — three places, each one line
        below. Advancing it here instead would record code that never got on the
        bus, and the next reload of that same file would answer ``unchanged``:
        the one word that reads as "your edit is live" about an edit that is not.
        """
        loaded = load_adapter(entry.name, entry.path)
        entry.error = loaded.error
        return loaded

    def _mount(self, entry: Supervised) -> None:
        self.plugins[entry.name] = entry
        loaded = self._load(entry)
        if loaded.adapter is None:
            log.warning("plugin %r was not mounted: %s", entry.name, entry.error)
            return
        try:
            entry.fork = self.kernel.mount(loaded.adapter)
        except PLUGIN_LOAD_ERRORS as exc:
            entry.error = f"{type(exc).__name__}: {exc}"
            log.warning("plugin %r failed to mount: %s", entry.name, exc)
            return
        entry.fingerprint = loaded.fingerprint
        entry.error = ""


def start_plugin_supervisor(
    *,
    kernel: Kernel | None = None,
    install_root: str | Path | None = None,
) -> PluginSupervisor:
    """Mount the installed plugins under a supervisor that can change them."""
    from thomas.server.plugin_hook_bridge import resolve_plugins_install_root

    root = install_root if install_root is not None else resolve_plugins_install_root()
    return PluginSupervisor(kernel=kernel or get_kernel(), install_root=root).start()


__all__ = ["PluginSupervisor", "Supervised", "start_plugin_supervisor"]
