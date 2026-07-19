"""Safe repository selection and conversation-to-project persistence."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class ForgeCodeProjectError(ValueError):
    """Raised when a requested Forge Code project is not a usable repository."""


def validate_project_root(value: str | Path | None, *, fallback: str | Path) -> Path:
    """Resolve ``value`` to its containing git repository root.

    Forge change attribution and revert are git-backed, so non-repositories are
    rejected instead of silently running with misleading review controls.
    """

    raw = Path(value).expanduser() if value else Path(fallback)
    if not raw.is_absolute():
        raise ForgeCodeProjectError("project_root must be an absolute path")
    try:
        candidate = raw.resolve(strict=True)
    except OSError as exc:
        raise ForgeCodeProjectError("project_root does not exist") from exc
    if not candidate.is_dir():
        raise ForgeCodeProjectError("project_root must be a directory")
    try:
        proc = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ForgeCodeProjectError("project_root could not be inspected") from exc
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ForgeCodeProjectError("project_root must be inside a git repository")
    try:
        root = Path(proc.stdout.strip()).resolve(strict=True)
    except OSError as exc:
        raise ForgeCodeProjectError("git reported an unavailable repository root") from exc
    if not root.is_dir():
        raise ForgeCodeProjectError("git repository root is not a directory")
    return root


def thomas_source_repo_root() -> Path | None:
    """Absolute git-toplevel of Thomas's OWN source checkout, if it is one.

    Code runs must NEVER be pointed here: a "make me a game" ask would write
    into the product tree and its change-attribution/Revert UI would sweep up
    unrelated edits. Used as a hard safety net that rejects this path.
    """
    try:
        import thomas

        pkg = Path(thomas.__file__).resolve().parent  # .../thomas
        proc = subprocess.run(
            ["git", "-C", str(pkg.parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError, ImportError, ValueError):
        return None
    return None


def default_scratch_project(catalog_root: str | Path) -> Path:
    """Default project for a NEW Code conversation when the user picked none.

    The scratch repo is anchored in the user's HOME (``~/.thomas/code_scratch``),
    deliberately OUTSIDE any Thomas checkout: when the server runs from the repo
    with a repo-relative data dir, a data-dir-relative scratch path sits inside
    the repo working tree, so ``git rev-parse --show-toplevel`` walks up to the
    repo root and Code edits the product source (observed 2026-07-19). A
    home-anchored scratch has its OWN git toplevel. A real project is still one
    "Choose project folder" click away.
    """

    scratch = (Path.home() / ".thomas" / "code_scratch").expanduser()
    try:
        scratch.mkdir(parents=True, exist_ok=True)
        if not (scratch / ".git").exists():
            proc = subprocess.run(
                ["git", "init", "--initial-branch=main", str(scratch)],
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode != 0:
                raise ForgeCodeProjectError(f"scratch project git init failed: {proc.stderr.strip()[:200]}")
    except OSError as exc:
        raise ForgeCodeProjectError("scratch project directory could not be created") from exc
    resolved = validate_project_root(scratch, fallback=scratch)
    repo = thomas_source_repo_root()
    if repo is not None and resolved == repo:
        # Scratch somehow still resolved to the Thomas repo (e.g. HOME is inside
        # the checkout). Fail loudly rather than silently editing the product.
        raise ForgeCodeProjectError("scratch project resolved to the Thomas source repo; refusing")
    return resolved


def _registry_path(catalog_root: str | Path) -> Path:
    directory = Path(catalog_root) / ".thomas" / "evolve" / "agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "project_registry.json"


def _load_registry(catalog_root: str | Path) -> dict[str, dict[str, Any]]:
    path = _registry_path(catalog_root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(cid): row for cid, row in payload.items() if isinstance(row, dict)}


def _write_registry(catalog_root: str | Path, registry: dict[str, dict[str, Any]]) -> None:
    path = _registry_path(catalog_root)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def bind_conversation(
    catalog_root: str | Path,
    conversation_id: str,
    project_root: str | Path,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the selected repository and settings for one Code conversation."""

    cid = str(conversation_id or "").strip()
    if not cid:
        raise ForgeCodeProjectError("conversation_id is required")
    root = validate_project_root(project_root, fallback=catalog_root)
    registry = _load_registry(catalog_root)
    row = {"project_root": str(root), "settings": dict(settings or {})}
    registry[cid] = row
    _write_registry(catalog_root, registry)
    return dict(row)


def update_conversation_settings(
    catalog_root: str | Path,
    conversation_id: str,
    settings: dict[str, Any],
) -> dict[str, Any] | None:
    registry = _load_registry(catalog_root)
    row = registry.get(str(conversation_id or ""))
    if row is None:
        return None
    row["settings"] = dict(settings)
    _write_registry(catalog_root, registry)
    return dict(row)


def conversation_metadata(catalog_root: str | Path, conversation_id: str) -> dict[str, Any] | None:
    row = _load_registry(catalog_root).get(str(conversation_id or ""))
    return dict(row) if row is not None else None


def conversation_project(catalog_root: str | Path, conversation_id: str) -> Path:
    """Return a validated bound project, falling back for legacy conversations."""

    row = conversation_metadata(catalog_root, conversation_id)
    selected = row.get("project_root") if row else catalog_root
    return validate_project_root(selected, fallback=catalog_root)


def conversation_roots(catalog_root: str | Path) -> list[Path]:
    """Return unique, still-valid roots that may hold Code conversations."""

    roots: list[Path] = []
    candidates: list[str | Path] = [catalog_root]
    candidates.extend(
        row.get("project_root", "") for row in _load_registry(catalog_root).values() if row.get("project_root")
    )
    for candidate in candidates:
        try:
            root = validate_project_root(candidate, fallback=catalog_root)
        except ForgeCodeProjectError:
            continue
        if root not in roots:
            roots.append(root)
    return roots


def forget_conversation(catalog_root: str | Path, conversation_id: str) -> None:
    registry = _load_registry(catalog_root)
    if registry.pop(str(conversation_id or ""), None) is not None:
        _write_registry(catalog_root, registry)
