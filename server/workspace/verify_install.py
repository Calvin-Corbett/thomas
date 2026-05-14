"""Verify installation of workspace.rbac_multi_tenant.

Usage:
  THOMAS_APP_IMPORT="server.main:app" python -m server.workspace.verify_install

If THOMAS_APP_IMPORT is not set, we try common import paths.

What it checks:
  - /api routes have enforce_workspace dependency (excluding public prefixes).
  - workspace tables exist.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from fastapi.routing import APIRoute
from sqlalchemy import inspect

from .deps import PUBLIC_PATH_PREFIXES, enforce_workspace
from .migrate_schema import _import_engine  # noqa: WPS436


def _import_app() -> object:
    env = os.environ.get("THOMAS_APP_IMPORT", "").strip()
    candidates = []
    if env and ":" in env:
        candidates.append(env)
    candidates += [
        "server.main:app",
        "server.app:app",
        "server.__main__:app",
        "main:app",
        "app:app",
    ]

    last = None
    for path in candidates:
        if ":" not in path:
            continue
        mod, sym = path.split(":")
        try:
            m = __import__(mod, fromlist=[sym])
            return getattr(m, sym)
        except Exception as e:
            last = e
    raise RuntimeError("Could not import FastAPI app. Set THOMAS_APP_IMPORT=module:app") from last


def _has_enforce_dependency(route: APIRoute) -> bool:
    # route.dependencies are fastapi.params.Depends objects if set at router/include level
    for dep in (route.dependencies or []):
        call = getattr(dep, "dependency", None)
        if call is enforce_workspace:
            return True

    # route.dependant dependencies include nested dependencies, but we only accept direct include deps
    # to avoid false positives.
    try:
        for dep in route.dependant.dependencies:
            if dep.call is enforce_workspace:
                return True
    except Exception:
        pass
    return False


def verify_routes(app) -> tuple[int, int]:
    ok = 0
    bad = 0
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        path = r.path
        if not path.startswith("/api"):
            continue
        if any(path.startswith(p) for p in PUBLIC_PATH_PREFIXES):
            ok += 1
            continue
        if _has_enforce_dependency(r):
            ok += 1
        else:
            bad += 1
            print(f"[MISSING] {r.methods} {path}")
    return ok, bad


def verify_db() -> None:
    engine = _import_engine()
    insp = inspect(engine)
    needed = {"workspaces", "workspace_memberships", "workspace_invites"}
    present = set(insp.get_table_names())
    missing = sorted(list(needed - present))
    if missing:
        raise RuntimeError("Missing DB tables: " + ", ".join(missing))
    print("[OK] DB tables present:", ", ".join(sorted(list(needed))))


def main() -> None:
    app = _import_app()
    ok, bad = verify_routes(app)
    print(f"[ROUTES] ok={ok} bad={bad}")
    if bad:
        raise SystemExit(2)
    verify_db()
    print("workspace.rbac_multi_tenant verification PASSED.")


if __name__ == "__main__":
    main()
