from __future__ import annotations

from enum import Enum
from typing import Any, Iterable


class WorkspaceRole(str, Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


ROLE_RANK = {
    WorkspaceRole.owner: 3,
    WorkspaceRole.admin: 2,
    WorkspaceRole.member: 1,
    WorkspaceRole.viewer: 0,
}


def normalize_role(role: Any) -> WorkspaceRole:
    value = str(role or "").strip().lower()
    if not value:
        raise ValueError("role is required")
    try:
        return WorkspaceRole(value)
    except ValueError as exc:
        raise ValueError(f"unsupported role: {role!r}") from exc


def role_allows(current: WorkspaceRole, required: Iterable[WorkspaceRole]) -> bool:
    """True if current meets/exceeds at least one required role."""
    req = list(required)
    if not req:
        return True
    cur = ROLE_RANK[current]
    return any(cur >= ROLE_RANK[r] for r in req)


def can_manage_members(role: WorkspaceRole) -> bool:
    return role in (WorkspaceRole.owner, WorkspaceRole.admin)


def can_write(role: WorkspaceRole) -> bool:
    return role in (WorkspaceRole.owner, WorkspaceRole.admin, WorkspaceRole.member)
