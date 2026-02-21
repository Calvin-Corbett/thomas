"""Browser cookie export/import helpers.

This module is intentionally self-contained and provides:

- A small, versioned cookies file format (JSON)

- Optional zip wrapping for portability (a `cookies.json` member inside a `.zip`)

- A backend protocol + a Playwright-backed implementation

- Deterministic, machine-readable errors for invalid input, missing config,
  and external failures.

The primary entrypoints are:

- export_cookies(CookiesExportRequest, backend=...)
- import_cookies(CookiesImportRequest, backend=...)

"""

from __future__ import annotations

import inspect
import importlib
import json
import os
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Optional, Protocol, Sequence, TypedDict, Union, cast


# -------------------------
# Public data contracts
# -------------------------


class Cookie(TypedDict, total=False):
    """A cookie in (mostly) Playwright-compatible dict shape."""

    name: str
    value: str

    # Either url OR (domain+path) must be present for import.
    url: str
    domain: str
    path: str

    expires: float
    httpOnly: bool
    secure: bool
    sameSite: str  # "Lax" | "Strict" | "None" (Playwright accepts these strings)


CookiesFormat = Literal["json", "zip"]


@dataclass(frozen=True)
class CookiesExportRequest:
    """Input contract for exporting cookies."""

    output_file: Path
    profile_dir: Optional[Path] = None
    url: Optional[str] = None
    output_format: Optional[CookiesFormat] = None  # None => infer from output_file suffix


@dataclass(frozen=True)
class CookiesExportResult:
    """Output contract for exporting cookies."""

    output_file: Path
    cookie_count: int
    schema: str
    exported_at: str
    url: Optional[str]
    output_format: CookiesFormat
    archive_member: Optional[str]


@dataclass(frozen=True)
class CookiesImportRequest:
    """Input contract for importing cookies."""

    input_file: Path
    profile_dir: Optional[Path] = None
    input_format: Optional[CookiesFormat] = None  # None => infer from file signature/ext


@dataclass(frozen=True)
class CookiesImportResult:
    """Output contract for importing cookies."""

    input_file: Path
    cookie_count: int
    schema: str
    input_format: CookiesFormat
    archive_member: Optional[str]


class CookiesBackend(Protocol):
    """Backend protocol for reading/writing cookies from a browser profile."""

    def list_cookies(self, url: Optional[str] = None) -> list[Cookie]:
        raise NotImplementedError

    def add_cookies(self, cookies: Sequence[Cookie]) -> None:
        raise NotImplementedError


# -------------------------
# Deterministic errors
# -------------------------


ErrorCode = Literal[
    "INVALID_INPUT",
    "MISSING_CONFIG",
    "EXTERNAL_FAILURE",
]


class CookiesTransferError(RuntimeError):
    """Base error with a deterministic error code and optional details."""

    code: ErrorCode
    details: dict[str, Any]

    def __init__(self, code: ErrorCode, message: str, *, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": self.details,
        }


class InvalidInputError(CookiesTransferError):
    def __init__(self, message: str, *, details: Optional[dict[str, Any]] = None):
        super().__init__("INVALID_INPUT", message, details=details)


class MissingConfigError(CookiesTransferError):
    def __init__(self, message: str, *, details: Optional[dict[str, Any]] = None):
        super().__init__("MISSING_CONFIG", message, details=details)


class ExternalFailureError(CookiesTransferError):
    def __init__(self, message: str, *, details: Optional[dict[str, Any]] = None):
        super().__init__("EXTERNAL_FAILURE", message, details=details)


# -------------------------
# Cookies file format
# -------------------------


COOKIES_SCHEMA_V1 = "thomas.browser.cookies.v1"
COOKIES_ARCHIVE_MEMBER = "cookies.json"


class CookiesFileV1(TypedDict):
    schema: str
    exported_at: str
    cookies: list[Cookie]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_parent_dir(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # pragma: no cover
        raise ExternalFailureError(
            "Failed to create output directory",
            details={"path": str(path.parent), "error": type(e).__name__},
        ) from e


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes atomically (best-effort) to avoid partial files."""
    _ensure_parent_dir(path)

    fd: Optional[int] = None
    tmp_path: Optional[str] = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "wb") as f:
            fd = None
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    except CookiesTransferError:
        raise
    except Exception as e:
        raise ExternalFailureError(
            "Failed to write cookies file",
            details={"path": str(path), "error": type(e).__name__},
        ) from e
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _dump_json_file(path: Path, payload: Any) -> None:
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write_bytes(path, data)


def _load_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise InvalidInputError("Cookies file not found", details={"path": str(path)}) from e
    except Exception as e:
        raise ExternalFailureError(
            "Failed to read cookies file",
            details={"path": str(path), "error": type(e).__name__},
        ) from e


def _load_json_file(path: Path) -> Any:
    raw = _load_text_file(path)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise InvalidInputError(
            "Cookies file is not valid JSON",
            details={"path": str(path), "line": e.lineno, "col": e.colno},
        ) from e


def _zip_write_payload(path: Path, payload: Any, *, member_name: str = COOKIES_ARCHIVE_MEMBER) -> None:
    """Write payload as a JSON file inside a zip archive, atomically."""
    _ensure_parent_dir(path)
    json_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    fd: Optional[int] = None
    tmp_path: Optional[str] = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        os.close(fd)
        fd = None

        with zipfile.ZipFile(tmp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(member_name, json_text)

        os.replace(tmp_path, path)
        tmp_path = None
    except CookiesTransferError:
        raise
    except Exception as e:
        raise ExternalFailureError(
            "Failed to write cookies zip",
            details={"path": str(path), "error": type(e).__name__},
        ) from e
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _zip_read_payload(path: Path) -> tuple[Any, str]:
    """Read and parse cookies JSON payload from a zip archive.

    Returns (payload, member_name).
    """
    try:
        with zipfile.ZipFile(path, mode="r") as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if COOKIES_ARCHIVE_MEMBER in names:
                member = COOKIES_ARCHIVE_MEMBER
            else:
                json_members = [n for n in names if n.lower().endswith(".json")]
                if len(json_members) == 1:
                    member = json_members[0]
                elif len(json_members) == 0:
                    raise InvalidInputError(
                        "Zip archive does not contain a cookies JSON file",
                        details={"path": str(path), "expected_member": COOKIES_ARCHIVE_MEMBER, "members": names[:50]},
                    )
                else:
                    raise InvalidInputError(
                        "Zip archive contains multiple JSON files; ambiguous",
                        details={"path": str(path), "json_members": json_members[:50]},
                    )
            raw_bytes = zf.read(member)
    except FileNotFoundError as e:
        raise InvalidInputError("Cookies file not found", details={"path": str(path)}) from e
    except zipfile.BadZipFile as e:
        raise InvalidInputError("Cookies zip is not a valid zip archive", details={"path": str(path)}) from e
    except CookiesTransferError:
        raise
    except Exception as e:
        raise ExternalFailureError(
            "Failed to read cookies zip",
            details={"path": str(path), "error": type(e).__name__},
        ) from e

    try:
        raw = raw_bytes.decode("utf-8")
    except Exception as e:
        raise InvalidInputError(
            "Cookies JSON inside zip is not UTF-8 text",
            details={"path": str(path), "member": member},
        ) from e

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise InvalidInputError(
            "Cookies JSON inside zip is not valid JSON",
            details={"path": str(path), "member": member, "line": e.lineno, "col": e.colno},
        ) from e

    return payload, member


def _peek_file_signature(path: Path, n: int = 4) -> bytes:
    try:
        with path.open("rb") as f:
            return f.read(n)
    except FileNotFoundError as e:
        raise InvalidInputError("Cookies file not found", details={"path": str(path)}) from e
    except Exception as e:
        raise ExternalFailureError(
            "Failed to read cookies file",
            details={"path": str(path), "error": type(e).__name__},
        ) from e


def _infer_export_format(path: Path, requested: Optional[CookiesFormat]) -> CookiesFormat:
    if requested is not None:
        if requested not in ("json", "zip"):
            raise InvalidInputError("Invalid output format", details={"format": requested})
        return requested
    if path.suffix.lower() == ".zip":
        return "zip"
    return "json"


def _infer_import_format(path: Path, requested: Optional[CookiesFormat]) -> CookiesFormat:
    if requested is not None:
        if requested not in ("json", "zip"):
            raise InvalidInputError("Invalid input format", details={"format": requested})
        return requested

    if path.suffix.lower() == ".zip":
        return "zip"

    sig = _peek_file_signature(path, 4)
    if sig.startswith(b"PK\x03\x04") or sig.startswith(b"PK\x05\x06") or sig.startswith(b"PK\x07\x08"):
        return "zip"
    return "json"


def _synthesize_url_from_domain_path(cookie: Mapping[str, Any]) -> Optional[str]:
    domain = cookie.get("domain")
    path = cookie.get("path")
    if not isinstance(domain, str) or not domain:
        return None
    if not isinstance(path, str) or not path:
        path = "/"
    if not path.startswith("/"):
        path = "/" + path

    # Prefer https unless explicitly non-secure.
    secure = cookie.get("secure")
    scheme = "http" if secure is False else "https"

    host = domain.lstrip(".")
    if not host:
        return None
    return f"{scheme}://{host}{path}"


_ALLOWED_COOKIE_KEYS = {
    "name",
    "value",
    "url",
    "domain",
    "path",
    "expires",
    "httpOnly",
    "secure",
    "sameSite",
}


def _normalize_same_site(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInputError("Cookie field 'sameSite' must be a string")
    v = value.strip().lower()
    mapping = {"lax": "Lax", "strict": "Strict", "none": "None"}
    if v in mapping:
        return mapping[v]
    raise InvalidInputError("Cookie field 'sameSite' must be one of: Lax, Strict, None", details={"sameSite": value})


def _normalize_cookie(raw_cookie: Mapping[str, Any]) -> Cookie:
    if not isinstance(raw_cookie, Mapping):
        raise InvalidInputError("Cookie entry must be an object")

    name = raw_cookie.get("name")
    value = raw_cookie.get("value")
    if not isinstance(name, str) or not name:
        raise InvalidInputError("Cookie is missing a valid 'name'")
    if not isinstance(value, str):
        raise InvalidInputError("Cookie is missing a valid 'value'")

    cookie: dict[str, Any] = {
        "name": name,
        "value": value,
    }

    # Determine scope.
    url = raw_cookie.get("url")
    if isinstance(url, str) and url:
        if not (url.startswith("http://") or url.startswith("https://")):
            raise InvalidInputError(
                "Cookie 'url' must start with http:// or https://", details={"url": url, "name": name}
            )
        cookie["url"] = url
    else:
        synthesized = _synthesize_url_from_domain_path(raw_cookie)
        if synthesized is None:
            raise InvalidInputError(
                "Cookie must include 'url' or ('domain' and 'path')",
                details={"cookie": {"name": name}},
            )
        cookie["url"] = synthesized

    # Optional attributes with type checks.
    if "expires" in raw_cookie and raw_cookie.get("expires") is not None:
        exp = raw_cookie.get("expires")
        if not isinstance(exp, (int, float)):
            raise InvalidInputError("Cookie field 'expires' must be a number", details={"expires": exp, "name": name})
        cookie["expires"] = float(exp)

    if "httpOnly" in raw_cookie and raw_cookie.get("httpOnly") is not None:
        v = raw_cookie.get("httpOnly")
        if not isinstance(v, bool):
            raise InvalidInputError("Cookie field 'httpOnly' must be boolean", details={"httpOnly": v, "name": name})
        cookie["httpOnly"] = v

    if "secure" in raw_cookie and raw_cookie.get("secure") is not None:
        v = raw_cookie.get("secure")
        if not isinstance(v, bool):
            raise InvalidInputError("Cookie field 'secure' must be boolean", details={"secure": v, "name": name})
        cookie["secure"] = v

    if "sameSite" in raw_cookie and raw_cookie.get("sameSite") is not None:
        cookie["sameSite"] = _normalize_same_site(raw_cookie.get("sameSite"))

    # Keep domain/path if present and valid strings (harmless even if url is present).
    if isinstance(raw_cookie.get("domain"), str) and raw_cookie.get("domain"):
        cookie["domain"] = raw_cookie.get("domain")
    if isinstance(raw_cookie.get("path"), str) and raw_cookie.get("path"):
        cookie["path"] = raw_cookie.get("path")

    cookie = {k: v for k, v in cookie.items() if k in _ALLOWED_COOKIE_KEYS and v is not None}
    return cast(Cookie, cookie)


def _extract_cookies_from_payload(payload: Any) -> tuple[str, list[Cookie]]:
    """Return (schema, cookies) from a payload.

    Supported payload shapes:
    - Thomas v1 file: {"schema": "thomas.browser.cookies.v1", "cookies": [...], ...}
    - Playwright storage state: {"cookies": [...], "origins": [...]}  (schema reported as "playwright.storage_state")
    - Raw cookies list: [...] (schema reported as "cookies.list")
    """
    if isinstance(payload, list):
        cookies_raw = payload
        schema = "cookies.list"
    elif isinstance(payload, dict):
        cookies_raw = payload.get("cookies")
        schema_val = payload.get("schema")
        if isinstance(schema_val, str) and schema_val:
            schema = schema_val
        else:
            schema = "playwright.storage_state"
    else:
        raise InvalidInputError("Cookies payload must be a JSON array or object")

    if not isinstance(cookies_raw, list):
        raise InvalidInputError("Cookies payload must contain a 'cookies' list")

    cookies: list[Cookie] = []
    for raw_cookie in cookies_raw:
        if not isinstance(raw_cookie, Mapping):
            raise InvalidInputError("Cookie entry must be an object")
        cookies.append(_normalize_cookie(cast(Mapping[str, Any], raw_cookie)))

    return schema, cookies


# -------------------------
# Playwright backend
# -------------------------


class PlaywrightCookiesBackend:
    """A backend that reads/writes cookies via Playwright persistent context."""

    def __init__(self, profile_dir: Path, *, headless: bool = True):
        self.profile_dir = profile_dir
        self.headless = headless
        self._pw = None
        self._context = None

    def __enter__(self) -> "PlaywrightCookiesBackend":
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as e:
            raise MissingConfigError(
                "Playwright is not installed; cannot access browser cookies",
                details={"error": type(e).__name__},
            ) from e

        try:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise ExternalFailureError(
                "Failed to initialize browser profile directory",
                details={"path": str(self.profile_dir), "error": type(e).__name__},
            ) from e

        try:
            self._pw = sync_playwright().start()
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
            )
        except Exception as e:
            try:
                if self._pw is not None:
                    self._pw.stop()
            except Exception:
                pass

            raise ExternalFailureError(
                "Failed to launch browser context",
                details={"error": type(e).__name__},
            ) from e

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._context is not None:
                self._context.close()
        finally:
            if self._pw is not None:
                try:
                    self._pw.stop()
                except Exception:
                    pass

    def list_cookies(self, url: Optional[str] = None) -> list[Cookie]:
        assert self._context is not None
        try:
            if url:
                cookies = self._context.cookies([url])
            else:
                cookies = self._context.cookies()
        except Exception as e:
            raise ExternalFailureError("Failed to read cookies from browser", details={"error": type(e).__name__}) from e

        normalized: list[Cookie] = []
        for c in cookies:
            if isinstance(c, Mapping):
                c_map = cast(Mapping[str, Any], c)
                cookie: dict[str, Any] = {k: c_map.get(k) for k in _ALLOWED_COOKIE_KEYS if k in c_map}
                if isinstance(c_map.get("name"), str):
                    cookie["name"] = c_map["name"]
                if isinstance(c_map.get("value"), str):
                    cookie["value"] = c_map["value"]
                normalized.append(cast(Cookie, {k: v for k, v in cookie.items() if v is not None}))
        return normalized

    def add_cookies(self, cookies: Sequence[Cookie]) -> None:
        assert self._context is not None
        try:
            self._context.add_cookies(list(cookies))
        except Exception as e:
            raise ExternalFailureError("Failed to write cookies to browser", details={"error": type(e).__name__}) from e


def _resolve_profile_dir(profile_dir: Optional[Path]) -> Path:
    """Resolve the profile directory.

    Resolution order:
    1. Explicit profile_dir argument
    2. Environment variable THOMAS_BROWSER_PROFILE_DIR

    We intentionally avoid guessing additional locations to prevent writing into
    unexpected directories.
    """
    if profile_dir is not None:
        return profile_dir

    env = os.environ.get("THOMAS_BROWSER_PROFILE_DIR")
    if env:
        return Path(env)

    # Best-effort integration with the existing Thomas codebase.
    def _try_call_zero_arg(obj: Any) -> Optional[Path]:
        if not callable(obj):
            return None
        try:
            sig = inspect.signature(obj)
        except Exception:
            sig = None
        if sig is not None and any(
            p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            for p in sig.parameters.values()
        ):
            return None
        try:
            value = obj()
        except Exception:
            return None
        if isinstance(value, Path):
            return value
        if isinstance(value, str) and value:
            return Path(value)
        return None

    def _try_attr(mod_name: str, attr_names: Sequence[str]) -> Optional[Path]:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            return None
        for attr in attr_names:
            val = getattr(mod, attr, None)
            if isinstance(val, Path):
                return val
            if isinstance(val, str) and val:
                return Path(val)
            called = _try_call_zero_arg(val)
            if called is not None:
                return called
        return None

    candidate_modules: list[tuple[str, list[str]]] = [
        (
            "thomas.cli.live_browser",
            [
                "default_profile_dir",
                "get_default_profile_dir",
                "get_profile_dir",
                "get_browser_profile_dir",
                "DEFAULT_PROFILE_DIR",
                "DEFAULT_BROWSER_PROFILE_DIR",
                "BROWSER_PROFILE_DIR",
            ],
        ),
        (
            "thomas.tools.browser",
            [
                "default_profile_dir",
                "get_default_profile_dir",
                "get_profile_dir",
                "get_browser_profile_dir",
                "DEFAULT_PROFILE_DIR",
                "DEFAULT_BROWSER_PROFILE_DIR",
                "BROWSER_PROFILE_DIR",
            ],
        ),
    ]
    for mod_name, attrs in candidate_modules:
        resolved = _try_attr(mod_name, attrs)
        if resolved is not None:
            return resolved

    raise MissingConfigError(
        "No browser profile directory provided",
        details={
            "expected": [
                "profile_dir argument",
                "THOMAS_BROWSER_PROFILE_DIR env",
                "thomas.cli.live_browser (default profile dir)",
                "thomas.tools.browser (default profile dir)",
            ]
        },
    )


def export_cookies(request: CookiesExportRequest, *, backend: Optional[CookiesBackend] = None) -> CookiesExportResult:
    """Export cookies from the given backend/profile to a JSON file or zip archive."""
    output_format = _infer_export_format(request.output_file, request.output_format)

    if backend is None:
        profile_dir = _resolve_profile_dir(request.profile_dir)
        with PlaywrightCookiesBackend(profile_dir) as pw_backend:
            return export_cookies(request, backend=pw_backend)

    try:
        cookies = backend.list_cookies(url=request.url)
    except CookiesTransferError:
        raise
    except Exception as e:
        raise ExternalFailureError("Failed to export cookies", details={"error": type(e).__name__}) from e

    payload: CookiesFileV1 = {
        "schema": COOKIES_SCHEMA_V1,
        "exported_at": _utc_now_iso(),
        "cookies": cast(list[Cookie], cookies),
    }

    archive_member: Optional[str] = None
    if output_format == "json":
        _dump_json_file(request.output_file, payload)
    else:
        archive_member = COOKIES_ARCHIVE_MEMBER
        _zip_write_payload(request.output_file, payload, member_name=archive_member)

    return CookiesExportResult(
        output_file=request.output_file,
        cookie_count=len(cookies),
        schema=COOKIES_SCHEMA_V1,
        exported_at=payload["exported_at"],
        url=request.url,
        output_format=output_format,
        archive_member=archive_member,
    )


def import_cookies(request: CookiesImportRequest, *, backend: Optional[CookiesBackend] = None) -> CookiesImportResult:
    """Import cookies from a JSON file or zip archive into the given backend/profile."""
    input_format = _infer_import_format(request.input_file, request.input_format)

    if backend is None:
        profile_dir = _resolve_profile_dir(request.profile_dir)
        with PlaywrightCookiesBackend(profile_dir) as pw_backend:
            return import_cookies(request, backend=pw_backend)

    archive_member: Optional[str] = None
    if input_format == "zip":
        payload, archive_member = _zip_read_payload(request.input_file)
    else:
        payload = _load_json_file(request.input_file)

    schema, cookies = _extract_cookies_from_payload(payload)

    try:
        backend.add_cookies(cookies)
    except CookiesTransferError:
        raise
    except Exception as e:
        raise ExternalFailureError("Failed to import cookies", details={"error": type(e).__name__}) from e

    return CookiesImportResult(
        input_file=request.input_file,
        cookie_count=len(cookies),
        schema=schema,
        input_format=input_format,
        archive_member=archive_member,
    )


def result_to_dict(result: Union[CookiesExportResult, CookiesImportResult]) -> dict[str, Any]:
    """Convert result dataclasses to JSON-serializable dict."""
    d = asdict(result)
    for k, v in list(d.items()):
        if isinstance(v, Path):
            d[k] = str(v)
    return d
