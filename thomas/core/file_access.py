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
from functools import lru_cache
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


@lru_cache(maxsize=1)
def configured_file_access_level() -> int:
    """The level the owner actually set in config, or the ladder default.

    Callers with no explicit level per request used to fall back to a hardcoded
    WORKSPACE, which silently ignored ``[tools] file_access`` and pinned every
    worker to its own task folder however the owner had it set.

    Deliberately forgiving: a missing, unreadable or nonsense config answers
    with the default rather than raising, because the callers are decision
    paths that only want a number and a broken config must not take a run down.
    Cached because it is read per delegation and the file does not change under
    a running process.
    """
    try:
        from pathlib import Path as _Path

        from thomas.core.config import load_config

        override = os.environ.get("THOMAS_CONFIG")
        cfg = load_config(_Path(override)) if override else load_config()
        return clamp_file_access_level(getattr(cfg.tools, "file_access", DEFAULT_FILE_ACCESS_LEVEL))
    # What an unreadable or malformed config actually raises. Deliberately not
    # `except Exception`: this cannot re-raise -- the callers are decision paths
    # that only want a number, and a broken config must not take a run down --
    # so it names what it absorbs rather than swallowing everything.
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError):
        return DEFAULT_FILE_ACCESS_LEVEL


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
    """True if resolved *target* is inside (or equal to) resolved *root*, as the disk sees it.

    The allow side of the ladder, where a false True opens a folder nobody granted. Resolving handles symlink and
    junction escapes; path_is_inside handles case differences without reading a separate folder as the same one.
    """
    try:
        return path_is_inside(target.resolve(), root.resolve())
    except (ValueError, OSError):
        return False


def _reads_as_within(target: Path, root: Path) -> bool:
    """:func:`_path_within` for the deny list, which errs the other way: on Windows it also matches in lowercase.

    ``str.lower()`` reads a folder spelled with U+212A KELVIN SIGN as the one spelled with ``k``. That is why the allow
    side stopped trusting it, and why this side keeps it: a false True refuses one odd name, and without it the list
    would read fewer names than it always has. It is never narrower than ``_path_within``: checked across the BMP on
    Python 3.12.10, every letter ``normcase`` folds, ``str.lower()`` folds the same way.
    """
    try:
        resolved_target, resolved_root = target.resolve(), root.resolve()
    except (ValueError, OSError):
        return False
    if os.name == "nt":
        resolved_target, resolved_root = Path(str(resolved_target).lower()), Path(str(resolved_root).lower())
    return path_is_inside(resolved_target, resolved_root)


def path_is_inside(target: Path, root: Path) -> bool:
    """True if ``target`` is ``root`` or under it, compared folder by folder. Both must be resolved already.

    ``os.path.normcase`` decides whether two names are the same, because on Windows it asks the system. ``Path ==``,
    ``Path.is_relative_to`` and ``os.path.commonpath`` use ``str.lower()``, which turns U+212A KELVIN SIGN into ``k``
    while NTFS keeps the two apart, so a separate folder spelled with that sign passed as the root. Measured
    2026-10-31 on Python 3.12.10, making each letter a real folder: ``normcase`` changed 947 BMP letters and NTFS agreed
    on every one, and ``str.lower()`` folded 200 that NTFS keeps apart.
    """
    folded_root = [os.path.normcase(part) for part in root.parts]
    return [os.path.normcase(part) for part in target.parts[: len(folded_root)]] == folded_root


def names_another_volume(path: str | os.PathLike[str], root: Path) -> bool:
    """True if ``path``, as written, is on another drive or host than ``root``. Read from the text, touching nothing.

    The check has to come before ``resolve()``, because resolving opens the path: ``\\\\host\\share\\x`` reaches the
    filesystem layer, and Windows can offer the account's NTLM credentials to that host, all to learn it is outside.
    ``\\??\\`` is the native spelling, which Windows honours and in which pathlib sees no drive at all.
    """
    text = os.fspath(path)
    if os.name == "nt" and text.replace("/", "\\").startswith("\\??\\"):
        return True
    drive = Path(text).drive
    return bool(drive) and os.path.normcase(drive) != os.path.normcase(root.drive)


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


_RUNTIME_PROTECTION_MARK = "Agent-spawned tools cannot modify"


def is_deterministic_policy_refusal(text: object) -> bool:
    """True for any refusal the identical call will meet forever.

    TWO ladders produce these, in different vocabularies: the file-access ladder
    above, and runtime protection (thomas/tools/runtime_protection_paths.py),
    which refuses writes into Thomas's own runtime. Both open with
    ``_REFUSAL_PREFIX``, but only the first carries the remedy sentences
    ``is_file_access_refusal`` looks for - so a runtime-protection block scored
    as a TRANSIENT failure and the loop kept retrying it.

    Measured 2026-09-19 by driving the UI: a chat task card tried to create
    thomas/agent/loop_provider_limits.py and was blocked once. The run then
    continued for ten more minutes without surfacing the block or finishing,
    behind an "On it - working on this" spinner, and nothing was ever written.

    Scope of what is measured: the misclassification is read directly from the
    code (``_record_failed_tool`` scored this 1, not 2). Whether the model
    actually repeated the identical call is NOT established - the logs show a
    single block. This widening removes a wrong signal; it is not by itself
    proof of what the model did with it.

    Sight, not a gate - exactly as above. A DIFFERENT attempt stays fully open.
    """
    value = str(text or "")
    if is_file_access_refusal(value):
        return True
    return _REFUSAL_PREFIX in value and _RUNTIME_PROTECTION_MARK in value


_RUNTIME_PROTECTION_USER_REMEDY = (
    "This task tried to change the running Thomas's own files directly, which is "
    "blocked. Changes to Thomas are made in a private copy and reach the running "
    "Thomas when you approve the card -- ask for a self-fix, or open it in "
    "Redesign. A one-off change straight to the running Thomas, skipping the "
    "card, asks at your operating system's prompt instead."
)


def deterministic_refusal_remedy(text: object) -> str:
    """The USER-actionable sentence for either ladder, or ''.

    ``file_access_refusal_remedy`` speaks only the file-access ladder's
    vocabulary and returns '' for a runtime-protection block, so the block's
    guidance never reached the person. The block does carry guidance, but it is
    written for the MODEL ("call fs.write_protected_file", "stop now and
    report"); the sentence returned here is the same fact in the register a
    person can act on.

    Measured 2026-09-19: a chat task card was blocked from writing inside
    thomas/agent/, and the reply the person saw said only that the refactor
    "stalled ... I can rerun it with a narrower scope" - advice that cannot
    work, because scope was never the obstacle. Same shape as the 2026-08-05
    incident recorded on ``result_with_policy_remedy``: the lever was known and
    withheld.
    """
    value = str(text or "")
    ladder = file_access_refusal_remedy(value)
    if ladder:
        return ladder
    if _REFUSAL_PREFIX in value and _RUNTIME_PROTECTION_MARK in value:
        return _RUNTIME_PROTECTION_USER_REMEDY
    return ""


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
        if _reads_as_within(target, deny):
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
