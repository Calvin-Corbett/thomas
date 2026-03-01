from __future__ import annotations

import secrets
import hashlib
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import String, DateTime, Boolean, UniqueConstraint, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

try:
    from server.db.base import Base
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        "Expected server.db.base.Base to exist. "
        "If your repo uses a different Base location, update server/workspace/models.py accordingly."
    ) from e

from .rbac import WorkspaceRole


_INVITE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,255}$")


def _normalize_invite_token(raw_token: str) -> str:
    token = str(raw_token).strip()
    if not _INVITE_TOKEN_RE.fullmatch(token):
        raise ValueError("Invalid invite token format")
    return token


def _utcnow() -> datetime:
    return datetime.utcnow()


def _new_id() -> str:
    # UUID-like string (36 chars) without importing uuid; good-enough for internal ids.
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


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Workspace(Base):
    __tablename__ = "workspaces"

    workspace_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_workspaces_owner_user_id", "owner_user_id"),
    )


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"

    membership_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=WorkspaceRole.member.value)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_memberships_workspace_user"),
        Index("ix_workspace_memberships_workspace_role", "workspace_id", "role"),
    )


class WorkspaceInvite(Base):
    __tablename__ = "workspace_invites"

    invite_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=WorkspaceRole.member.value)

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: _utcnow() + timedelta(days=7), nullable=False)

    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_workspace_invites_workspace_status", "workspace_id", "revoked_at", "accepted_at"),
    )

    @staticmethod
    def new_token_pair() -> tuple[str, str]:
        raw = secrets.token_urlsafe(32)
        return raw, _hash_token(raw)

    @staticmethod
    def hash_raw_token(raw: str) -> str:
        return _hash_token(_normalize_invite_token(raw))
