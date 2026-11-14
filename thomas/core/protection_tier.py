"""Report the protection Thomas actually has, measured, never assumed.

Every safety failure found on 2026-09-19 was the same shape: something reported a
protection it did not have. Gates printed PASS without running. A verification
record claimed a pass from `python -c print(123)`. `os_protect.py` showed
`0 locked, 94 open` while the repo described itself as protected. A frontend gate
answered "your code is clean" when it could not start the compiler.

So this module never reads a setting to decide how safe it is. It tries to write
to the files that enforce the rules, and requires the write to FAIL.

The three tiers:

    isolated  writes fail AND this process is not privileged
              -> nothing local short of an admin can undo it
    locked    writes fail, but this process is admin/root
              -> real, but this process could take ownership and undo it
    advisory  at least one write succeeded
              -> in-process checks only; `git config core.hooksPath ...`
                 disables every gate in one line

`isolated` is never reported on the strength of an installer having run. It is
reported only when a write was attempted and refused.
"""

from __future__ import annotations

import ctypes
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

TIER_ISOLATED = "isolated"
TIER_LOCKED = "locked"
TIER_ADVISORY = "advisory"

# The enforcement surface: the things that judge the agent. This is deliberately
# NOT the full protected-files list. A worker is expected to write thomas/ and
# tests/ - that is self-editing, and it is the product. These five are the
# referee, and no tier and no toggle makes them writable.
ENFORCEMENT_PATHS: tuple[str, ...] = (
    ".git/config",
    ".git/hooks",
    "agent_safety.toml",
    "scripts/forge/gates",
    "scripts/forge/commit_master.py",
)


@dataclass(frozen=True)
class TierReport:
    """What the probe actually found. `writable` is the evidence for the verdict."""

    tier: str
    writable: tuple[str, ...]
    privileged: bool
    checked: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def is_enforced(self) -> bool:
        return self.tier in (TIER_ISOLATED, TIER_LOCKED)

    def summary(self) -> str:
        if self.tier == TIER_ISOLATED:
            return "Protection: Isolated"
        if self.tier == TIER_LOCKED:
            return "Protection: Locked"
        return "Protection: Advisory - Thomas can edit its own safety rules."


def is_privileged() -> bool:
    """True when this process could undo a file lock by taking ownership.

    A locked file is not a boundary against the account that can change its
    owner, so this is what separates `locked` from `isolated`.
    """
    if os.name == "nt":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def _file_is_writable(path: Path) -> bool:
    """Attempt a real write-open. Never truncates: no O_TRUNC, no 'w' mode.

    os.access() is not used on purpose - it answers from the permission bits and
    is documented as unreliable on Windows, which is exactly the "ask the
    settings instead of trying it" mistake this module exists to avoid.
    """
    try:
        fd = os.open(path, os.O_WRONLY)
    except (PermissionError, OSError):
        return False
    os.close(fd)
    return True


def _dir_is_writable(path: Path) -> bool:
    """Attempt to create a file in the directory, then remove it."""
    probe = path / f".thomas-tier-probe-{uuid.uuid4().hex}"
    try:
        fd = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except (PermissionError, OSError):
        return False
    os.close(fd)
    try:
        probe.unlink()
    except OSError:
        # Created but not removable: still proves the directory took a write.
        pass
    return True


def probe_path(path: Path) -> bool:
    """True when this process can write `path`. Directories and files both."""
    if path.is_dir():
        return _dir_is_writable(path)
    return _file_is_writable(path)


def detect_tier(repo_root: Path, *, paths: tuple[str, ...] = ENFORCEMENT_PATHS) -> TierReport:
    """Measure the protection level by trying to write the enforcement surface.

    A path that does not exist is recorded in `missing` and does not count as
    writable - absence is not evidence either way, and silently treating it as
    locked would be the same false-comfort bug this module is built against.
    """
    writable: list[str] = []
    missing: list[str] = []
    checked: list[str] = []

    for rel in paths:
        target = repo_root / rel
        if not target.exists():
            missing.append(rel)
            continue
        checked.append(rel)
        if probe_path(target):
            writable.append(rel)

    privileged = is_privileged()
    if writable:
        tier = TIER_ADVISORY
    elif not checked:
        # Nothing was there to probe. Claiming protection here would be a verdict
        # with no evidence behind it.
        tier = TIER_ADVISORY
    elif privileged:
        tier = TIER_LOCKED
    else:
        tier = TIER_ISOLATED

    return TierReport(
        tier=tier,
        writable=tuple(writable),
        privileged=privileged,
        checked=tuple(checked),
        missing=tuple(missing),
    )
