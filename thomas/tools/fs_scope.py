"""The files slot: which paths a root lets through.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md (slots). This is a scope policy, not an I/O layer:
it decides whether a path stays inside a root and whether a file may be read, and it never opens one.

``_safe_path`` and ``_is_read_protected_path`` live here and are still imported from ``thomas.tools.filesystem``,
because ``shell.py`` imports them under that name. Nothing else uses ``Scopes`` yet; the sites that test paths by
hand move onto it in the next wave.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from thomas.core.file_access import names_another_volume, path_is_inside
from thomas.tools.runtime_protection_flag import _RUNTIME_KEY_REL


def _is_read_protected_path(sandbox_root: Path, target: Path) -> str | None:
    """Return a refusal reason if *target* must not be readable by agent tools.

    Currently scoped to the HMAC signing key.  The disable-flag file is
    metadata only (timestamp + user + signature) and is harmless to read —
    forging it requires the key.  Protecting the key's read path is
    defense-in-depth alongside the write-side path protection (security
    hardening review).
    """
    try:
        rel = target.resolve().relative_to(sandbox_root.resolve())
    except ValueError:
        return None
    rel_posix_str = str(PurePosixPath(rel))
    if rel_posix_str == _RUNTIME_KEY_REL:
        return (
            f"BLOCKED: '{rel_posix_str}' is the runtime-protection signing key. "
            "Agent tools cannot read it; doing so would let an attacker mint "
            "valid disable flags."
        )
    return None


def _safe_path(root: Path, rel: str) -> Path:
    """Resolve path and ensure it doesn't escape the sandbox root.

    Resolving first stops symlink/junction escapes; path_is_inside then compares
    folders the way the disk does, so case differences (C: Users vs c: users)
    pass and a separate folder that only reads the same in lowercase does not.
    """
    resolved_root = root.resolve()
    p = (resolved_root / rel).resolve()
    if not path_is_inside(p, resolved_root):
        raise ValueError(f"Path escapes sandbox: {rel}")
    return p


class Scope:
    """One root and what may be reached from it."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def resolve(self, rel: str) -> Path:
        """The real path ``rel`` names under the root. Raises ``ValueError`` when it leads outside."""
        if names_another_volume(rel, self.root.resolve()):
            raise ValueError(f"Path escapes sandbox: {rel}")
        return _safe_path(self.root, rel)

    def contains(self, rel: str) -> bool:
        try:
            self.resolve(rel)
        except (ValueError, OSError):
            return False
        return True

    def read_refusal(self, rel: str) -> str | None:
        """Why the file may not be read, or ``None``. An escape is a refusal too."""
        try:
            target = self.resolve(rel)
        except (ValueError, OSError) as exc:
            return f"BLOCKED: {exc}"
        return _is_read_protected_path(self.root, target)


class Scopes:
    """The default provider for the ``fs`` seam: a scope for each root."""

    name = "default-fs-scopes"

    def scope(self, root: Path | str, /) -> Scope:
        return Scope(root)


_scopes = Scopes()


def scopes() -> Scopes:
    """The process-wide files slot."""
    return _scopes
