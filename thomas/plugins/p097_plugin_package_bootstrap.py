from __future__ import annotations

"""Plugin package bootstrap for Thomas.

This module generates a minimal, importable Python package implementing a Thomas
plugin skeleton. It is intended for automation and local developer tooling.

The generated package is *not* automatically installed; it simply writes files
to disk. Installation/distribution decisions are left to the caller.

Deterministic errors are provided for reliable automation.
"""

import keyword
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


# -----------------------------
# Deterministic errors
# -----------------------------


class PluginBootstrapError(RuntimeError):
    """Deterministic error with a stable machine-readable code."""

    def __init__(self, *, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class InvalidInputError(PluginBootstrapError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="invalid_input", message=message, details=details)


class AlreadyExistsError(PluginBootstrapError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="already_exists", message=message, details=details)


class ExternalFailureError(PluginBootstrapError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(code="external_failure", message=message, details=details)


# -----------------------------
# Typed contracts
# -----------------------------


@dataclass(frozen=True)
class PluginBootstrapRequest:
    plugin_name: str
    destination_dir: Path
    description: str = "Thomas plugin package"
    author: str = ""
    overwrite: bool = False


@dataclass(frozen=True)
class PluginBootstrapResult:
    plugin_name: str
    package_dir: str
    files_created: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_name": self.plugin_name,
            "package_dir": self.package_dir,
            "files_created": self.files_created,
            "warnings": self.warnings,
        }


# -----------------------------
# Implementation
# -----------------------------


_PKG_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_TOML_ESCAPE_RE = re.compile(r"[\r\n\t\"]")


def _validate_plugin_name(name: str) -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise InvalidInputError("plugin_name is required.")

    if not _PKG_NAME_RE.match(normalized):
        raise InvalidInputError(
            "plugin_name must be a valid Python package identifier.",
            details={"plugin_name": normalized},
        )

    if keyword.iskeyword(normalized):
        raise InvalidInputError("plugin_name cannot be a Python keyword.", details={"plugin_name": normalized})

    return normalized


def _toml_escape(value: str) -> str:
    # Keep escaping simple and deterministic; this is not a full TOML encoder.
    return _TOML_ESCAPE_RE.sub(lambda m: {"\r": "\\r", "\n": "\\n", "\t": "\\t", '"': "\\\""}[m.group(0)], value)


def _write_file(path: Path, content: str, *, overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        raise ExternalFailureError(
            "Unable to write file.",
            details={"path": str(path), "error": str(e)},
        ) from e
    return True


def bootstrap_plugin_package(req: PluginBootstrapRequest) -> PluginBootstrapResult:
    name = _validate_plugin_name(req.plugin_name)
    dest = req.destination_dir

    if str(dest).strip() == "":
        raise InvalidInputError("destination_dir is required.")

    package_dir = dest / name

    if package_dir.exists() and not req.overwrite:
        raise AlreadyExistsError(
            "Plugin package directory already exists.",
            details={"package_dir": str(package_dir)},
        )

    try:
        package_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ExternalFailureError(
            "Unable to create plugin package directory.",
            details={"package_dir": str(package_dir), "error": str(e)},
        ) from e

    files_created: list[str] = []
    warnings: list[str] = []

    init_py = (
        "from __future__ import annotations\n\n"
        "from .plugin import Plugin\n\n"
        "__all__ = [\"Plugin\"]\n"
    )

    plugin_py = (
        "from __future__ import annotations\n\n"
        f"\"\"\"{req.description}\"\"\"\n\n"
        "from dataclasses import dataclass\n"
        "from typing import Any\n\n"
        "# The Thomas plugin base class may evolve; we attempt a best-effort import.\n"
        "try:\n"
        "    from thomas.autonomy.plugin import AutonomyPlugin  # type: ignore\n"
        "except Exception:  # pragma: no cover\n"
        "    try:\n"
        "        from thomas.autonomy.plugin import Plugin as AutonomyPlugin  # type: ignore\n"
        "    except Exception:  # pragma: no cover\n"
        "        AutonomyPlugin = object  # type: ignore\n\n\n"
        "@dataclass\n"
        "class Plugin(AutonomyPlugin):\n"
        f"    \"\"\"{req.description}\"\"\"\n\n"
        f"    name: str = \"{name}\"\n\n"
        "    def register(self, registry: Any) -> None:\n"
        "        \"\"\"Register tools/hooks with Thomas.\n\n"
        "        Extend this method to add tools to the registry.\n"
        "        \"\"\"\n"
        "        return\n"
    )

    pyproject = (
        "[build-system]\n"
        "requires = [\"setuptools>=61.0\"]\n"
        "build-backend = \"setuptools.build_meta\"\n\n"
        "[project]\n"
        f"name = \"{_toml_escape(name)}\"\n"
        "version = \"0.1.0\"\n"
        f"description = \"{_toml_escape(req.description)}\"\n"
    )
    if req.author.strip():
        pyproject += f"authors = [{{name = \"{_toml_escape(req.author.strip())}\"}}]\n"

    readme = f"# {name}\n\n{req.description}\n"

    def _track(created: bool, p: Path, warn: str) -> None:
        if created:
            files_created.append(str(p))
        else:
            warnings.append(warn)

    _track(_write_file(package_dir / "__init__.py", init_py, overwrite=req.overwrite), package_dir / "__init__.py", "__init__.py existed; skipped.")
    _track(_write_file(package_dir / "plugin.py", plugin_py, overwrite=req.overwrite), package_dir / "plugin.py", "plugin.py existed; skipped.")
    _track(_write_file(package_dir / "pyproject.toml", pyproject, overwrite=req.overwrite), package_dir / "pyproject.toml", "pyproject.toml existed; skipped.")
    _track(_write_file(package_dir / "README.md", readme, overwrite=req.overwrite), package_dir / "README.md", "README.md existed; skipped.")

    return PluginBootstrapResult(
        plugin_name=name,
        package_dir=str(package_dir),
        files_created=files_created,
        warnings=warnings,
    )
