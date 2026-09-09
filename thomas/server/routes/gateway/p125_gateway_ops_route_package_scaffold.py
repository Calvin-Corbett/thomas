from __future__ import annotations

import keyword
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict, cast

ERROR_INVALID_INPUT = "invalid_input"
ERROR_MISSING_CONFIG = "missing_config"
ERROR_EXTERNAL_FAILURE = "external_failure"


class GatewayOpsRoutePackageScaffoldError(Exception):
    """Deterministic, machine-friendly error for gateway ops route scaffolding."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class GatewayOpsRoutePackageScaffoldRequestDict(TypedDict, total=False):
    project_root: str
    package_name: str
    dry_run: bool


@dataclass(frozen=True, slots=True)
class GatewayOpsRoutePackageScaffoldRequest:
    """Input contract for scaffolding a gateway ops route package."""

    package_name: str
    project_root: str | None = None
    dry_run: bool = False


class GatewayOpsRoutePackageScaffoldResultDict(TypedDict):
    project_root: str
    package_name: str
    package_dir: str
    created_dirs: list[str]
    created_files: list[str]
    skipped: list[str]


@dataclass(frozen=True, slots=True)
class GatewayOpsRoutePackageScaffoldResult:
    """Output contract for scaffolding a gateway ops route package."""

    project_root: str
    package_name: str
    package_dir: str
    created_dirs: tuple[str, ...] = field(default_factory=tuple)
    created_files: tuple[str, ...] = field(default_factory=tuple)
    skipped: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> GatewayOpsRoutePackageScaffoldResultDict:
        return {
            "project_root": self.project_root,
            "package_name": self.package_name,
            "package_dir": self.package_dir,
            "created_dirs": list(self.created_dirs),
            "created_files": list(self.created_files),
            "skipped": list(self.skipped),
        }


_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_package_name(name: str) -> None:
    if not isinstance(name, str) or not name.strip():
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_INVALID_INPUT,
            "package_name must be a non-empty string",
            details={"field": "package_name"},
        )
    if not _PACKAGE_NAME_RE.match(name):
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_INVALID_INPUT,
            "package_name must be a valid Python identifier (letters, digits, underscores)",
            details={"field": "package_name", "value": name},
        )
    if keyword.iskeyword(name):
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_INVALID_INPUT,
            "package_name must not be a Python keyword",
            details={"field": "package_name", "value": name},
        )


def _resolve_project_root(explicit: str | None) -> Path:
    if explicit:
        root = Path(explicit)
    else:
        env_root = os.environ.get("THOMAS_PROJECT_ROOT")
        if env_root:
            root = Path(env_root)
        else:
            raise GatewayOpsRoutePackageScaffoldError(
                ERROR_MISSING_CONFIG,
                "project_root not provided and THOMAS_PROJECT_ROOT is not set",
                details={"field": "project_root"},
            )

    if not root.exists():
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_INVALID_INPUT,
            "project_root does not exist",
            details={"project_root": str(root)},
        )
    if not root.is_dir():
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_INVALID_INPUT,
            "project_root must be a directory",
            details={"project_root": str(root)},
        )

    thomas_dir = root / "thomas"
    if not thomas_dir.exists() or not thomas_dir.is_dir():
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_MISSING_CONFIG,
            "project_root does not look like a Thomas checkout (missing 'thomas/' directory)",
            details={"project_root": str(root)},
        )

    return root


def _safe_mkdir(path: Path, *, dry_run: bool) -> bool:
    """Ensure directory exists. Returns True if created, False if already existed."""
    if path.exists():
        if path.is_dir():
            return False
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_EXTERNAL_FAILURE,
            "cannot create directory because a non-directory path exists",
            details={"path": str(path)},
        )

    if not dry_run:
        try:
            path.mkdir(parents=True, exist_ok=False)
        except Exception as e:  # pragma: no cover
            raise GatewayOpsRoutePackageScaffoldError(
                ERROR_EXTERNAL_FAILURE,
                "failed to create directory",
                details={"path": str(path), "reason": type(e).__name__},
            ) from e
    return True


def _safe_write_text(path: Path, content: str, *, dry_run: bool) -> bool:
    """Ensure file exists with given content if missing. Returns True if created, False if already existed."""
    if path.exists():
        if path.is_file():
            return False
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_EXTERNAL_FAILURE,
            "cannot create file because a non-file path exists",
            details={"path": str(path)},
        )

    if not dry_run:
        try:
            path.write_text(content, encoding="utf-8")
        except Exception as e:  # pragma: no cover
            raise GatewayOpsRoutePackageScaffoldError(
                ERROR_EXTERNAL_FAILURE,
                "failed to write file",
                details={"path": str(path), "reason": type(e).__name__},
            ) from e
    return True


def _minimal_init_py() -> str:
    return '"""Package."""\n'


def scaffold_gateway_ops_route_package(
    request: GatewayOpsRoutePackageScaffoldRequest,
) -> GatewayOpsRoutePackageScaffoldResult:
    """Create a gateway ops route package scaffold under:

        <project_root>/thomas/server/routes/gateway/ops/<package_name>/

    Idempotent; never overwrites existing files.

    Design note:
    - Avoid adding __init__.py files to pre-existing directories unless they are part of the new ops subtree
      (gateway/ops and the leaf package), to minimize surprising changes to an existing repo layout.
    """
    _validate_package_name(request.package_name)
    root = _resolve_project_root(request.project_root)

    thomas_dir = root / "thomas"
    gateway_dir = thomas_dir / "server" / "routes" / "gateway"
    ops_dir = gateway_dir / "ops"
    leaf_dir = ops_dir / request.package_name

    package_dirs = [
        thomas_dir / "server",
        thomas_dir / "server" / "routes",
        gateway_dir,
        ops_dir,
        leaf_dir,
    ]

    created_dirs: list[str] = []
    created_files: list[str] = []
    skipped: list[str] = []

    for d in package_dirs:
        created = _safe_mkdir(d, dry_run=request.dry_run)
        if created:
            created_dirs.append(str(d))
        else:
            skipped.append(str(d))

        should_ensure_init = created or d in {ops_dir, leaf_dir}
        if should_ensure_init:
            init_py = d / "__init__.py"
            created_init = _safe_write_text(init_py, _minimal_init_py(), dry_run=request.dry_run)
            if created_init:
                created_files.append(str(init_py))
            else:
                skipped.append(str(init_py))

    routes_py = leaf_dir / "routes.py"
    routes_content = (
        "from __future__ import annotations\n\n"
        "from aiohttp import web\n\n\n"
        "routes = web.RouteTableDef()\n\n\n"
        f"@routes.get('/gateway/ops/{request.package_name}/health')\n"
        "async def health(request: web.Request) -> web.Response:\n"
        "    return web.json_response({'ok': True})\n\n\n"
        "def register(app: web.Application) -> None:\n"
        "    app.add_routes(routes)\n"
    )
    created_routes = _safe_write_text(routes_py, routes_content, dry_run=request.dry_run)
    if created_routes:
        created_files.append(str(routes_py))
    else:
        skipped.append(str(routes_py))

    return GatewayOpsRoutePackageScaffoldResult(
        project_root=str(root),
        package_name=request.package_name,
        package_dir=str(leaf_dir),
        created_dirs=tuple(created_dirs),
        created_files=tuple(created_files),
        skipped=tuple(skipped),
    )


def gateway_ops_route_package_scaffold_request_from_mapping(
    data: Mapping[str, Any],
) -> GatewayOpsRoutePackageScaffoldRequest:
    """Parse and validate a mapping (typically JSON) into a request dataclass."""
    if not isinstance(data, Mapping):
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_INVALID_INPUT,
            "request body must be a JSON object",
            details={"field": "body"},
        )

    package_name = data.get("package_name")
    project_root = data.get("project_root")
    dry_run = data.get("dry_run", False)

    if package_name is None:
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_INVALID_INPUT,
            "package_name is required",
            details={"field": "package_name"},
        )
    if not isinstance(package_name, str):
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_INVALID_INPUT,
            "package_name must be a string",
            details={"field": "package_name"},
        )
    if project_root is not None and not isinstance(project_root, str):
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_INVALID_INPUT,
            "project_root must be a string",
            details={"field": "project_root"},
        )
    if not isinstance(dry_run, bool):
        raise GatewayOpsRoutePackageScaffoldError(
            ERROR_INVALID_INPUT,
            "dry_run must be a boolean",
            details={"field": "dry_run"},
        )

    return GatewayOpsRoutePackageScaffoldRequest(
        package_name=cast(str, package_name),
        project_root=cast(str | None, project_root),
        dry_run=dry_run,
    )


def get_gateway_ops_route_package_scaffold_json_schema() -> dict[str, Any]:
    """Machine-readable schema for automation clients."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "GatewayOpsRoutePackageScaffold",
        "type": "object",
        "properties": {
            "request": {
                "type": "object",
                "required": ["package_name"],
                "properties": {
                    "package_name": {
                        "type": "string",
                        "pattern": _PACKAGE_NAME_RE.pattern,
                        "description": "Python identifier to use as the leaf package name under gateway/ops/",
                    },
                    "project_root": {
                        "type": "string",
                        "description": "Filesystem path to the Thomas project root. If omitted, THOMAS_PROJECT_ROOT is used.",
                    },
                    "dry_run": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            "response": {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "result": {"type": "object"},
                    "error": {"type": "object"},
                },
                "required": ["ok"],
                "additionalProperties": True,
            },
        },
        "required": ["request"],
        "additionalProperties": False,
    }


# ------------------------------
# Optional aiohttp route wiring.
# ------------------------------

try:  # pragma: no cover
    from aiohttp import web  # type: ignore
except Exception:  # pragma: no cover
    web = None  # type: ignore

if web is not None:  # pragma: no cover
    routes = web.RouteTableDef()

    @routes.get("/gateway/ops/route-package-scaffold/schema")
    async def schema_handler(request: web.Request) -> web.Response:
        return web.json_response(get_gateway_ops_route_package_scaffold_json_schema())

    @routes.post("/gateway/ops/route-package-scaffold")
    async def scaffold_handler(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            err = GatewayOpsRoutePackageScaffoldError(
                ERROR_INVALID_INPUT, "request body must be valid JSON", details={"field": "body"}
            )
            return web.json_response({"ok": False, "error": err.to_dict()}, status=400)

        try:
            req = gateway_ops_route_package_scaffold_request_from_mapping(body)
            result = scaffold_gateway_ops_route_package(req)
            return web.json_response({"ok": True, "result": result.to_dict()})
        except GatewayOpsRoutePackageScaffoldError as e:
            status = 400 if e.code in {ERROR_INVALID_INPUT, ERROR_MISSING_CONFIG} else 500
            return web.json_response({"ok": False, "error": e.to_dict()}, status=status)

    def register(app: web.Application) -> None:
        """Compatibility hook for apps that expect an explicit registration function."""
        app.add_routes(routes)
