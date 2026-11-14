"""One supervised plugin: its handles, and how it describes itself.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md). Split out of
``plugin_supervisor`` along the line that was already there: this is the *record*
of one plugin — which fork it is mounted under, the handle that can put it back,
the fingerprint of the code that is answering, and the last reason a load failed
— while the supervisor is the collection and the operations on it.

``row`` imports nothing and runs no plugin code. That matters because the one
moment a status surface is worth reading is when a plugin failed to load, and a
description that can itself fail is no use then.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thomas.core.kernel import Unplugged
from thomas.core.kernel.plugins import Fork


@dataclass
class Supervised:
    """One installed plugin and the supervisor's handle on it."""

    name: str
    path: Path
    fingerprint: str = ""
    fork: Fork | None = None
    held: Unplugged | None = None
    error: str = ""

    @property
    def mounted(self) -> bool:
        return self.fork is not None and not self.fork.disposed

    @property
    def hooks(self) -> tuple[str, ...]:
        plugin = getattr(self.fork, "plugin", None)
        return tuple(getattr(plugin, "hooks", ()) or ())

    def row(self) -> dict[str, Any]:
        """What a status surface shows for this plugin.

        ``state`` distinguishes the three things "not mounted" can mean: you
        switched it off (``unplugged``, and the way back is held), or it never
        got on (``absent``, with ``error`` saying why). Collapsing those would
        make a failed load look like a deliberate choice.
        """
        plugin = getattr(self.fork, "plugin", None)
        return {
            "name": self.name,
            "plugin_id": getattr(plugin, "name", "") if plugin is not None else "",
            "path": str(self.path),
            "state": "mounted" if self.mounted else ("unplugged" if self.held is not None else "absent"),
            "hooks": list(self.hooks),
            "fingerprint": self.fingerprint[:12],
            "error": self.error,
        }


__all__ = ["Supervised"]
