"""Node command uninstall.

Thomas-native behavior for uninstalling an npm package.

This module is intentionally self-contained (standard library only) so it can be
used from both CLI and server contexts without importing the broader Thomas
runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
from typing import Any, Mapping


# -----------------
# Public contracts
# -----------------


DEFAULT_TIMEOUT_S: int = 300


@dataclass(frozen=True, slots=True)
class NodeCommandUninstallRequest:
    """Input contract for uninstalling an npm package.

    Only a single package spec is supported per request for deterministic
    behavior.

    Attributes:
        package: npm package spec (e.g. "lodash" or "@scope/pkg").
        project_dir: Starting directory for local uninstalls. The implementation
            will search upward for a package.json and use that directory as the
            working directory.
        global_install: If True, uninstall from the global npm prefix.
        dry_run: If True, add npm's --dry-run flag.
        npm_executable: Executable name or path for npm.
        timeout_s: Timeout in seconds for the npm process (None disables).
    """

    package: str
    project_dir: str | Path = "."
    global_install: bool = False
    dry_run: bool = False
    npm_executable: str = "npm"
    timeout_s: int | None = DEFAULT_TIMEOUT_S

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NodeCommandUninstallRequest":
        if not isinstance(data, Mapping):
            raise NodeCommandUninstallError(
                code="invalid_input",
                message="Request payload must be an object.",
                details={"received_type": type(data).__name__},
            )

        return cls(
            package=data.get("package"),  # validated later
            project_dir=data.get("project_dir", "."),
            global_install=data.get("global_install", False),
            dry_run=data.get("dry_run", False),
            npm_executable=data.get("npm_executable", "npm"),
            timeout_s=data.get("timeout_s", DEFAULT_TIMEOUT_S),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "project_dir": str(self.project_dir),
            "global_install": self.global_install,
            "dry_run": self.dry_run,
            "npm_executable": self.npm_executable,
            "timeout_s": self.timeout_s,
        }


@dataclass(frozen=True, slots=True)
class NodeCommandUninstallResult:
    """Output contract for a successful uninstall."""

    package: str
    command: list[str]
    project_dir: str | None
    global_install: bool
    dry_run: bool
    return_code: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "command": list(self.command),
            "project_dir": self.project_dir,
            "global_install": self.global_install,
            "dry_run": self.dry_run,
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


class NodeCommandUninstallError(RuntimeError):
    """Deterministic error type for uninstall failures."""

    def __init__(self, *, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details) if details else {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


# -----------------
# JSON Schemas
# -----------------

NODE_COMMAND_UNINSTALL_REQUEST_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["package"],
    "properties": {
        "package": {"type": "string", "minLength": 1},
        "project_dir": {"type": "string", "default": "."},
        "global_install": {"type": "boolean", "default": False},
        "dry_run": {"type": "boolean", "default": False},
        "npm_executable": {"type": "string", "default": "npm"},
        "timeout_s": {"type": ["integer", "null"], "minimum": 1, "default": DEFAULT_TIMEOUT_S},
    },
}

NODE_COMMAND_UNINSTALL_RESULT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "package",
        "command",
        "project_dir",
        "global_install",
        "dry_run",
        "return_code",
        "stdout",
        "stderr",
    ],
    "properties": {
        "package": {"type": "string"},
        "command": {"type": "array", "items": {"type": "string"}},
        "project_dir": {"type": ["string", "null"]},
        "global_install": {"type": "boolean"},
        "dry_run": {"type": "boolean"},
        "return_code": {"type": "integer"},
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
    },
}

# Common alias names used by route registries / automation.
REQUEST_SCHEMA = NODE_COMMAND_UNINSTALL_REQUEST_SCHEMA
RESPONSE_SCHEMA = NODE_COMMAND_UNINSTALL_RESULT_SCHEMA
JSON_INPUT_SCHEMA = NODE_COMMAND_UNINSTALL_REQUEST_SCHEMA
JSON_OUTPUT_SCHEMA = NODE_COMMAND_UNINSTALL_RESULT_SCHEMA


# -----------------
# Implementation
# -----------------


def uninstall_node_command(req: NodeCommandUninstallRequest) -> NodeCommandUninstallResult:
    """Uninstall an npm package.

    Raises:
        NodeCommandUninstallError: deterministic error for invalid input, missing
            config, or external npm failures.
    """

    package = _validate_package(req.package)

    npm_exe = _validate_npm_executable(req.npm_executable)
    timeout_s = _validate_timeout(req.timeout_s)

    project_root: Path | None = None
    if not req.global_install:
        project_root = _resolve_project_root(req.project_dir)

    cmd: list[str] = [npm_exe, "uninstall"]
    if req.global_install:
        cmd.append("-g")
    if req.dry_run:
        cmd.append("--dry-run")
    cmd.append(package)

    cwd: str | None = None if req.global_install else str(project_root)
    project_dir_str: str | None = None if req.global_install else str(project_root)

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as e:
        raise NodeCommandUninstallError(
            code="npm_not_found",
            message=f"npm executable not found: {npm_exe}",
            details={"npm_executable": npm_exe},
        ) from e
    except subprocess.TimeoutExpired as e:
        raise NodeCommandUninstallError(
            code="external_timeout",
            message="npm uninstall timed out.",
            details={"command": cmd, "timeout_s": timeout_s},
        ) from e
    except Exception as e:  # pragma: no cover
        raise NodeCommandUninstallError(
            code="external_failure",
            message="Failed to invoke npm uninstall.",
            details={"command": cmd, "exception": type(e).__name__},
        ) from e

    result = NodeCommandUninstallResult(
        package=package,
        command=cmd,
        project_dir=project_dir_str,
        global_install=req.global_install,
        dry_run=req.dry_run,
        return_code=int(proc.returncode),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )

    if proc.returncode != 0:
        raise NodeCommandUninstallError(
            code="uninstall_failed",
            message=f"npm uninstall failed with exit code {proc.returncode}.",
            details={
                "package": package,
                "command": cmd,
                "return_code": int(proc.returncode),
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )

    return result


def uninstall_node_command_from_dict(payload: Mapping[str, Any]) -> NodeCommandUninstallResult:
    """Convenience wrapper for JSON / route handlers."""

    return uninstall_node_command(NodeCommandUninstallRequest.from_dict(payload))


# Alias for some discovery systems.
node_command_uninstall = uninstall_node_command


def _validate_npm_executable(npm_executable: Any) -> str:
    if not isinstance(npm_executable, str) or not npm_executable.strip():
        raise NodeCommandUninstallError(
            code="invalid_input",
            message="'npm_executable' must be a non-empty string.",
            details={"npm_executable": npm_executable},
        )
    return npm_executable.strip()


def _validate_timeout(timeout_s: Any) -> int | None:
    if timeout_s is None:
        return None
    if not isinstance(timeout_s, int):
        raise NodeCommandUninstallError(
            code="invalid_input",
            message="'timeout_s' must be an integer or null.",
            details={"received_type": type(timeout_s).__name__},
        )
    if timeout_s <= 0:
        raise NodeCommandUninstallError(
            code="invalid_input",
            message="'timeout_s' must be a positive integer when provided.",
            details={"timeout_s": timeout_s},
        )
    return timeout_s


def _validate_package(package: Any) -> str:
    if not isinstance(package, str):
        raise NodeCommandUninstallError(
            code="invalid_input",
            message="'package' must be a string.",
            details={"received_type": type(package).__name__},
        )

    spec = package.strip()
    if not spec:
        raise NodeCommandUninstallError(code="invalid_input", message="'package' must not be empty.")

    if any(ch.isspace() for ch in spec):
        raise NodeCommandUninstallError(
            code="invalid_input",
            message="'package' must be a single npm package spec (no whitespace).",
            details={"package": package},
        )

    # Prevent option injection like "--force".
    if spec.startswith("-"):
        raise NodeCommandUninstallError(
            code="invalid_input",
            message="'package' must not start with '-'.",
            details={"package": package},
        )

    # Basic structured validation (scoped/unscoped + optional @version/tag).
    name_part, version_part = _split_name_and_version(spec)
    _validate_name_only(name_part)

    if version_part is not None:
        # Keep it permissive but safe: no whitespace, no slashes.
        if (not version_part) or any(ch.isspace() for ch in version_part) or "/" in version_part:
            raise NodeCommandUninstallError(
                code="invalid_input",
                message="'package' has an invalid version/tag suffix.",
                details={"package": package},
            )

    return spec


def _split_name_and_version(spec: str) -> tuple[str, str | None]:
    """Split an npm package spec into (name, version/tag|None).

    Supports:
      - name
      - name@version
      - @scope/name
      - @scope/name@version
    """

    if spec.startswith("@"):
        # scoped: @scope/name or @scope/name@version
        if "/" not in spec:
            raise NodeCommandUninstallError(
                code="invalid_input",
                message="Scoped packages must be in the form '@scope/name'.",
                details={"package": spec},
            )
        scope, tail = spec.split("/", 1)
        if scope == "@":
            raise NodeCommandUninstallError(
                code="invalid_input",
                message="Scoped packages must include a scope name.",
                details={"package": spec},
            )
        if not tail:
            raise NodeCommandUninstallError(
                code="invalid_input",
                message="Scoped packages must include a package name after '/'.",
                details={"package": spec},
            )
        # tail may contain @version
        if "@" in tail:
            name_only, version = tail.rsplit("@", 1)
            if not name_only:
                raise NodeCommandUninstallError(
                    code="invalid_input",
                    message="'package' has an invalid version/tag suffix.",
                    details={"package": spec},
                )
            return f"{scope}/{name_only}", version
        return spec, None

    # unscoped: name or name@version
    if "@" in spec:
        name_only, version = spec.rsplit("@", 1)
        if not name_only:
            raise NodeCommandUninstallError(
                code="invalid_input",
                message="'package' has an invalid version/tag suffix.",
                details={"package": spec},
            )
        return name_only, version
    return spec, None


def _validate_name_only(name: str) -> None:
    # '@scope/name' or 'name'
    if name.startswith("@"):
        scope, pkg = name.split("/", 1)
        if not _valid_simple_name(scope[1:]):
            raise NodeCommandUninstallError(
                code="invalid_input",
                message="'package' scope contains invalid characters.",
                details={"package": name},
            )
        if not _valid_simple_name(pkg):
            raise NodeCommandUninstallError(
                code="invalid_input",
                message="'package' name contains invalid characters.",
                details={"package": name},
            )
        return

    if not _valid_simple_name(name):
        raise NodeCommandUninstallError(
            code="invalid_input",
            message="'package' name contains invalid characters.",
            details={"package": name},
        )


def _valid_simple_name(value: str) -> bool:
    # NPM is fairly permissive; we keep it safe and practical.
    if not value:
        return False
    if value[0] in {".", "_"}:
        return False
    # Avoid path-ish names.
    if "/" in value or "\\" in value:
        return False
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    return all(ch in allowed for ch in value)


def _resolve_project_root(project_dir: str | Path) -> Path:
    if not isinstance(project_dir, (str, Path)):
        raise NodeCommandUninstallError(
            code="invalid_input",
            message="'project_dir' must be a string path.",
            details={"received_type": type(project_dir).__name__},
        )

    start = Path(project_dir).expanduser()
    if not start.exists() or not start.is_dir():
        raise NodeCommandUninstallError(
            code="invalid_input",
            message="'project_dir' must be an existing directory for local uninstalls.",
            details={"project_dir": str(project_dir)},
        )

    root = _find_upward(start, "package.json")
    if root is None:
        raise NodeCommandUninstallError(
            code="missing_config",
            message="package.json not found (searched upward from project_dir).",
            details={"project_dir": str(start.resolve())},
        )

    return root.resolve()


def _find_upward(start: Path, filename: str) -> Path | None:
    cur = start.resolve()
    while True:
        candidate = cur / filename
        if candidate.exists():
            return cur
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent
