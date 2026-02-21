"""Browser upload helper.

This module stages a local file into a directory that is expected to be readable by
the browser runtime used by Thomas (for example, a shared workspace directory that
a live browser session can access).

The helper provides:
- A small, explicit input/output contract for staging an upload.
- Deterministic error codes for invalid input, missing configuration, and I/O failures.
- JSON-serializable payload helpers for automation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import inspect
import os
from pathlib import Path
import secrets
from typing import Any, Mapping, Optional, TypedDict


_DEFAULT_UPLOAD_DIR_ENV_KEYS: tuple[str, ...] = (
    "THOMAS_BROWSER_UPLOAD_DIR",
    "THOMAS_BROWSER_UPLOAD_ROOT",
)

_FALLBACK_WORKSPACE_ENV_KEYS: tuple[str, ...] = (
    "THOMAS_WORKSPACE",
    "THOMAS_PROJECT_ROOT",
    "THOMAS_HOME",
)

# Best-effort integration points with the existing Thomas codebase. We only look
# for simple constants / zero-arg callables to avoid forcing heavy imports.
_THOMAS_MODULE_UPLOAD_DIR_ATTRS: tuple[str, ...] = (
    "BROWSER_UPLOAD_DIR",
    "UPLOAD_DIR",
    "UPLOAD_ROOT",
    "DEFAULT_UPLOAD_DIR",
    "DEFAULT_BROWSER_UPLOAD_DIR",
)
_THOMAS_MODULE_UPLOAD_DIR_FUNCS: tuple[str, ...] = (
    "get_browser_upload_dir",
    "get_upload_dir",
    "default_upload_dir",
)


class BrowserUploadHelperError(Exception):
    """Base exception with a deterministic error code and structured details."""

    code: str
    details: dict[str, Any]

    def __init__(self, code: str, message: str, *, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    @property
    def message(self) -> str:
        return str(self)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class BrowserUploadInvalidInputError(BrowserUploadHelperError):
    """Raised when the user input is invalid."""


class BrowserUploadMissingConfigError(BrowserUploadHelperError):
    """Raised when required configuration is missing."""


class BrowserUploadExternalFailureError(BrowserUploadHelperError):
    """Raised for external failures (I/O, permissions, etc.)."""


@dataclass(frozen=True)
class BrowserUploadRequest:
    """Input contract for staging a file for a browser upload."""

    source_path: Path
    destination_dir: Path | None = None
    destination_name: str | None = None
    overwrite: bool = False
    make_parents: bool = True
    max_bytes: int | None = None
    compute_sha256: bool = True
    chunk_size: int = 1024 * 1024
    fsync: bool = False


@dataclass(frozen=True)
class BrowserUploadResult:
    """Output contract for staging a file for a browser upload."""

    source_path: Path
    staged_path: Path
    bytes_copied: int
    sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        source = Path(self.source_path).as_posix()
        staged = Path(self.staged_path).as_posix()
        return {
            "source_path": source,
            "staged_path": staged,
            "bytes_copied": self.bytes_copied,
            "sha256": self.sha256,
        }


class BrowserUploadJsonSuccess(TypedDict):
    ok: bool
    result: dict[str, Any]


class BrowserUploadJsonFailure(TypedDict):
    ok: bool
    error: dict[str, Any]


BROWSER_UPLOAD_RESULT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["source_path", "staged_path", "bytes_copied", "sha256"],
    "properties": {
        "source_path": {"type": "string"},
        "staged_path": {"type": "string"},
        "bytes_copied": {"type": "integer", "minimum": 0},
        "sha256": {"type": ["string", "null"]},
    },
}

BROWSER_UPLOAD_ERROR_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["code", "message"],
    "properties": {
        "code": {"type": "string"},
        "message": {"type": "string"},
        "details": {"type": "object"},
    },
}


def _maybe_path(value: object) -> Path | None:
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value)
    return None


def _try_resolve_from_thomas_modules() -> Path | None:
    """Best-effort lookup from existing Thomas modules.

    We avoid importing deep dependency trees by only checking a small set of known
    module paths and pulling simple attributes/zero-arg callables.
    """
    for mod_name in ("thomas.cli.live_browser", "thomas.tools.browser"):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue

        for attr in _THOMAS_MODULE_UPLOAD_DIR_ATTRS:
            if hasattr(mod, attr):
                candidate = _maybe_path(getattr(mod, attr))
                if candidate is not None:
                    return candidate.expanduser()

        for fn_name in _THOMAS_MODULE_UPLOAD_DIR_FUNCS:
            fn = getattr(mod, fn_name, None)
            if not callable(fn):
                continue
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                continue

            # Only call if it can be invoked with no args.
            has_required_params = any(
                p.default is inspect.Signature.empty
                and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                for p in sig.parameters.values()
            )
            if has_required_params:
                continue

            try:
                candidate = _maybe_path(fn())
            except Exception:
                continue
            if candidate is not None:
                return candidate.expanduser()

    return None


def resolve_default_destination_dir(*, env: Mapping[str, str] | None = None) -> Path:
    """Resolve the default staging directory from configuration.

    Resolution order:
    1) THOMAS_BROWSER_UPLOAD_DIR / THOMAS_BROWSER_UPLOAD_ROOT
    2) THOMAS_WORKSPACE / THOMAS_PROJECT_ROOT / THOMAS_HOME, with a "browser_uploads" suffix
    3) Best-effort values exposed by `thomas.cli.live_browser` or `thomas.tools.browser`

    Raises:
        BrowserUploadMissingConfigError if no default can be determined.
    """
    env_map = os.environ if env is None else env

    for key in _DEFAULT_UPLOAD_DIR_ENV_KEYS:
        raw = env_map.get(key)
        if raw and raw.strip():
            return Path(raw).expanduser()

    for key in _FALLBACK_WORKSPACE_ENV_KEYS:
        raw = env_map.get(key)
        if raw and raw.strip():
            return Path(raw).expanduser() / "browser_uploads"

    candidate = _try_resolve_from_thomas_modules()
    if candidate is not None:
        return candidate

    raise BrowserUploadMissingConfigError(
        "missing_upload_directory",
        "No browser upload directory configured. Provide destination_dir or set THOMAS_BROWSER_UPLOAD_DIR.",
        details={
            "checked_env": list(_DEFAULT_UPLOAD_DIR_ENV_KEYS + _FALLBACK_WORKSPACE_ENV_KEYS),
            "checked_modules": ["thomas.cli.live_browser", "thomas.tools.browser"],
        },
    )


def _validate_destination_name(name: str) -> None:
    # Keep it intentionally strict: the destination is a filename, not a path.
    if not name or name.strip() != name:
        raise BrowserUploadInvalidInputError(
            "invalid_destination_name",
            "Destination name must be a non-empty filename.",
            details={"destination_name": name},
        )
    if Path(name).name != name or "/" in name or "\\" in name:
        raise BrowserUploadInvalidInputError(
            "invalid_destination_name",
            "Destination name must not contain path separators.",
            details={"destination_name": name},
        )


def _sha256_of_file(path: Path, *, chunk_size: int) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def stage_file_for_browser(request: BrowserUploadRequest, *, env: Mapping[str, str] | None = None) -> BrowserUploadResult:
    """Stage a local file into a browser-accessible directory.

    Args:
        request: BrowserUploadRequest
        env: Optional environment mapping, useful for testing.

    Returns:
        BrowserUploadResult

    Raises:
        BrowserUploadHelperError subclasses with deterministic error codes.
    """
    src = Path(request.source_path)

    if request.chunk_size <= 0:
        raise BrowserUploadInvalidInputError(
            "invalid_chunk_size",
            "chunk_size must be > 0.",
            details={"chunk_size": request.chunk_size},
        )

    if not src.exists():
        raise BrowserUploadInvalidInputError(
            "source_not_found",
            "Source file does not exist.",
            details={"source_path": str(src)},
        )
    if not src.is_file():
        raise BrowserUploadInvalidInputError(
            "source_not_file",
            "Source path is not a file.",
            details={"source_path": str(src)},
        )

    if request.max_bytes is not None:
        if request.max_bytes < 0:
            raise BrowserUploadInvalidInputError(
                "invalid_max_bytes",
                "max_bytes must be >= 0.",
                details={"max_bytes": request.max_bytes},
            )
        try:
            size = src.stat().st_size
        except OSError as e:  # pragma: no cover
            raise BrowserUploadExternalFailureError(
                "stat_failed",
                "Unable to stat source file.",
                details={"source_path": str(src), "errno": getattr(e, "errno", None)},
            ) from e
        if size > request.max_bytes:
            raise BrowserUploadInvalidInputError(
                "file_too_large",
                "Source file exceeds max_bytes.",
                details={"source_path": str(src), "size": size, "max_bytes": request.max_bytes},
            )

    dest_dir = request.destination_dir
    if dest_dir is None:
        dest_dir = resolve_default_destination_dir(env=env)

    dest_dir = Path(dest_dir).expanduser()

    if dest_dir.exists() and not dest_dir.is_dir():
        raise BrowserUploadExternalFailureError(
            "destination_not_directory",
            "Destination path exists but is not a directory.",
            details={"destination_dir": str(dest_dir)},
        )

    if request.make_parents:
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise BrowserUploadExternalFailureError(
                "mkdir_failed",
                "Unable to create destination directory.",
                details={"destination_dir": str(dest_dir), "errno": getattr(e, "errno", None)},
            ) from e
    else:
        if not dest_dir.exists():
            raise BrowserUploadExternalFailureError(
                "destination_missing",
                "Destination directory does not exist.",
                details={"destination_dir": str(dest_dir)},
            )

    dest_name = request.destination_name or src.name
    _validate_destination_name(dest_name)

    staged_path = dest_dir / dest_name

    # If the destination resolves to the same file as the source, treat as a no-op.
    try:
        same_file = src.resolve() == staged_path.resolve()
    except Exception:
        same_file = False
    if same_file:
        sha = _sha256_of_file(src, chunk_size=request.chunk_size) if request.compute_sha256 else None
        return BrowserUploadResult(
            source_path=src,
            staged_path=staged_path,
            bytes_copied=0,
            sha256=sha,
        )

    if staged_path.exists() and staged_path.is_dir():
        raise BrowserUploadExternalFailureError(
            "destination_is_directory",
            "Destination path exists and is a directory.",
            details={"staged_path": str(staged_path)},
        )

    if staged_path.exists() and not request.overwrite:
        raise BrowserUploadExternalFailureError(
            "destination_exists",
            "Destination file already exists (use overwrite to replace).",
            details={"staged_path": str(staged_path)},
        )

    tmp_name = f".{dest_name}.tmp.{secrets.token_hex(8)}"
    tmp_path = dest_dir / tmp_name

    sha256_hasher = hashlib.sha256() if request.compute_sha256 else None
    bytes_copied = 0
    try:
        with src.open("rb") as fsrc, tmp_path.open("wb") as fdst:
            while True:
                chunk = fsrc.read(request.chunk_size)
                if not chunk:
                    break
                if request.max_bytes is not None and bytes_copied + len(chunk) > request.max_bytes:
                    # Defensive: even if size check passed, don't allow growth during copy.
                    raise BrowserUploadInvalidInputError(
                        "file_too_large",
                        "Source file exceeds max_bytes during copy.",
                        details={"source_path": str(src), "max_bytes": request.max_bytes},
                    )
                fdst.write(chunk)
                bytes_copied += len(chunk)
                if sha256_hasher is not None:
                    sha256_hasher.update(chunk)

            fdst.flush()
            if request.fsync:
                os.fsync(fdst.fileno())

        os.replace(tmp_path, staged_path)

        # Best-effort: keep perms + timestamps close to the source for a smoother UX.
        try:
            st = src.stat()
            os.chmod(staged_path, st.st_mode & 0o777)
            os.utime(staged_path, (st.st_atime, st.st_mtime))
        except Exception:
            pass
    except BrowserUploadHelperError:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise
    except OSError as e:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise BrowserUploadExternalFailureError(
            "copy_failed",
            "Failed to stage file due to an I/O error.",
            details={
                "source_path": str(src),
                "staged_path": str(staged_path),
                "errno": getattr(e, "errno", None),
                "exception": type(e).__name__,
            },
        ) from e

    return BrowserUploadResult(
        source_path=src,
        staged_path=staged_path,
        bytes_copied=bytes_copied,
        sha256=sha256_hasher.hexdigest() if sha256_hasher is not None else None,
    )


def make_success_payload(result: BrowserUploadResult) -> BrowserUploadJsonSuccess:
    return {"ok": True, "result": result.to_dict()}


def make_failure_payload(error: BrowserUploadHelperError) -> BrowserUploadJsonFailure:
    return {"ok": False, "error": error.to_dict()}
