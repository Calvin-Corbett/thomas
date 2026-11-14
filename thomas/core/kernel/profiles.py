"""Profiles: a named, ordered composition of plugins.

Phase 3.2 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md), the last piece.

Thomas configures a run by piling arguments onto a constructor —
``AgentLoop.__init__`` takes twenty-three parameters, and each surface passes a
different subset. That is configuration by accretion: there is no name for "the
headless setup", only the particular arguments a given call site remembered to
pass, and no way to see two setups side by side.

A profile is the alternative. It names an ordered list of entries, each an id
plus a plugin plus its config, and it is *immutable*: ``extend``, ``patch``,
``without`` and ``insert_after`` each return a new profile. So a host describes
its variant as a diff against a base rather than a fork of it, and the diff is
inspectable before anything mounts.

Order matters and is preserved: entries mount in the order listed, so a later
entry may deliberately override a service an earlier one provided, and
un-mounting restores what came before because every registration is reversible.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

log = logging.getLogger(__name__)


class ProfileError(ValueError):
    """A profile was built or patched in a way that cannot be resolved."""


@dataclass(frozen=True)
class Entry:
    """One row of a profile: a plugin, its config, and a stable id.

    The id is what a patch targets, so it must stay put even when the plugin
    behind it is swapped — that is the whole point of naming rows.
    """

    id: str
    plugin: Any
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    """An ordered, immutable composition. Every operation returns a new one."""

    name: str
    entries: tuple[Entry, ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for entry in self.entries:
            if entry.id in seen:
                raise ProfileError(f"profile {self.name!r} has two entries with id {entry.id!r}")
            seen.add(entry.id)

    # -- inspection --------------------------------------------------------

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(entry.id for entry in self.entries)

    def index_of(self, entry_id: str) -> int:
        for position, entry in enumerate(self.entries):
            if entry.id == entry_id:
                return position
        raise ProfileError(f"profile {self.name!r} has no entry {entry_id!r}")

    # -- composition -------------------------------------------------------

    def extend(self, name: str, entries: Iterable[Entry]) -> Profile:
        """A new profile: this one's rows, then the given ones."""
        return Profile(name=name, entries=self.entries + tuple(entries))

    def patch(
        self,
        entry_id: str,
        *,
        plugin: Any = None,
        config: Mapping[str, Any] | None = None,
        name: str | None = None,
    ) -> Profile:
        """Replace one row's plugin and/or config, keeping its position."""
        position = self.index_of(entry_id)
        current = self.entries[position]
        updated = replace(
            current,
            plugin=current.plugin if plugin is None else plugin,
            config=current.config if config is None else config,
        )
        entries = self.entries[:position] + (updated,) + self.entries[position + 1 :]
        return Profile(name=name or self.name, entries=entries)

    def without(self, entry_id: str, *, name: str | None = None) -> Profile:
        """Drop one row. Raises if it is not there, so a typo is not a silent no-op."""
        position = self.index_of(entry_id)
        entries = self.entries[:position] + self.entries[position + 1 :]
        return Profile(name=name or self.name, entries=entries)

    def insert_after(self, entry_id: str, entry: Entry, *, name: str | None = None) -> Profile:
        """Place a new row directly after an existing one."""
        position = self.index_of(entry_id) + 1
        entries = self.entries[:position] + (entry,) + self.entries[position:]
        return Profile(name=name or self.name, entries=entries)


class MountedProfile:
    """What a profile became once mounted: its forks, and the way back."""

    def __init__(self, profile: Profile, forks: list[Any]) -> None:
        self.profile = profile
        self.forks = forks

    def __repr__(self) -> str:
        return f"<MountedProfile {self.profile.name!r} entries={len(self.forks)}>"

    @property
    def pending(self) -> list[Any]:
        """Entries that mounted but are waiting on a service nobody provides."""
        return [fork for fork in self.forks if not fork.active]

    def dispose(self) -> None:
        """Unmount every entry, newest first, so overrides unwind before what they hid."""
        for fork in reversed(self.forks):
            fork.dispose()
        self.forks = []


def apply_profile(kernel: Any, profile: Profile) -> MountedProfile:
    """Mount a profile's entries in order.

    A row whose dependencies are unmet does not fail the profile — it mounts as
    pending and shows up in ``MountedProfile.pending`` and in ``seam_report``.
    That is deliberate: the honest state of a partially-satisfiable composition
    is "these three are waiting on ``llm``", not a crash and not silence.
    """
    forks: list[Any] = []
    try:
        for entry in profile.entries:
            forks.append(kernel.mount(entry.plugin, entry.config))
    except BaseException as exc:
        log.warning(
            "profile %r failed after %d of %d entries; unwinding all of them: %s",
            profile.name,
            len(forks),
            len(profile.entries),
            exc,
        )
        for fork in reversed(forks):
            fork.dispose()
        raise
    return MountedProfile(profile, forks)
