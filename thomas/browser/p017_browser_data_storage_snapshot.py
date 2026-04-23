from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import importlib
import json
import os
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

ErrorCode = Literal["invalid_input", "missing_config", "external_failure"]


class BrowserDataStorageSnapshotError(Exception):
    """Deterministic error for browser data storage snapshot operations."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message: str = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


@dataclasses.dataclass(frozen=True)
class BrowserDataStorageSnapshotRequest:
    """Input contract for taking a snapshot of browser data storage."""

    data_dir: Path | None = None
    profile: str | None = None
    output_path: Path | None = None
    overwrite: bool = False
    strict: bool = True
    include_hash: bool = True
    include_manifest: bool = True
    compress_level: int = 6  # zlib default; good tradeoff for real-world browser profiles

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BrowserDataStorageSnapshotRequest:
        if not isinstance(data, Mapping):
            raise BrowserDataStorageSnapshotError(
                "invalid_input",
                "Request payload must be a JSON object.",
                details={"got_type": type(data).__name__},
            )

        def _p(key: str) -> Path | None:
            v = data.get(key)
            if v is None:
                return None
            if not isinstance(v, (str, os.PathLike)):
                raise BrowserDataStorageSnapshotError(
                    "invalid_input",
                    f"'{key}' must be a path string.",
                    details={"key": key, "got_type": type(v).__name__},
                )
            return Path(v)

        profile = data.get("profile")
        if profile is not None and not isinstance(profile, str):
            raise BrowserDataStorageSnapshotError(
                "invalid_input",
                "'profile' must be a string.",
                details={"got_type": type(profile).__name__},
            )

        def _b(key: str, default: bool) -> bool:
            v = data.get(key, default)
            if isinstance(v, bool):
                return v
            raise BrowserDataStorageSnapshotError(
                "invalid_input",
                f"'{key}' must be a boolean.",
                details={"key": key, "got_type": type(v).__name__},
            )

        compress_level = data.get("compress_level", 6)
        if isinstance(compress_level, bool) or not isinstance(compress_level, int):
            raise BrowserDataStorageSnapshotError(
                "invalid_input",
                "'compress_level' must be an integer between 0 and 9.",
                details={"got_type": type(compress_level).__name__},
            )
        if compress_level < 0 or compress_level > 9:
            raise BrowserDataStorageSnapshotError(
                "invalid_input",
                "'compress_level' must be between 0 and 9.",
                details={"compress_level": compress_level},
            )

        return cls(
            data_dir=_p("data_dir"),
            profile=profile,
            output_path=_p("output_path"),
            overwrite=_b("overwrite", False),
            strict=_b("strict", True),
            include_hash=_b("include_hash", True),
            include_manifest=_b("include_manifest", True),
            compress_level=compress_level,
        )


@dataclasses.dataclass(frozen=True)
class BrowserDataStorageSnapshotResult:
    """Output contract for a browser data storage snapshot."""

    ok: bool
    data_dir: Path
    snapshot_path: Path
    format: Literal["zip"]
    bytes_written: int
    file_count: int
    skipped_files: tuple[str, ...]
    sha256: str | None
    created_at: str
    manifest_path_in_archive: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data_dir": str(self.data_dir),
            "snapshot_path": str(self.snapshot_path),
            "format": self.format,
            "bytes_written": self.bytes_written,
            "file_count": self.file_count,
            "skipped_files": list(self.skipped_files),
            "sha256": self.sha256,
            "created_at": self.created_at,
            "manifest_path_in_archive": self.manifest_path_in_archive,
        }


TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "data_dir": {"type": ["string", "null"], "description": "Browser data directory to snapshot."},
        "profile": {
            "type": ["string", "null"],
            "description": "Browser profile name to snapshot (resolved via config/env).",
        },
        "output_path": {"type": ["string", "null"], "description": "Where to write the snapshot archive (.zip)."},
        "overwrite": {"type": "boolean", "default": False},
        "strict": {"type": "boolean", "default": True},
        "include_hash": {"type": "boolean", "default": True},
        "include_manifest": {"type": "boolean", "default": True},
        "compress_level": {"type": "integer", "minimum": 0, "maximum": 9, "default": 6},
    },
    "required": [],
}

TOOL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ok": {"type": "boolean"},
        "data_dir": {"type": "string"},
        "snapshot_path": {"type": "string"},
        "format": {"type": "string"},
        "bytes_written": {"type": "integer"},
        "file_count": {"type": "integer"},
        "skipped_files": {"type": "array", "items": {"type": "string"}},
        "sha256": {"type": ["string", "null"]},
        "created_at": {"type": "string"},
        "manifest_path_in_archive": {"type": ["string", "null"]},
    },
    "required": [
        "ok",
        "data_dir",
        "snapshot_path",
        "format",
        "bytes_written",
        "file_count",
        "skipped_files",
        "created_at",
    ],
}


def browser_data_storage_snapshot(request: BrowserDataStorageSnapshotRequest) -> BrowserDataStorageSnapshotResult:
    """Create a ZIP archive snapshot of a browser's persisted storage directory.

    This is designed to be robust and deterministic:
    - invalid input -> BrowserDataStorageSnapshotError(code="invalid_input")
    - unable to resolve data dir -> BrowserDataStorageSnapshotError(code="missing_config")
    - I/O failures -> BrowserDataStorageSnapshotError(code="external_failure")
    """
    if not isinstance(request, BrowserDataStorageSnapshotRequest):
        raise BrowserDataStorageSnapshotError(
            "invalid_input",
            "Request must be a BrowserDataStorageSnapshotRequest.",
            details={"got_type": type(request).__name__},
        )

    if isinstance(request.compress_level, bool) or not isinstance(request.compress_level, int):
        raise BrowserDataStorageSnapshotError(
            "invalid_input",
            "compress_level must be an integer between 0 and 9.",
            details={"got_type": type(request.compress_level).__name__},
        )
    if request.compress_level < 0 or request.compress_level > 9:
        raise BrowserDataStorageSnapshotError(
            "invalid_input",
            "compress_level must be between 0 and 9.",
            details={"compress_level": request.compress_level},
        )

    data_dir = _resolve_data_dir(request)
    _validate_data_dir(data_dir)

    snapshot_path = _resolve_output_path(
        data_dir=data_dir,
        output_path=request.output_path,
        overwrite=request.overwrite,
    )

    created_at = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()

    file_count = 0
    skipped: list[str] = []
    files_listing: list[dict[str, Any]] = []

    manifest_path_in_archive: str | None = None

    try:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise BrowserDataStorageSnapshotError(
            "external_failure",
            "Failed to create output directory.",
            details={"output_dir": str(snapshot_path.parent), "os_error": str(e)},
        ) from e

    tmp_zip_path = _make_temp_output_path(snapshot_path)

    try:
        with zipfile.ZipFile(
            tmp_zip_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=request.compress_level,
            allowZip64=True,
        ) as zf:
            for root, dirs, files in os.walk(data_dir):
                dirs.sort()
                files.sort()
                for filename in files:
                    full_path = Path(root) / filename
                    if full_path.is_symlink():
                        skipped.append(full_path.relative_to(data_dir).as_posix())
                        continue

                    rel = full_path.relative_to(data_dir)
                    arcname = rel.as_posix()  # stable across OSes (Windows uses backslashes otherwise)
                    if not full_path.is_file():
                        skipped.append(arcname)
                        continue

                    try:
                        st = full_path.stat()
                    except OSError as e:
                        if request.strict:
                            raise BrowserDataStorageSnapshotError(
                                "external_failure",
                                "Failed to stat file while creating snapshot.",
                                details={"path": str(full_path), "os_error": str(e)},
                            ) from e
                        skipped.append(arcname)
                        continue

                    try:
                        zf.write(full_path, arcname=arcname)
                        file_count += 1
                        if request.include_manifest:
                            files_listing.append(
                                {
                                    "path": arcname,
                                    "size": int(st.st_size),
                                    "mtime": _dt.datetime.fromtimestamp(st.st_mtime, tz=_dt.timezone.utc).isoformat(),
                                }
                            )
                    except OSError as e:
                        if request.strict:
                            raise BrowserDataStorageSnapshotError(
                                "external_failure",
                                "Failed to read file while creating snapshot.",
                                details={"path": str(full_path), "os_error": str(e)},
                            ) from e
                        skipped.append(arcname)
                    except NotImplementedError as e:
                        raise BrowserDataStorageSnapshotError(
                            "external_failure",
                            "ZIP_DEFLATED compression is not available in this Python environment.",
                            details={"exception": str(e)},
                        ) from e

            if request.include_manifest:
                manifest_path_in_archive = "thomas_browser_data_storage_snapshot_manifest.json"
                manifest = {
                    "created_at": created_at,
                    "data_dir": str(data_dir),
                    "file_count": file_count,
                    "skipped_files": skipped,
                    "format": "zip",
                    "compress_level": request.compress_level,
                    "files": files_listing,
                }
                zf.writestr(
                    manifest_path_in_archive,
                    json.dumps(manifest, sort_keys=True, indent=2),
                )

    except BrowserDataStorageSnapshotError:
        _safe_unlink(tmp_zip_path)
        raise
    except Exception as e:  # pragma: no cover - defensive
        _safe_unlink(tmp_zip_path)
        raise BrowserDataStorageSnapshotError(
            "external_failure",
            "Failed to create snapshot archive.",
            details={"exception_type": type(e).__name__, "exception": str(e)},
        ) from e

    try:
        bytes_written = tmp_zip_path.stat().st_size
    except OSError as e:
        _safe_unlink(tmp_zip_path)
        raise BrowserDataStorageSnapshotError(
            "external_failure",
            "Failed to stat snapshot archive.",
            details={"snapshot_path": str(tmp_zip_path), "os_error": str(e)},
        ) from e

    sha256: str | None = None
    if request.include_hash:
        sha256 = _sha256_file(tmp_zip_path)

    try:
        os.replace(tmp_zip_path, snapshot_path)
    except OSError as e:
        _safe_unlink(tmp_zip_path)
        raise BrowserDataStorageSnapshotError(
            "external_failure",
            "Failed to finalize snapshot archive (atomic replace failed).",
            details={"tmp_path": str(tmp_zip_path), "snapshot_path": str(snapshot_path), "os_error": str(e)},
        ) from e

    return BrowserDataStorageSnapshotResult(
        ok=True,
        data_dir=data_dir,
        snapshot_path=snapshot_path,
        format="zip",
        bytes_written=bytes_written,
        file_count=file_count,
        skipped_files=tuple(skipped),
        sha256=sha256,
        created_at=created_at,
        manifest_path_in_archive=manifest_path_in_archive,
    )


def run_tool(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Tool-friendly wrapper: accepts a JSON payload and returns a JSON-serializable dict."""
    req = BrowserDataStorageSnapshotRequest.from_dict(payload)
    res = browser_data_storage_snapshot(req)
    return res.to_dict()


def _resolve_data_dir(request: BrowserDataStorageSnapshotRequest) -> Path:
    if request.data_dir is not None:
        return Path(request.data_dir).expanduser().resolve()

    candidates: list[Path] = []

    profile = request.profile
    profile_env_key = None
    if profile:
        profile_env_key = f"THOMAS_BROWSER_PROFILE_{profile.upper().replace('-', '_')}_DATA_DIR"

    for env_key in [
        "THOMAS_BROWSER_DATA_DIR",
        "THOMAS_BROWSER_USER_DATA_DIR",
        "THOMAS_BROWSER_PROFILE_DIR",
        profile_env_key,
    ]:
        if not env_key:
            continue
        raw = os.environ.get(env_key)
        if raw:
            candidates.append(Path(raw).expanduser())

    candidates.extend(_candidates_from_thomas_config(profile))

    home = Path.home()
    candidates.extend(
        [
            home / ".thomas" / "browser",
            home / ".thomas" / "browser_data",
            home / ".config" / "thomas" / "browser",
            home / ".config" / "thomas" / "browser_data",
            home / ".local" / "share" / "thomas" / "browser",
            home / ".local" / "share" / "thomas" / "browser_data",
        ]
    )

    attempted: list[str] = []
    for c in candidates:
        try:
            c2 = c.expanduser()
        except (ValueError, OSError, RuntimeError):
            c2 = c
        attempted.append(str(c2))
        if c2.exists() and c2.is_dir():
            return c2.resolve()

    raise BrowserDataStorageSnapshotError(
        "missing_config",
        "Browser data directory could not be resolved. Provide --data-dir or configure THOMAS_BROWSER_DATA_DIR.",
        details={"attempted_paths": attempted, "profile": profile},
    )


def _candidates_from_thomas_config(profile: str | None) -> list[Path]:
    # Best-effort, lazy config discovery. This should never raise.
    candidates: list[Path] = []

    def _as_path(v: Any) -> Path | None:
        if isinstance(v, (str, os.PathLike)):
            return Path(v).expanduser()
        return None

    def _get(obj: Any, key: str) -> Any:
        if obj is None:
            return None
        if isinstance(obj, Mapping):
            return obj.get(key)
        return getattr(obj, key, None)

    def _get_nested(obj: Any, path: Sequence[str]) -> Any:
        cur = obj
        for p in path:
            cur = _get(cur, p)
            if cur is None:
                return None
        return cur

    for mod_name in ("thomas.config", "thomas.settings", "thomas.cli.config"):
        try:
            mod = importlib.import_module(mod_name)
        except (ImportError, ModuleNotFoundError):
            continue

        config_obj = None
        for attr in ("get_config", "load_config", "get_settings", "load_settings", "settings", "CONFIG"):
            try:
                candidate = getattr(mod, attr, None)
            except (AttributeError, TypeError):
                continue
            if candidate is None:
                continue
            if callable(candidate):
                try:
                    config_obj = candidate()
                except (RuntimeError, TypeError):
                    continue
            else:
                config_obj = candidate
            if config_obj is not None:
                break

        if config_obj is None:
            continue

        # Direct keys
        for key_path in (
            ("browser_data_dir",),
            ("browser_user_data_dir",),
            ("browser_profile_dir",),
            ("browser", "data_dir"),
            ("browser", "user_data_dir"),
            ("browser", "profile_dir"),
        ):
            v = _get_nested(config_obj, key_path)
            p = _as_path(v)
            if p:
                candidates.append(p)

        # Profile-specific
        if profile:
            for key_path in (
                ("browser_profiles", profile, "data_dir"),
                ("browser_profiles", profile, "user_data_dir"),
                ("browser_profiles", profile, "profile_dir"),
                ("browser", "profiles", profile, "data_dir"),
                ("browser", "profiles", profile, "user_data_dir"),
                ("browser", "profiles", profile, "profile_dir"),
            ):
                v = _get_nested(config_obj, key_path)
                p = _as_path(v)
                if p:
                    candidates.append(p)

    return candidates


def _validate_data_dir(data_dir: Path) -> None:
    if not data_dir.exists():
        raise BrowserDataStorageSnapshotError(
            "invalid_input",
            "Browser data directory does not exist.",
            details={"data_dir": str(data_dir)},
        )
    if not data_dir.is_dir():
        raise BrowserDataStorageSnapshotError(
            "invalid_input",
            "Browser data directory is not a directory.",
            details={"data_dir": str(data_dir)},
        )


def _resolve_output_path(*, data_dir: Path, output_path: Path | None, overwrite: bool) -> Path:
    if output_path is None:
        stamp = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = Path.cwd() / f"browser_data_storage_snapshot_{stamp}.zip"
    else:
        output_path = Path(output_path).expanduser()

        # If user provided a directory, place the snapshot inside it.
        if output_path.exists() and output_path.is_dir():
            stamp = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output_path = output_path / f"browser_data_storage_snapshot_{stamp}.zip"
        else:
            # Ensure the file name clearly reflects the actual format.
            if output_path.suffix.lower() != ".zip":
                output_path = output_path.with_suffix(".zip")

    output_path = output_path.resolve()

    # Prevent writing inside the data dir (would self-include and/or corrupt).
    try:
        output_path.relative_to(data_dir.resolve())
        raise BrowserDataStorageSnapshotError(
            "invalid_input",
            "Output path must not be inside the browser data directory.",
            details={"output_path": str(output_path), "data_dir": str(data_dir)},
        )
    except ValueError:
        pass

    if output_path.exists() and not overwrite:
        raise BrowserDataStorageSnapshotError(
            "invalid_input",
            "Output path already exists. Use overwrite to replace it.",
            details={"output_path": str(output_path)},
        )

    if output_path.exists() and overwrite and output_path.is_dir():
        raise BrowserDataStorageSnapshotError(
            "invalid_input",
            "Output path points to a directory; expected a file path.",
            details={"output_path": str(output_path)},
        )

    return output_path


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError as e:
        raise BrowserDataStorageSnapshotError(
            "external_failure",
            "Failed to read snapshot archive for hashing.",
            details={"snapshot_path": str(path), "os_error": str(e)},
        ) from e
    return h.hexdigest()


def _make_temp_output_path(final_path: Path) -> Path:
    try:
        fd, tmp = tempfile.mkstemp(
            prefix=f"{final_path.name}.",
            suffix=".tmp",
            dir=str(final_path.parent),
        )
        os.close(fd)
        return Path(tmp)
    except OSError as e:
        raise BrowserDataStorageSnapshotError(
            "external_failure",
            "Failed to allocate temporary file for snapshot.",
            details={"output_dir": str(final_path.parent), "os_error": str(e)},
        ) from e


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        # Best-effort cleanup only.
        pass
