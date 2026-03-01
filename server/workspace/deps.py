from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Iterable, Sequence

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from .models import Workspace, WorkspaceMembership
from .rbac import WorkspaceRole, normalize_role, role_allows


def _import_symbol(candidates: Sequence[str], hint: str):
    last_err = None
    for path in candidates:
        mod, sym = path.split(":")
        try:
            m = __import__(mod, fromlist=[sym])
            return getattr(m, sym)
        except Exception as e:
            last_err = e
    raise RuntimeError(hint) from last_err


get_current_user = _import_symbol(
    [
        "server.auth.deps:get_current_user",
        "server.auth.dependencies:get_current_user",
        "server.auth.security:get_current_user",
        "auth.deps:get_current_user",
    ],
    "Could not import get_current_user from expected locations. Update server/workspace/deps.py to match your auth stack.",
)

get_db = _import_symbol(
    [
        "server.db.session:get_db",
        "server.db.deps:get_db",
        "server.database:get_db",
    ],
    "Could not import get_db from expected locations. Update server/workspace/deps.py to match your DB stack.",
)

PUBLIC_PATH_PREFIXES: Sequence[str] = (
    "/api/health",
    "/api/auth",
    "/api/openapi",
    "/api/docs",
    "/api/redoc",
)


@dataclass(frozen=True)
class WorkspaceContext:
    workspace: Workspace
    membership: WorkspaceMembership
    role: WorkspaceRole


def _pick_workspace_id(request: Request) -> Optional[str]:
    ws = request.headers.get("X-Workspace-Id") or request.headers.get("X-Workspace-ID")
    if ws:
        return ws.strip()
    ws = request.cookies.get("workspace_id")
    if ws:
        return ws.strip()
    ws = getattr(request.state, "workspace_id", None)
    if ws:
        return str(ws)
    return None


def enforce_workspace(
    request: Request,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceContext:
    path = request.url.path
    if any(path.startswith(p) for p in PUBLIC_PATH_PREFIXES):
        # Public routes do not carry tenant context.
        return WorkspaceContext(
            workspace=Workspace(workspace_id="public", name="public", owner_user_id=None, created_at=request.state.__dict__.get("now")),  # type: ignore
            membership=WorkspaceMembership(workspace_id="public", user_id="public", role=WorkspaceRole.viewer.value, created_at=request.state.__dict__.get("now"), is_active=True),  # type: ignore
            role=WorkspaceRole.viewer,
        )

    user_id = str(getattr(user, "id", getattr(user, "user_id", "")))
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    ws_id = _pick_workspace_id(request)

    if not ws_id:
        membership = db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.user_id == user_id)
            .where(WorkspaceMembership.is_active == True)  # noqa: E712
            .order_by(WorkspaceMembership.created_at.asc())
            .limit(1)
        ).scalars().first()
        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No workspace membership")
        ws_id = membership.workspace_id
    else:
        membership = db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == ws_id)
            .where(WorkspaceMembership.user_id == user_id)
            .where(WorkspaceMembership.is_active == True)  # noqa: E712
            .limit(1)
        ).scalars().first()
        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this workspace")

    ws = db.execute(
        select(Workspace).where(Workspace.workspace_id == ws_id).limit(1)
    ).scalars().first()
    if not ws:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    try:
        role = normalize_role(membership.role, field="membership role")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid membership role") from exc
    request.state.workspace_id = ws_id
    request.state.workspace_role = role.value

    try:
        db.info["workspace_id"] = ws_id
    except Exception:
        pass

    return WorkspaceContext(workspace=ws, membership=membership, role=role)


def require_roles(required: Iterable[WorkspaceRole]):
    required = tuple(required)

    def _dep(ctx: WorkspaceContext = Depends(enforce_workspace)) -> WorkspaceContext:
        if not role_allows(ctx.role, required):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return ctx

    return _dep
