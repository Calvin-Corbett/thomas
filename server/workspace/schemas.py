from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class WorkspaceOut(BaseModel):
    workspace_id: str
    name: str
    owner_user_id: str | None = None
    created_at: datetime

    class Config:
        orm_mode = True


class WorkspaceCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MembershipOut(BaseModel):
    workspace_id: str
    user_id: str
    role: str
    created_at: datetime
    is_active: bool

    class Config:
        orm_mode = True


class InviteCreateIn(BaseModel):
    email: str
    role: str = "member"
    note: str | None = None


class InviteOut(BaseModel):
    invite_id: str
    workspace_id: str
    email: str
    role: str
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    note: str | None = None

    class Config:
        orm_mode = True


class InviteCreateOut(BaseModel):
    invite: InviteOut
    invite_token: str  # show once; not stored
