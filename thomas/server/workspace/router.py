"""Workspace RBAC — aiohttp routes.

Adapted from the FastAPI pack to run natively in Thomas's aiohttp server.
Auth: Thomas uses a per-request context key APP_WORKSPACE_CON (sqlite3 connection).
All workspace API routes are under /api/workspaces.

Public integration: call setup(app, config) from create_app().
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from collections.abc import Callable

from aiohttp import web

from thomas.core.config import AppConfig, load_config
from thomas.server.app_keys import APP_CONFIG

from .db import (
    accept_invite,
    connect,
    create_invite,
    create_workspace,
    deactivate_member,
    ensure_schema,
    first_membership_for_user,
    get_db_path,
    get_invite_by_token,
    get_membership,
    get_workspace,
    list_invites,
    list_members,
    list_workspaces_for_user,
    upsert_membership,
)
from .rbac import WorkspaceRole, can_manage_members, normalize_role

log = logging.getLogger(__name__)

APP_WORKSPACE_CON = web.AppKey("workspace_con", object)
APP_WORKSPACE_REQUIRE_API_ACCESS = web.AppKey("workspace_require_api_access", object)

RequireAccessFn = Callable[[web.Request], None]

_BEARER_TOKEN_RE = re.compile(r"^Bearer\s+([^\s]+)\s*$", re.IGNORECASE)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _json(data) -> web.Response:
    return web.Response(
        content_type="application/json",
        text=json.dumps(data, default=str),
    )


def _err(status: int, detail: str) -> web.HTTPException:
    exc_cls = {
        400: web.HTTPBadRequest,
        401: web.HTTPUnauthorized,
        403: web.HTTPForbidden,
        404: web.HTTPNotFound,
        409: web.HTTPConflict,
        410: web.HTTPGone,
        422: web.HTTPUnprocessableEntity,
    }.get(status, web.HTTPInternalServerError)
    raise exc_cls(
        content_type="application/json",
        text=json.dumps({"detail": detail}),
    )


def _extract_request_token(request: web.Request) -> str:
    auth = str(request.headers.get("Authorization") or "").strip()
    if auth:
        match = _BEARER_TOKEN_RE.match(auth)
        if not match:
            return ""
        return match.group(1)

    token = str(request.headers.get("X-Api-Token") or "").strip()
    if not token or any(ch.isspace() for ch in token):
        return ""
    return token


def _require_default_api_access(request: web.Request) -> None:
    cfg = request.app.get(APP_CONFIG)
    if not isinstance(cfg, AppConfig):
        cfg = load_config()

    server_cfg = getattr(cfg, "server", None)
    mode = str(getattr(server_cfg, "access_mode", "local") or "local").strip().lower()
    if mode != "remote":
        return

    expected = str(getattr(server_cfg, "api_token", "") or "").strip()
    if not expected:
        raise web.HTTPUnauthorized(text="server api token is not configured")

    incoming = _extract_request_token(request)
    if not incoming:
        raise web.HTTPUnauthorized(text="missing api token")
    if not hmac.compare_digest(incoming.encode("utf-8"), expected.encode("utf-8")):
        raise web.HTTPUnauthorized(text="invalid api token")


def _row(r) -> dict:
    if r is None:
        return {}
    return dict(r)


def _get_user_id(request: web.Request) -> str:
    """Extract user identity from request.

    In remote mode, bind identity to the validated API token to avoid trusting
    caller-controlled headers for authorization decisions.
    """
    cfg = request.app.get(APP_CONFIG)
    if not isinstance(cfg, AppConfig):
        cfg = load_config()

    server_cfg = getattr(cfg, "server", None)
    mode = str(getattr(server_cfg, "access_mode", "local") or "local").strip().lower()
    if mode == "remote":
        expected = str(getattr(server_cfg, "api_token", "") or "").strip()
        incoming = _extract_request_token(request)
        if not incoming:
            raise web.HTTPUnauthorized(text="missing api token")
        if not expected:
            raise web.HTTPUnauthorized(text="server api token is not configured")
        if not hmac.compare_digest(incoming.encode("utf-8"), expected.encode("utf-8")):
            raise web.HTTPUnauthorized(text="invalid api token")
        # The token is already verified above via constant-time compare; this hash
        # is only a stable identity/bucket key for membership lookups, not a
        # security control protecting the token, so it is not security-sensitive.
        return hashlib.sha256(incoming.encode("utf-8"), usedforsecurity=False).hexdigest()

    raw = str(request.headers.get("X-User-Id") or "").strip()
    return raw if raw else "default"


def _enforce_api_access(request: web.Request) -> None:
    require_api_access = request.app.get(APP_WORKSPACE_REQUIRE_API_ACCESS)
    if callable(require_api_access):
        require_api_access(request)
        return
    _require_default_api_access(request)


def _pick_workspace_id(request: web.Request) -> str | None:
    ws = request.headers.get("X-Workspace-Id") or request.headers.get("X-Workspace-ID")
    if ws:
        return ws.strip()
    return None


def _require_role(value, *, field: str) -> WorkspaceRole:
    try:
        return normalize_role(value)
    except ValueError:
        _err(422, f"invalid {field}")


def _require_workspace_ctx(con, request: web.Request):
    """Resolve workspace + membership for the current request. Returns (ws_row, membership_row, WorkspaceRole)."""
    user_id = _get_user_id(request)
    ws_id = _pick_workspace_id(request)

    if ws_id:
        membership = get_membership(con, ws_id, user_id)
        if not membership:
            _err(403, "Not a member of this workspace")
        ws = get_workspace(con, ws_id)
        if not ws:
            _err(404, "Workspace not found")
    else:
        membership = first_membership_for_user(con, user_id)
        if not membership:
            _err(403, "No workspace membership")
        ws_id = membership["workspace_id"]
        ws = get_workspace(con, ws_id)
        if not ws:
            _err(404, "Workspace not found")

    role = _require_role(membership["role"], field="membership role")
    return ws, membership, role


# ── Route handlers ────────────────────────────────────────────────────────────


async def h_list_workspaces(request: web.Request) -> web.Response:
    _enforce_api_access(request)
    con = request.app[APP_WORKSPACE_CON]
    user_id = _get_user_id(request)
    rows = list_workspaces_for_user(con, user_id)
    return _json([_row(r) for r in rows])


async def h_create_workspace(request: web.Request) -> web.Response:
    _enforce_api_access(request)
    con = request.app[APP_WORKSPACE_CON]
    user_id = _get_user_id(request)
    try:
        body = await request.json()
    except Exception:
        _err(400, "Invalid JSON")
    name = str(body.get("name", "")).strip()
    if not name or len(name) > 200:
        _err(422, "name must be 1-200 characters")
    ws = create_workspace(con, name, user_id)
    return web.Response(
        status=201,
        content_type="application/json",
        text=json.dumps(_row(ws), default=str),
    )


async def h_current_workspace(request: web.Request) -> web.Response:
    _enforce_api_access(request)
    con = request.app[APP_WORKSPACE_CON]
    ws, _m, _r = _require_workspace_ctx(con, request)
    return _json(_row(ws))


async def h_current_membership(request: web.Request) -> web.Response:
    _enforce_api_access(request)
    con = request.app[APP_WORKSPACE_CON]
    _ws, membership, _r = _require_workspace_ctx(con, request)
    return _json(_row(membership))


async def h_list_members(request: web.Request) -> web.Response:
    _enforce_api_access(request)
    con = request.app[APP_WORKSPACE_CON]
    workspace_id = request.match_info["workspace_id"]
    ws, _m, role = _require_workspace_ctx(con, request)
    if ws["workspace_id"] != workspace_id:
        _err(403, "Workspace mismatch")
    if not can_manage_members(role):
        _err(403, "Insufficient role")
    members = list_members(con, workspace_id)
    return _json([_row(m) for m in members])


async def h_create_invite(request: web.Request) -> web.Response:
    _enforce_api_access(request)
    con = request.app[APP_WORKSPACE_CON]
    workspace_id = request.match_info["workspace_id"]
    ws, _m, role = _require_workspace_ctx(con, request)
    if ws["workspace_id"] != workspace_id:
        _err(403, "Workspace mismatch")
    if not can_manage_members(role):
        _err(403, "Insufficient role")
    try:
        body = await request.json()
    except Exception:
        _err(400, "Invalid JSON")
    email = str(body.get("email", "")).strip()
    if not email:
        _err(422, "email required")
    inv_role = _require_role(body.get("role", "member"), field="invite role")
    note = body.get("note")
    user_id = _get_user_id(request)
    inv_row, raw_token = create_invite(con, workspace_id, email, inv_role.value, user_id, note)
    result = {"invite": _row(inv_row), "invite_token": raw_token}
    return web.Response(status=201, content_type="application/json", text=json.dumps(result, default=str))


async def h_list_invites(request: web.Request) -> web.Response:
    _enforce_api_access(request)
    con = request.app[APP_WORKSPACE_CON]
    workspace_id = request.match_info["workspace_id"]
    ws, _m, role = _require_workspace_ctx(con, request)
    if ws["workspace_id"] != workspace_id:
        _err(403, "Workspace mismatch")
    if not can_manage_members(role):
        _err(403, "Insufficient role")
    invites = list_invites(con, workspace_id)
    return _json([_row(i) for i in invites])


async def h_accept_invite(request: web.Request) -> web.Response:
    _enforce_api_access(request)
    con = request.app[APP_WORKSPACE_CON]
    user_id = _get_user_id(request)
    try:
        body = await request.json()
    except Exception:
        _err(400, "Invalid JSON")
    raw_token = str(body.get("invite_token", "")).strip()
    if not raw_token:
        _err(400, "invite_token required")
    inv = get_invite_by_token(con, raw_token)
    if not inv:
        _err(404, "Invite not found")
    if inv["revoked_at"]:
        _err(410, "Invite revoked")
    if inv["accepted_at"]:
        _err(409, "Invite already used")
    from datetime import datetime, timezone

    if datetime.fromisoformat(inv["expires_at"]) < datetime.now(timezone.utc).replace(tzinfo=None):
        _err(410, "Invite expired")
    _require_role(inv["role"], field="invite role")
    membership = accept_invite(con, inv["invite_id"], user_id)
    return _json(_row(membership))


async def h_change_role(request: web.Request) -> web.Response:
    _enforce_api_access(request)
    con = request.app[APP_WORKSPACE_CON]
    workspace_id = request.match_info["workspace_id"]
    target_user_id = request.match_info["user_id"]
    ws, _m, role = _require_workspace_ctx(con, request)
    if ws["workspace_id"] != workspace_id:
        _err(403, "Workspace mismatch")
    if not can_manage_members(role):
        _err(403, "Insufficient role")
    try:
        body = await request.json()
    except Exception:
        _err(400, "Invalid JSON")
    new_role = _require_role(body.get("role", ""), field="role")
    target = get_membership(con, workspace_id, target_user_id)
    if not target:
        _err(404, "Member not found")
    target_role = _require_role(target["role"], field="target role")
    if role == WorkspaceRole.admin and target_role == WorkspaceRole.owner:
        _err(403, "Admins cannot modify owners")
    updated = upsert_membership(con, workspace_id, target_user_id, new_role.value)
    return _json(_row(updated))


async def h_revoke_member(request: web.Request) -> web.Response:
    _enforce_api_access(request)
    con = request.app[APP_WORKSPACE_CON]
    workspace_id = request.match_info["workspace_id"]
    target_user_id = request.match_info["user_id"]
    ws, _m, role = _require_workspace_ctx(con, request)
    if ws["workspace_id"] != workspace_id:
        _err(403, "Workspace mismatch")
    if not can_manage_members(role):
        _err(403, "Insufficient role")
    target = get_membership(con, workspace_id, target_user_id)
    if not target:
        _err(404, "Member not found")
    target_role = _require_role(target["role"], field="target role")
    if target_role == WorkspaceRole.owner:
        _err(403, "Cannot revoke owner")
    deactivate_member(con, workspace_id, target_user_id)
    return web.Response(status=204)


# ── Setup ─────────────────────────────────────────────────────────────────────


def setup(app: web.Application, config, *, require_api_access: RequireAccessFn | None = None) -> None:
    """Register workspace routes and open the DB connection."""
    db_path = get_db_path(config)
    con = connect(db_path)
    ensure_schema(con)
    app[APP_WORKSPACE_CON] = con
    app[APP_WORKSPACE_REQUIRE_API_ACCESS] = require_api_access or _require_default_api_access
    log.info("workspace.rbac_multi_tenant: DB at %s", db_path)

    async def _close_workspace_connection(app_: web.Application) -> None:
        con_ = app_.get(APP_WORKSPACE_CON)
        if con_ is None:
            return
        try:
            con_.close()
        except Exception as e:
            log.debug("workspace db close failed: %s", e)

    app.on_cleanup.append(_close_workspace_connection)

    r = app.router
    r.add_get("/api/workspaces", h_list_workspaces)
    r.add_post("/api/workspaces", h_create_workspace)
    r.add_get("/api/workspaces/current", h_current_workspace)
    r.add_get("/api/workspaces/current/membership", h_current_membership)
    r.add_post("/api/workspaces/invites/accept", h_accept_invite)
    r.add_get("/api/workspaces/{workspace_id}/members", h_list_members)
    r.add_post("/api/workspaces/{workspace_id}/invites", h_create_invite)
    r.add_get("/api/workspaces/{workspace_id}/invites", h_list_invites)
    r.add_patch("/api/workspaces/{workspace_id}/members/{user_id}", h_change_role)
    r.add_delete("/api/workspaces/{workspace_id}/members/{user_id}", h_revoke_member)
