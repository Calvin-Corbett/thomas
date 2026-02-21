"""Accessibility snapshot artifact capture.

This module implements the "browser artifact accessibility snapshot" feature.

Intent:
- Ask a browser/page-like object for an accessibility snapshot (AX tree-ish JSON).
- Persist it as an artifact file.
- Return machine-readable metadata for automation.

The wider Thomas codebase may provide different browser wrappers (Playwright Page,
a Thomas Browser tool wrapper, a remote driver, etc.). This module therefore uses
duck-typing and provides deterministic, structured errors.

Deterministic error codes:
- missing_config
- invalid_input
- external_failure
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol


class BrowserArtifactError(Exception):
    """Deterministic error for artifact capture failures."""

    def __init__(self, code: str, message: str, *, details: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: Dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict:
        payload: dict = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = dict(self.details)
        return payload


class _SupportsAccessibilitySnapshot(Protocol):
    def accessibility_snapshot(self, *, root: Any | None = None, interesting_only: bool = True) -> Any:
        ...


class _SupportsPlaywrightAccessibility(Protocol):
    def snapshot(self, *, root: Any | None = None, interesting_only: bool = True) -> Any:
        ...


@dataclass(frozen=True)
class AccessibilitySnapshotRequest:
    """Inputs for capturing an accessibility snapshot artifact."""

    source: Any
    artifact_dir: Path | None = None
    artifact_name: str = "accessibility_snapshot"
    interesting_only: bool = True
    root: Any | None = None

    def resolved_artifact_dir(self) -> Path:
        """Resolve the artifact directory.

        Resolution order:
        1) Explicit `artifact_dir`
        2) THOMAS_ARTIFACT_DIR env var
        """
        if self.artifact_dir is not None:
            return Path(self.artifact_dir)

        env_dir = os.environ.get("THOMAS_ARTIFACT_DIR")
        if env_dir:
            return Path(env_dir)

        raise BrowserArtifactError(
            "missing_config",
            "No artifact directory configured (set --artifact-dir or THOMAS_ARTIFACT_DIR).",
        )


@dataclass(frozen=True)
class AccessibilitySnapshotResult:
    """Outputs for capturing an accessibility snapshot artifact."""

    artifact_path: Path
    snapshot: Mapping[str, Any]

    def to_dict(self) -> dict:
        return {"artifact_path": str(self.artifact_path), "snapshot": self.snapshot}


def capture_accessibility_snapshot_artifact(request: AccessibilitySnapshotRequest) -> AccessibilitySnapshotResult:
    """Capture an accessibility snapshot and write it to an artifact file.

    Raises:
        BrowserArtifactError: deterministic codes:
            - missing_config
            - invalid_input
            - external_failure
    """

    artifact_dir = request.resolved_artifact_dir()
    _validate_artifact_dir(artifact_dir)

    artifact_name = _sanitize_artifact_name(request.artifact_name)
    artifact_path = _choose_available_path(artifact_dir / f"{artifact_name}.json")

    snapshot = _extract_snapshot(
        request.source,
        root=request.root,
        interesting_only=request.interesting_only,
    )

    payload = {
        "type": "accessibility_snapshot",
        "schema_version": 1,
        "options": {
            "interesting_only": bool(request.interesting_only),
            "root_provided": request.root is not None,
        },
        "snapshot": snapshot,
    }

    try:
        _write_json_atomic(artifact_path, payload)
    except BrowserArtifactError:
        raise
    except Exception as e:  # noqa: BLE001
        raise BrowserArtifactError(
            "external_failure",
            "Failed to write accessibility snapshot artifact.",
            details={"path": str(artifact_path), "exception": e.__class__.__name__},
        ) from e

    return AccessibilitySnapshotResult(artifact_path=artifact_path, snapshot=snapshot)


def _validate_artifact_dir(artifact_dir: Path) -> None:
    if not artifact_dir.exists():
        raise BrowserArtifactError(
            "invalid_input",
            "Artifact directory does not exist.",
            details={"artifact_dir": str(artifact_dir)},
        )
    if not artifact_dir.is_dir():
        raise BrowserArtifactError(
            "invalid_input",
            "Artifact directory is not a directory.",
            details={"artifact_dir": str(artifact_dir)},
        )


def _sanitize_artifact_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise BrowserArtifactError("invalid_input", "Artifact name must be non-empty.")

    # Don't allow path traversal or directory components.
    if any(sep in cleaned for sep in ("/", "\\")):
        raise BrowserArtifactError(
            "invalid_input",
            "Artifact name must not include path separators.",
            details={"artifact_name": name},
        )

    # Keep filenames boring.
    cleaned = cleaned.replace(" ", "_")
    return cleaned


def _choose_available_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def _write_json_atomic(path: Path, payload: Any) -> None:
    """Write JSON to a file atomically (best-effort across platforms)."""
    try:
        serialized = json.dumps(payload, indent=2, sort_keys=True)
    except Exception as e:  # noqa: BLE001
        raise BrowserArtifactError(
            "external_failure",
            "Accessibility snapshot payload is not JSON-serializable.",
            details={"exception": e.__class__.__name__},
        ) from e

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(serialized, encoding="utf-8")
        tmp_path.replace(path)
    except Exception as e:  # noqa: BLE001
        # Cleanup temp file if possible.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        raise e


def _extract_snapshot(source: Any, *, root: Any | None, interesting_only: bool) -> Mapping[str, Any]:
    # 1) Thomas-style wrapper: has `accessibility_snapshot(...)`.
    if hasattr(source, "accessibility_snapshot") and callable(getattr(source, "accessibility_snapshot")):
        return _call_snapshot(source, root=root, interesting_only=interesting_only)

    # 2) Wrapper exposes a `.page` attribute.
    page = getattr(source, "page", None)
    if page is not None:
        return _extract_snapshot(page, root=root, interesting_only=interesting_only)

    # 3) Playwright page: `page.accessibility.snapshot(...)`.
    accessibility = getattr(source, "accessibility", None)
    if accessibility is not None and hasattr(accessibility, "snapshot") and callable(getattr(accessibility, "snapshot")):
        try:
            snap = accessibility.snapshot(root=root, interesting_only=interesting_only)
        except Exception as e:  # noqa: BLE001
            raise BrowserArtifactError(
                "external_failure",
                "Browser failed while generating accessibility snapshot.",
                details={"exception": e.__class__.__name__},
            ) from e
        return _coerce_snapshot(snap)

    raise BrowserArtifactError(
        "invalid_input",
        "Snapshot source does not support accessibility snapshots.",
        details={"source_type": type(source).__name__},
    )


def _call_snapshot(source: _SupportsAccessibilitySnapshot, *, root: Any | None, interesting_only: bool) -> Mapping[str, Any]:
    try:
        snap = source.accessibility_snapshot(root=root, interesting_only=interesting_only)
    except Exception as e:  # noqa: BLE001
        raise BrowserArtifactError(
            "external_failure",
            "Browser failed while generating accessibility snapshot.",
            details={"exception": e.__class__.__name__},
        ) from e

    return _coerce_snapshot(snap)


def _coerce_snapshot(snapshot: Any) -> Mapping[str, Any]:
    # Playwright returns a nested dict/list structure (or None).
    if snapshot is None:
        raise BrowserArtifactError(
            "external_failure",
            "Accessibility snapshot returned null.",
        )

    if isinstance(snapshot, Mapping):
        return snapshot

    raise BrowserArtifactError(
        "external_failure",
        "Accessibility snapshot returned a non-mapping payload.",
        details={"payload_type": type(snapshot).__name__},
    )
