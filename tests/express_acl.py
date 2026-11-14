"""A fake folder ACL lister that behaves the way NTFS does where it matters for the Express referee.

Plan row 33: a class is disabled when a cage account can write its landing folder. A fake that under-reports
writers would pass that check where it should not, so this one errs toward reporting. Permissions are additive
(an entry on a child never hides what the parent grants), a nearer level decides first and a deny is read before an
allow, and ``block_inheritance(path)`` stops the walk upward at that folder. Every principal is also in the broad
groups every Windows account belongs to (``Everyone``, ``Users``, ``Authenticated Users``, ``INTERACTIVE``,
``BATCH``, ``SERVICE``, ``LOCAL``). Names are compared after ``normalize`` (machine prefix, ``@machine`` suffix and
well-known SIDs fold). Rights are real NTFS names and icacls letters; an unknown name raises.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

READ = frozenset({"readdata", "readattributes", "readextendedattributes", "readpermissions", "synchronize"})
WRITE = frozenset({"writedata", "appenddata", "writeattributes", "writeextendedattributes"})
WRITE_ATOMS = frozenset(
    {"writedata", "appenddata", "delete", "deletesubdirectoriesandfiles", "changepermissions", "takeownership"}
)
BROAD_GROUPS = frozenset({"everyone", "users", "authenticated users", "interactive", "batch", "service", "local"})
_SIDS = {
    "s-1-1-0": "everyone",
    "s-1-5-32-545": "users",
    "s-1-5-11": "authenticated users",
    "s-1-5-4": "interactive",
    "s-1-5-3": "batch",
    "s-1-5-6": "service",
    "s-1-2-1": "local",
}


def normalize(principal: str) -> str:
    """One spelling for an account: ``MACHINE\\thomas-agent``, ``thomas-agent@MACHINE`` and a well-known SID all fold.

    The lister must agree with whatever ``icacls`` prints, so a grant spelled with the machine or domain in front
    still reaches the bare account name a test asks about.
    """
    name = principal.strip().lower()
    if name in _SIDS:
        return _SIDS[name]
    name = name.rsplit("\\", 1)[-1]
    return name.split("@", 1)[0]


_ALL = READ | WRITE | WRITE_ATOMS | {"takeownership", "executefile"}
_ALIASES = {
    "createfiles": {"writedata"},
    "createdirectories": {"appenddata"},
    "listdirectory": {"readdata"},
    "traverse": {"executefile"},
    "write": WRITE,
    "w": WRITE,
    "genericwrite": WRITE,
    "read": READ,
    "r": READ,
    "readandexecute": READ | {"executefile"},
    "rx": READ | {"executefile"},
    "readandwrite": READ | WRITE,
    "rw": READ | WRITE,
    "modify": READ | WRITE | {"executefile", "delete"},
    "m": READ | WRITE | {"executefile", "delete"},
    "fullcontrol": _ALL,
    "f": _ALL,
    "d": {"delete"},
}


def expand(rights: str) -> frozenset[str]:
    """Atomic rights for a NTFS name, an icacls letter or a comma-separated list of them. Unknown names raise."""
    atoms: set[str] = set()
    for word in re.split(r"[,|]", rights):
        key = re.sub(r"[\s_()]", "", word).lower()
        if key in _ALIASES:
            atoms |= _ALIASES[key]
        elif key in _ALL:
            atoms.add(key)
        else:
            raise ValueError(f"unknown NTFS right {word!r}")
    return frozenset(atoms)


@dataclass(frozen=True)
class Ace:
    principal: str
    rights: str
    deny: bool = False


def _key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(path))


class FakeAclLister:
    """Who can do what to a folder, computed the additive way."""

    def __init__(self) -> None:
        self._acl: dict[str, list[Ace]] = {}
        self._blocked: set[str] = set()
        self._members: dict[str, set[str]] = {}

    def grant(self, path: str | Path, principal: str, rights: str, *, deny: bool = False) -> None:
        expand(rights)  # refuse an unknown right now, not when someone later asks who can write
        self._acl.setdefault(_key(path), []).append(Ace(principal, rights, deny))

    def revoke(self, path: str | Path, principal: str) -> None:
        key = _key(path)
        self._acl[key] = [a for a in self._acl.get(key, []) if a.principal != principal]

    def block_inheritance(self, path: str | Path) -> None:
        self._blocked.add(_key(path))

    def add_member(self, group: str, member: str) -> None:
        self._members.setdefault(group, set()).add(member)

    def list(self, path: str | Path) -> tuple[Ace, ...]:
        """The entries set on this folder itself (not the inherited ones)."""
        return tuple(self._acl.get(_key(path), ()))

    def _levels(self, path: str | Path) -> list[list[Ace]]:
        current = Path(_key(path))
        levels = []
        for candidate in (current, *current.parents):
            levels.append(self._acl.get(str(candidate), []))
            if str(candidate) in self._blocked:
                break
        return levels

    def _groups_of(self, principal: str) -> set[str]:
        """Lower-cased names ``principal`` answers to: itself, its groups, and the broad groups everyone is in."""
        named = {principal} | {g for g, members in self._members.items() if principal in members}
        return {normalize(n) for n in named} | BROAD_GROUPS

    def effective(self, path: str | Path, principal: str) -> frozenset[str]:
        """The atomic rights ``principal`` holds on ``path`` once inheritance, groups and denies are applied."""
        names = self._groups_of(principal)
        decided: dict[str, bool] = {}
        for level in self._levels(path):
            for wanted_deny in (True, False):  # a deny is read before an allow at the same level
                for ace in level:
                    if ace.deny is wanted_deny and normalize(ace.principal) in names:
                        for atom in expand(ace.rights):
                            decided.setdefault(atom, not ace.deny)
        return frozenset(atom for atom, allowed in decided.items() if allowed)

    def can_write(self, path: str | Path, principal: str) -> bool:
        return bool(self.effective(path, principal) & WRITE_ATOMS)

    def writers(self, path: str | Path) -> list[str]:
        """Every account or group named anywhere in the ACLs (or as a member) that can write ``path``."""
        names = {a.principal for entries in self._acl.values() for a in entries}
        names |= {m for members in self._members.values() for m in members}
        return sorted(n for n in names if self.can_write(path, n))
