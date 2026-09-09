"""Tree-delta collection, integrity fingerprints, and diff previews."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from .evolve_supervisor_manifest import (
    _is_evolve_protected_path,
    _iter_scope_files,
    _normalize_relpath,
    _read_text,
    _restore_green_path_from_blue,
    _sha256,
)


def _revert_protected_changes(
    paths,
    delta: dict[str, Any],
    protected_paths: set[str],
    *,
    allow_retain: set[str] | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    retained = {_normalize_relpath(rel) for rel in (allow_retain or set())}
    violations = sorted(
        rel
        for rel in (delta.get("changed_files") or [])
        if _is_evolve_protected_path(_normalize_relpath(rel), protected_paths)
        and _normalize_relpath(rel) not in retained
    )
    reverted: list[str] = []
    for rel in violations:
        _restore_green_path_from_blue(paths, rel)
        reverted.append(rel)
    if violations:
        delta = _collect_tree_delta(paths)
    return delta, violations, reverted


def _collect_tree_delta(paths) -> dict[str, Any]:
    blue = _iter_scope_files(paths.blue_root)
    green = _iter_scope_files(paths.green_root)
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []
    for rel in sorted(set(blue) | set(green)):
        blue_path = blue.get(rel)
        green_path = green.get(rel)
        if blue_path is None and green_path is not None:
            added.append(rel)
        elif green_path is None and blue_path is not None:
            removed.append(rel)
        elif blue_path is not None and green_path is not None and _sha256(blue_path) != _sha256(green_path):
            modified.append(rel)
    changed = list(added) + list(modified) + list(removed)
    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "changed_files": changed,
        "changed_count": len(changed),
    }


def _delta_signature(delta: dict[str, Any]) -> dict[str, Any]:
    return {
        "added": sorted(str(rel) for rel in (delta.get("added") or [])),
        "modified": sorted(str(rel) for rel in (delta.get("modified") or [])),
        "removed": sorted(str(rel) for rel in (delta.get("removed") or [])),
        "changed_files": sorted(str(rel) for rel in (delta.get("changed_files") or [])),
        "changed_count": int(delta.get("changed_count") or 0),
    }


def _delta_content_fingerprints_for_root(root: Path, delta: dict[str, Any]) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for rel in sorted(str(item) for item in (delta.get("changed_files") or [])):
        green_path = Path(root) / rel
        if green_path.is_file():
            fingerprints[rel] = _sha256(green_path)
        else:
            fingerprints[rel] = "<missing>"
    return fingerprints


def _delta_fingerprint_for_root(root: Path, delta: dict[str, Any]) -> dict[str, Any]:
    return {
        "signature": _delta_signature(delta),
        "content": _delta_content_fingerprints_for_root(root, delta),
    }


def _delta_fingerprint(paths, delta: dict[str, Any]) -> dict[str, Any]:
    return _delta_fingerprint_for_root(paths.green_root, delta)


def _delta_drift_rejection_reasons(expected_delta: dict[str, Any], current_delta: dict[str, Any]) -> list[str]:
    if _delta_signature(expected_delta) == _delta_signature(current_delta):
        return []
    current_preview = ", ".join(list(_delta_signature(current_delta)["changed_files"])[:8])
    expected_preview = ", ".join(list(_delta_signature(expected_delta)["changed_files"])[:8])
    return [
        "green tree changed after verification: "
        f"verified=[{expected_preview or 'none'}]; current=[{current_preview or 'none'}]"
    ]


def _delta_fingerprint_drift_rejection_reasons(
    expected_fingerprint: dict[str, Any],
    current_fingerprint: dict[str, Any],
) -> list[str]:
    if expected_fingerprint == current_fingerprint:
        return []
    expected_files = ", ".join(list(dict(expected_fingerprint.get("content") or {}).keys())[:8])
    current_files = ", ".join(list(dict(current_fingerprint.get("content") or {}).keys())[:8])
    return [
        "green tree content changed after verification: "
        f"verified=[{expected_files or 'none'}]; current=[{current_files or 'none'}]"
    ]


def _diff_preview(paths, delta: dict[str, Any], *, limit: int = 32) -> str:
    out: list[str] = []
    for rel in list(delta.get("modified") or [])[:limit]:
        before = _read_text(paths.blue_root / rel)
        after = _read_text(paths.green_root / rel)
        if before is None or after is None:
            out.append(f"*** {rel} (binary or undecodable)\n")
            continue
        out.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                n=3,
            )
        )
    for rel in list(delta.get("added") or [])[:limit]:
        after = _read_text(paths.green_root / rel)
        if after is None:
            out.append(f"*** {rel} (new binary or undecodable file)\n")
            continue
        out.extend(
            difflib.unified_diff([], after.splitlines(keepends=True), fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3)
        )
    for rel in list(delta.get("removed") or [])[:limit]:
        before = _read_text(paths.blue_root / rel)
        if before is None:
            out.append(f"*** {rel} (removed binary or undecodable file)\n")
            continue
        out.extend(
            difflib.unified_diff(before.splitlines(keepends=True), [], fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3)
        )
    return "".join(out)
