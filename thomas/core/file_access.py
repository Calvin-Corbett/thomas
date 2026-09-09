"""Scalable file-access permission ladder for agent-spawned tools.

A separate axis from autonomy: autonomy governs how much Thomas ASKS before
acting; file-access governs WHAT a worker's filesystem tools may touch. Modeled
on Codex's sandbox modes / Claude Code's permission tiers, dialable from
read-only up to full-disk:

    0 read_only  — read only; no writes anywhere.
    1 workspace  — + write inside the task workspace (sandbox).  [DEFAULT]
    2 project    — + write inside the Thomas project tree.
    3 pc         — + write inside the user's home folder (Desktop, Documents…).
    4 full       — + write anywhere except OS system dirs and Thomas's own code.

INVARIANTS THAT HOLD AT EVERY LEVEL (defense in depth):
  - OS system directories (Windows/Program Files/etc.) are never writable.
  - Thomas's own runtime code is still guarded by filesystem._is_protected_runtime_path.
The ladder only widens the *workspace confinement*; it never disables the
runtime-code or system protections.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

READ_ONLY = 0
WORKSPACE = 1
PROJECT = 2
PC = 3
FULL = 4

DEFAULT_FILE_ACCESS_LEVEL = WORKSPACE


@dataclass(frozen=True)
class FileAccessSpec:
    level: int
    name: str
    ui_label: str
    summary: str


_SPECS: dict[int, FileAccessSpec] = {
    READ_ONLY: FileAccessSpec(READ_ONLY, "Read only", "read_only", "Read files; cannot write anything."),
    WORKSPACE: FileAccessSpec(
        WORKSPACE, "Workspace", "workspace", "Write only inside its own task workspace (sandbox)."
    ),
    PROJECT: FileAccessSpec(
        PROJECT, "Project", "project", "Also write inside the Thomas project (its own code stays protected)."
    ),
    PC: FileAccessSpec(PC, "Your PC", "pc", "Also write to your personal folders (Desktop, Documents, Downloads…)."),
    FULL: FileAccessSpec(FULL, "Full", "full", "Write anywhere except OS system folders and Thomas's own code."),
}

_NAME_TO_LEVEL = {s.ui_label: lvl for lvl, s in _SPECS.items()}
_NAME_TO_LEVEL.update({s.name.lower(): lvl for lvl, s in _SPECS.items()})
_ALIASES = {
    "read": READ_ONLY,
    "ro": READ_ONLY,
    "sandbox": WORKSPACE,
    "repo": PROJECT,
    "home": PC,
    "all": FULL,
    "anywhere": FULL,
}


def clamp_file_access_level(value: object, *, default: int = DEFAULT_FILE_ACCESS_LEVEL) -> int:
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(READ_ONLY, min(FULL, iv))


def parse_file_access_level(value: object, *, default: int = DEFAULT_FILE_ACCESS_LEVEL) -> int:
    """Parse a level from int, 'workspace'/'pc'/… name, or an alias."""
    if value is None:
        return default
    if isinstance(value, bool):  # guard: bool is an int subclass
        return PC if value else WORKSPACE
    if isinstance(value, int):
        return clamp_file_access_level(value, default=default)
    s = str(value).strip().lower()
    if not s:
        return default
    if s in _NAME_TO_LEVEL:
        return _NAME_TO_LEVEL[s]
    if s in _ALIASES:
        return _ALIASES[s]
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        return clamp_file_access_level(int(s), default=default)
    return default


def file_access_spec(level: object) -> FileAccessSpec:
    return _SPECS.get(clamp_file_access_level(level), _SPECS[DEFAULT_FILE_ACCESS_LEVEL])


def file_access_options() -> dict[int, dict[str, str]]:
    return {lvl: {"name": s.name, "ui_label": s.ui_label, "summary": s.summary} for lvl, s in _SPECS.items()}


# ── OS system directories that are NEVER writable, at any level ───────────────
def _system_deny_roots() -> list[Path]:
    roots: list[Path] = []
    if os.name == "nt":
        for env in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            val = os.environ.get(env)
            if val:
                roots.append(Path(val))
        roots.append(Path("C:/Windows"))
    else:
        roots += [
            Path(p) for p in ("/etc", "/usr", "/bin", "/sbin", "/boot", "/sys", "/proc", "/dev", "/lib", "/lib64")
        ]
        roots += [Path(p) for p in ("/System", "/Library", "/Applications", "/private")]
    out: list[Path] = []
    for r in roots:
        try:
            out.append(r.resolve())
        except OSError:
            continue
    return out


def _path_within(target: Path, root: Path) -> bool:
    """True if resolved *target* is inside (or equal to) resolved *root*. Uses
    commonpath so symlink/junction escapes and Windows case differences are handled."""
    try:
        t = target.resolve()
        r = root.resolve()
        common = Path(os.path.commonpath([str(t), str(r)]))
    except (ValueError, OSError):
        return False
    if os.name == "nt":
        return str(common).lower() == str(r).lower()
    return common == r


def resolve_write_roots(
    level: object,
    *,
    workspace_root: Path | None,
    project_root: Path | None = None,
    home_dir: Path | None = None,
) -> list[Path] | None:
    """Allowed write roots for a level. None == read-only (no writes). FULL returns
    [] meaning 'no root restriction' (only the system deny-list applies)."""
    lvl = clamp_file_access_level(level)
    if lvl == READ_ONLY:
        return None
    home = home_dir or Path.home()
    roots: list[Path] = []
    if workspace_root is not None:
        roots.append(workspace_root)
    if lvl >= PROJECT and project_root is not None:
        roots.append(project_root)
    if lvl >= PC:
        roots.append(home)
    if lvl >= FULL:
        return []  # unrestricted (deny-list still enforced by authorize_write)
    return roots


# ── Refusal wording, shared with the detectors below so they can never drift ──
# Each remedy names a lever the USER controls; refusal text that carries one
# must reach the user verbatim (chat_delegation_result_policy threads it into
# the final announcement). The system-dir refusal deliberately has no remedy:
# no ladder level unlocks it.
_REMEDY_OUTSIDE_SCOPE = "Raise the file-access level (e.g. to 'Your PC') to write here."
_REMEDY_READ_ONLY = "Raise Thomas's file-access level to let it write files."
_REFUSAL_SYSTEM_DIR_MARK = "never writable by Thomas at any access level"
_REFUSAL_PREFIX = "BLOCKED:"


def is_file_access_refusal(text: object) -> bool:
    """True when *text* carries a refusal produced by THIS ladder.

    Sight, not a gate: callers use this to recognise that a failure was
    deterministic policy (the identical call will be refused identically) and
    to surface the remedy — never to block a different attempt.
    """
    value = str(text or "")
    if _REFUSAL_PREFIX not in value:
        return False
    return _REMEDY_OUTSIDE_SCOPE in value or _REMEDY_READ_ONLY in value or _REFUSAL_SYSTEM_DIR_MARK in value


def file_access_refusal_remedy(text: object) -> str:
    """The user-actionable remedy sentence inside a ladder refusal, or ''.

    The remedy is the one thing the refusal knows that the user can act on;
    a reply that reports the refusal without it strands the user.
    """
    value = str(text or "")
    for sentence in (_REMEDY_OUTSIDE_SCOPE, _REMEDY_READ_ONLY):
        if sentence in value:
            return sentence
    return ""


def authorize_write(
    level: object,
    target: Path,
    *,
    workspace_root: Path | None,
    project_root: Path | None = None,
    home_dir: Path | None = None,
) -> tuple[bool, str]:
    """(allowed, reason) for writing to *target* at *level*. System dirs are always
    denied. Runtime-code protection is enforced separately by the filesystem tool."""
    lvl = clamp_file_access_level(level)
    spec = file_access_spec(lvl)

    # OS system dirs: never writable, even at FULL.
    for deny in _system_deny_roots():
        if _path_within(target, deny):
            return (
                False,
                f"{_REFUSAL_PREFIX} '{target}' is an OS system directory — {_REFUSAL_SYSTEM_DIR_MARK}.",
            )

    roots = resolve_write_roots(lvl, workspace_root=workspace_root, project_root=project_root, home_dir=home_dir)
    if roots is None:
        return False, (f"{_REFUSAL_PREFIX} file access is set to '{spec.ui_label}' (read-only). " + _REMEDY_READ_ONLY)
    if not roots:  # FULL — unrestricted apart from the system deny-list above
        return True, ""
    for root in roots:
        if _path_within(target, root):
            return True, ""
    return False, (
        f"{_REFUSAL_PREFIX} '{target}' is outside what file access '{spec.ui_label}' allows. " + _REMEDY_OUTSIDE_SCOPE
    )
