from __future__ import annotations

import hashlib
import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso() -> str:
    return _utc_now().isoformat(timespec="seconds")


def _new_id() -> str:
    # UUID-like without importing uuid.
    return (
        secrets.token_hex(4)
        + "-"
        + secrets.token_hex(2)
        + "-"
        + secrets.token_hex(2)
        + "-"
        + secrets.token_hex(2)
        + "-"
        + secrets.token_hex(6)
    )[:36]


class WorkspaceRole:
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


ROLE_RANK = {
    WorkspaceRole.OWNER: 3,
    WorkspaceRole.ADMIN: 2,
    WorkspaceRole.MEMBER: 1,
    WorkspaceRole.VIEWER: 0,
}


def normalize_role(role: Any) -> str:
    value = str(role or "").strip().lower()
    if value not in ROLE_RANK:
        raise ValueError(f"unsupported role: {value or role!r}")
    return value


def role_allows(current: str, required: Iterable[str]) -> bool:
    req = [normalize_role(r) for r in required]
    if not req:
        return True
    cur_rank = ROLE_RANK[normalize_role(current)]
    return any(cur_rank >= ROLE_RANK[r] for r in req)


def can_manage_members(role: str) -> bool:
    role_val = normalize_role(role)
    return role_val in {WorkspaceRole.OWNER, WorkspaceRole.ADMIN}


def can_write(role: str) -> bool:
    role_val = normalize_role(role)
    return role_val in {WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.MEMBER}


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class WorkspaceStore:
    """File-backed workspace + RBAC store (single-process safe)."""

    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._state = self._load()

    def _blank(self) -> Dict[str, Any]:
        return {"workspaces": {}, "memberships": [], "invites": []}

    def _backup_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".bak")

    def _quarantine_corrupt_file(self) -> Optional[Path]:
        if not self.path.exists():
            return None
        stamp = _utc_now().strftime("%Y%m%dT%H%M%S")
        target = self.path.with_name(f"{self.path.name}.corrupt.{stamp}")
        try:
            self.path.replace(target)
            return target
        except Exception:
            return None

    def _load_from_file(self, src: Path) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        out = self._blank()
        workspaces = data.get("workspaces")
        memberships = data.get("memberships")
        invites = data.get("invites")
        if isinstance(workspaces, dict):
            out["workspaces"] = workspaces
        if isinstance(memberships, list):
            out["memberships"] = memberships
        if isinstance(invites, list):
            out["invites"] = invites
        return out

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return self._blank()
        loaded = self._load_from_file(self.path)
        if loaded is not None:
            return loaded

        # Preserve corrupt primary file for forensics and recover from backup.
        self._quarantine_corrupt_file()
        backup = self._backup_path()
        if backup.exists():
            recovered = self._load_from_file(backup)
            if recovered is not None:
                return recovered
        return self._blank()

    def _save(self) -> None:
        payload = json.dumps(self._state, ensure_ascii=False, indent=2)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        if self.path.exists():
            try:
                self._backup_path().write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                # Keep save path resilient; backup failures should not block writes.
                pass
        tmp.replace(self.path)

    def _memberships_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        uid = str(user_id or "").strip()
        rows = [
            m
            for m in self._state["memberships"]
            if str(m.get("user_id") or "").strip() == uid and bool(m.get("is_active", False))
        ]
        rows.sort(key=lambda r: str(r.get("created_at") or ""))
        return rows

    def _membership(self, workspace_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        wid = str(workspace_id or "").strip()
        uid = str(user_id or "").strip()
        for m in self._state["memberships"]:
            if str(m.get("workspace_id") or "").strip() != wid:
                continue
            if str(m.get("user_id") or "").strip() != uid:
                continue
            return m
        return None

    def list_workspaces(self, user_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = []
            for m in self._memberships_for_user(user_id):
                workspace_id = str(m.get("workspace_id") or "").strip()
                ws = self._state["workspaces"].get(workspace_id)
                if isinstance(ws, dict):
                    rows.append(dict(ws))
            rows.sort(key=lambda r: str(r.get("created_at") or ""))
            return rows

    def create_workspace(self, name: str, owner_user_id: str) -> Dict[str, Any]:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("workspace name is required")
        owner = str(owner_user_id or "").strip()
        if not owner:
            raise ValueError("owner user id is required")

        with self._lock:
            workspace_id = _new_id()
            ws = {
                "workspace_id": workspace_id,
                "name": clean_name,
                "owner_user_id": owner,
                "created_at": _utc_iso(),
            }
            self._state["workspaces"][workspace_id] = ws
            self._state["memberships"].append(
                {
                    "membership_id": _new_id(),
                    "workspace_id": workspace_id,
                    "user_id": owner,
                    "role": WorkspaceRole.OWNER,
                    "is_active": True,
                    "created_at": _utc_iso(),
                }
            )
            self._save()
            return dict(ws)

    def current_workspace(self, user_id: str, workspace_hint: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
        uid = str(user_id or "").strip()
        hint = str(workspace_hint or "").strip()
        if not uid:
            raise ValueError("user id is required")

        with self._lock:
            if hint:
                ws = self._state["workspaces"].get(hint)
                if not isinstance(ws, dict):
                    raise KeyError("workspace not found")
                membership = self._membership(hint, uid)
                if membership is None or not bool(membership.get("is_active", False)):
                    raise PermissionError("user is not a member of the workspace")
                return dict(ws), dict(membership)

            memberships = self._memberships_for_user(uid)
            if not memberships:
                raise KeyError("no workspace membership for user")
            selected = memberships[0]
            workspace_id = str(selected.get("workspace_id") or "")
            ws = self._state["workspaces"].get(workspace_id)
            if not isinstance(ws, dict):
                raise KeyError("workspace not found")
            return dict(ws), dict(selected)

    def membership(self, workspace_id: str, user_id: str) -> Dict[str, Any]:
        with self._lock:
            m = self._membership(workspace_id, user_id)
            if m is None or not bool(m.get("is_active", False)):
                raise KeyError("membership not found")
            return dict(m)

    def _ensure_manage_role(self, workspace_id: str, user_id: str) -> Dict[str, Any]:
        m = self.membership(workspace_id, user_id)
        role = normalize_role(m.get("role"))
        if not can_manage_members(role):
            raise PermissionError("requires admin or owner role")
        return m

    def list_members(self, workspace_id: str, actor_user_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            self._ensure_manage_role(workspace_id, actor_user_id)
            out = [dict(m) for m in self._state["memberships"] if str(m.get("workspace_id") or "") == str(workspace_id or "")]
            out.sort(key=lambda r: str(r.get("created_at") or ""))
            return out

    def create_invite(
        self,
        workspace_id: str,
        actor_user_id: str,
        *,
        email: str,
        role: str,
        note: str = "",
        expires_days: int = 7,
    ) -> Dict[str, Any]:
        clean_email = str(email or "").strip().lower()
        if not clean_email:
            raise ValueError("email is required")
        role_val = normalize_role(role)
        expires_days = max(1, min(30, int(expires_days)))

        with self._lock:
            if str(workspace_id or "").strip() not in self._state["workspaces"]:
                raise KeyError("workspace not found")
            self._ensure_manage_role(workspace_id, actor_user_id)

            raw = secrets.token_urlsafe(32)
            token_hash = _hash_token(raw)
            invite = {
                "invite_id": _new_id(),
                "workspace_id": str(workspace_id or "").strip(),
                "email": clean_email,
                "role": role_val,
                "token_hash": token_hash,
                "created_by_user_id": str(actor_user_id or "").strip() or None,
                "created_at": _utc_iso(),
                "expires_at": (_utc_now() + timedelta(days=expires_days)).isoformat(timespec="seconds"),
                "accepted_at": None,
                "revoked_at": None,
                "note": str(note or "").strip() or None,
            }
            self._state["invites"].append(invite)
            self._save()
            public_invite = dict(invite)
            public_invite.pop("token_hash", None)
            return {"invite": public_invite, "invite_token": raw}

    def list_invites(self, workspace_id: str, actor_user_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            self._ensure_manage_role(workspace_id, actor_user_id)
            out = []
            for inv in self._state["invites"]:
                if str(inv.get("workspace_id") or "").strip() != str(workspace_id or "").strip():
                    continue
                row = dict(inv)
                row.pop("token_hash", None)
                out.append(row)
            out.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
            return out

    def accept_invite(self, invite_token: str, user_id: str, email: str = "") -> Dict[str, Any]:
        token = str(invite_token or "").strip()
        uid = str(user_id or "").strip()
        user_email = str(email or "").strip().lower()
        if not token:
            raise ValueError("invite_token is required")
        if not uid:
            raise ValueError("user id is required")

        with self._lock:
            token_hash = _hash_token(token)
            invite = None
            for inv in self._state["invites"]:
                if str(inv.get("token_hash") or "") == token_hash:
                    invite = inv
                    break
            if invite is None:
                raise KeyError("invite not found")
            if invite.get("revoked_at"):
                raise PermissionError("invite revoked")
            if invite.get("accepted_at"):
                raise PermissionError("invite already accepted")
            expires_at = str(invite.get("expires_at") or "").strip()
            if expires_at:
                try:
                    exp = datetime.fromisoformat(expires_at)
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    if exp < _utc_now():
                        raise PermissionError("invite expired")
                except ValueError:
                    pass
            if user_email and str(invite.get("email") or "").strip().lower() not in {"", user_email}:
                raise PermissionError("invite email mismatch")

            workspace_id = str(invite.get("workspace_id") or "").strip()
            role_val = normalize_role(invite.get("role"))
            existing = self._membership(workspace_id, uid)
            if existing is None:
                membership = {
                    "membership_id": _new_id(),
                    "workspace_id": workspace_id,
                    "user_id": uid,
                    "role": role_val,
                    "is_active": True,
                    "created_at": _utc_iso(),
                }
                self._state["memberships"].append(membership)
            else:
                existing["is_active"] = True
                existing["role"] = role_val
                membership = existing

            invite["accepted_at"] = _utc_iso()
            self._save()
            return dict(membership)

    def change_role(self, workspace_id: str, actor_user_id: str, target_user_id: str, role: str) -> Dict[str, Any]:
        role_val = normalize_role(role)
        target_uid = str(target_user_id or "").strip()
        if not target_uid:
            raise ValueError("target user id is required")

        with self._lock:
            actor = self._ensure_manage_role(workspace_id, actor_user_id)
            target = self._membership(workspace_id, target_uid)
            if target is None:
                raise KeyError("member not found")

            actor_role = normalize_role(actor.get("role"))
            target_role = normalize_role(target.get("role"))
            if actor_role == WorkspaceRole.ADMIN and target_role == WorkspaceRole.OWNER:
                raise PermissionError("admins cannot modify owners")

            target["role"] = role_val
            target["is_active"] = True
            self._save()
            return dict(target)

    def revoke_member(self, workspace_id: str, actor_user_id: str, target_user_id: str) -> None:
        target_uid = str(target_user_id or "").strip()
        if not target_uid:
            raise ValueError("target user id is required")

        with self._lock:
            actor = self._ensure_manage_role(workspace_id, actor_user_id)
            target = self._membership(workspace_id, target_uid)
            if target is None:
                raise KeyError("member not found")

            actor_role = normalize_role(actor.get("role"))
            target_role = normalize_role(target.get("role"))
            if target_role == WorkspaceRole.OWNER:
                raise PermissionError("cannot revoke owner")
            if actor_role == WorkspaceRole.ADMIN and target_role == WorkspaceRole.ADMIN:
                raise PermissionError("admins cannot revoke admins")

            target["is_active"] = False
            self._save()
