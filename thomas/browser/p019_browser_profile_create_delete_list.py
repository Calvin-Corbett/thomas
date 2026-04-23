"""Browser profile create/delete/list.

A *browser profile* is represented as an on-disk entry under a configurable
*profiles root* directory.

- Normal profiles are **directories** created by Thomas.
- If a **symlink** exists under the profiles root with a valid profile name,
  Thomas will **list** it and can **delete** it (by unlinking the symlink),
  but Thomas will never create symlinked profiles.

This module is intentionally filesystem-only and does not depend on Playwright.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class BrowserProfileError(Exception):
    """Base exception for deterministic browser profile failures."""

    code: str = "browser_profile_error"
    exit_code: int = 1

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class BrowserProfileConfigError(BrowserProfileError):
    code = "browser_profile_config_error"


class InvalidProfileNameError(BrowserProfileError):
    code = "invalid_profile_name"
    exit_code = 2


class ProfileAlreadyExistsError(BrowserProfileError):
    code = "profile_already_exists"


class ProfileNotFoundError(BrowserProfileError):
    code = "profile_not_found"


class BrowserProfileExternalError(BrowserProfileError):
    code = "browser_profile_external_error"


@dataclass(frozen=True, slots=True)
class BrowserProfileRef:
    name: str
    path: Path
    kind: str  # "dir" | "symlink"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "path": str(self.path), "kind": self.kind}


@dataclass(frozen=True, slots=True)
class CreateBrowserProfileRequest:
    name: str
    profiles_root: Path | None = None


@dataclass(frozen=True, slots=True)
class CreateBrowserProfileResult:
    profile: BrowserProfileRef

    def to_dict(self) -> dict[str, Any]:
        return {"profile": self.profile.to_dict()}


@dataclass(frozen=True, slots=True)
class DeleteBrowserProfileRequest:
    name: str
    profiles_root: Path | None = None


@dataclass(frozen=True, slots=True)
class DeleteBrowserProfileResult:
    name: str
    deleted: bool

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "deleted": self.deleted}


@dataclass(frozen=True, slots=True)
class ListBrowserProfilesRequest:
    profiles_root: Path | None = None


@dataclass(frozen=True, slots=True)
class ListBrowserProfilesResult:
    profiles: list[BrowserProfileRef]

    def to_dict(self) -> dict[str, Any]:
        return {"profiles": [p.to_dict() for p in self.profiles], "count": len(self.profiles)}


def _validate_profile_name(name: str) -> str:
    if not isinstance(name, str):
        raise InvalidProfileNameError("Profile name must be a string.")
    cleaned = name.strip()
    if cleaned != name:
        raise InvalidProfileNameError("Profile name may not contain leading/trailing whitespace.")
    if cleaned in {"", ".", ".."}:
        raise InvalidProfileNameError("Profile name may not be empty or '.' or '..'.")
    if "/" in cleaned or "\\" in cleaned:
        raise InvalidProfileNameError("Profile name may not contain path separators.")
    if not _PROFILE_NAME_RE.fullmatch(cleaned):
        raise InvalidProfileNameError("Profile name must match /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.")
    return cleaned


def _try_import_attr(module_name: str, attr_names: Iterable[str]) -> Any | None:
    """Best-effort lookup for an attribute in an optional dependency."""

    try:
        from importlib import import_module

        module = import_module(module_name)
    except (ImportError, ModuleNotFoundError):
        return None

    for attr in attr_names:
        if hasattr(module, attr):
            return getattr(module, attr)
    return None


def _lexists(path: Path) -> bool:
    # os.path.lexists returns True for broken symlinks as well.
    return os.path.lexists(str(path))


def resolve_profiles_root(explicit_root: Path | None = None) -> Path:
    """Resolve the root directory where profiles live.

    Resolution order:
    1) explicit_root (if provided)
    2) env var THOMAS_BROWSER_PROFILES_DIR
    3) value exposed by thomas.tools.browser (if present)
    4) default under THOMAS_HOME / ~/.thomas
    """

    if explicit_root is not None:
        root: Path = explicit_root
    else:
        env_root = os.environ.get("THOMAS_BROWSER_PROFILES_DIR")
        if env_root:
            root = Path(env_root)
        else:
            # Attempt to discover a canonical location from the existing browser tool.
            candidate = _try_import_attr(
                "thomas.tools.browser",
                [
                    "get_profiles_root",
                    "get_profiles_dir",
                    "get_browser_profiles_dir",
                    "browser_profiles_dir",
                    "profiles_root",
                    "profiles_dir",
                    "BROWSER_PROFILES_DIR",
                    "BROWSER_PROFILE_DIR",
                ],
            )
            if candidate is None:
                thomas_home = os.environ.get("THOMAS_HOME")
                if thomas_home:
                    root = Path(thomas_home) / "browser" / "profiles"
                else:
                    root = Path.home() / ".thomas" / "browser" / "profiles"
            else:
                root = Path(candidate() if callable(candidate) else candidate)

    # Normalize as an absolute path without requiring it to exist yet.
    root = Path(os.path.abspath(str(root.expanduser())))

    if root.exists() and not root.is_dir():
        raise BrowserProfileConfigError(f"Profiles root is not a directory: {root}")

    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise BrowserProfileExternalError(f"Failed to ensure profiles root directory exists: {root}") from e

    return root


def _profile_path(root: Path, name: str) -> Path:
    # name already validated to not contain path separators
    return root / name


def create_browser_profile(request: CreateBrowserProfileRequest) -> CreateBrowserProfileResult:
    name = _validate_profile_name(request.name)
    root = resolve_profiles_root(request.profiles_root)
    path = _profile_path(root, name)

    if _lexists(path):
        raise ProfileAlreadyExistsError(f"Profile already exists: {name}")

    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise ProfileAlreadyExistsError(f"Profile already exists: {name}")
    except OSError as e:
        raise BrowserProfileExternalError(f"Failed to create profile '{name}'.") from e

    return CreateBrowserProfileResult(profile=BrowserProfileRef(name=name, path=path, kind="dir"))


def list_browser_profiles(request: ListBrowserProfilesRequest) -> ListBrowserProfilesResult:
    root = resolve_profiles_root(request.profiles_root)
    try:
        entries = list(root.iterdir())
    except OSError as e:
        raise BrowserProfileExternalError(f"Failed to list profiles under '{root}'.") from e

    profiles: list[BrowserProfileRef] = []
    for p in entries:
        if not _PROFILE_NAME_RE.fullmatch(p.name):
            continue
        try:
            if p.is_symlink():
                kind = "symlink"
            elif p.is_dir():
                kind = "dir"
            else:
                continue
        except OSError as e:
            raise BrowserProfileExternalError(f"Failed to inspect profile entry: {p}") from e

        profiles.append(BrowserProfileRef(name=p.name, path=p, kind=kind))

    profiles.sort(key=lambda r: r.name.lower())
    return ListBrowserProfilesResult(profiles=profiles)


def delete_browser_profile(request: DeleteBrowserProfileRequest) -> DeleteBrowserProfileResult:
    name = _validate_profile_name(request.name)
    root = resolve_profiles_root(request.profiles_root)
    path = _profile_path(root, name)

    if not _lexists(path):
        raise ProfileNotFoundError(f"Profile not found: {name}")

    try:
        if path.is_symlink():
            # Unlink the symlink itself (do not follow).
            path.unlink()
            return DeleteBrowserProfileResult(name=name, deleted=True)

        if path.is_dir():
            shutil.rmtree(path)
            return DeleteBrowserProfileResult(name=name, deleted=True)
    except OSError as e:
        raise BrowserProfileExternalError(f"Failed to delete profile '{name}'.") from e

    raise BrowserProfileConfigError(f"Profile path is not a directory or symlink: {path}")


__all__ = [
    "BrowserProfileError",
    "BrowserProfileConfigError",
    "BrowserProfileExternalError",
    "InvalidProfileNameError",
    "ProfileAlreadyExistsError",
    "ProfileNotFoundError",
    "BrowserProfileRef",
    "CreateBrowserProfileRequest",
    "CreateBrowserProfileResult",
    "DeleteBrowserProfileRequest",
    "DeleteBrowserProfileResult",
    "ListBrowserProfilesRequest",
    "ListBrowserProfilesResult",
    "resolve_profiles_root",
    "create_browser_profile",
    "list_browser_profiles",
    "delete_browser_profile",
]
