from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class WorkspaceOut(BaseModel):
    workspace_id: str
    name: str
    owner_user_id: Optional[str] = None
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
    note: Optional[str] = None


class InviteOut(BaseModel):
    invite_id: str
    workspace_id: str
    email: str
    role: str
    created_at: datetime
    expires_at: datetime
    accepted_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    note: Optional[str] = None

    class Config:
        orm_mode = True


class InviteCreateOut(BaseModel):
    invite: InviteOut
    invite_token: str  # show once; not stored
