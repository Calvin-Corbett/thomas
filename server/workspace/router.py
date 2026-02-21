from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from .deps import enforce_workspace, require_roles, get_db, get_current_user, WorkspaceContext
from .models import Workspace, WorkspaceMembership, WorkspaceInvite
from .rbac import WorkspaceRole
from .schemas import (
    WorkspaceOut,
    WorkspaceCreateIn,
    MembershipOut,
    InviteCreateIn,
    InviteOut,
    InviteCreateOut,
)


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=List[WorkspaceOut])
def list_workspaces(user=Depends(get_current_user), db: Session = Depends(get_db)):
    user_id = str(getattr(user, "id", getattr(user, "user_id", "")))
    rows = db.execute(
        select(Workspace)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.workspace_id)
        .where(WorkspaceMembership.user_id == user_id)
        .where(WorkspaceMembership.is_active == True)  # noqa: E712
        .order_by(Workspace.created_at.asc())
    ).scalars().all()
    return rows


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_workspace(data: WorkspaceCreateIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    user_id = str(getattr(user, "id", getattr(user, "user_id", "")))
    ws = Workspace(name=data.name, owner_user_id=user_id)
    db.add(ws)
    db.flush()

    membership = WorkspaceMembership(
        workspace_id=ws.workspace_id,
        user_id=user_id,
        role=WorkspaceRole.owner.value,
        is_active=True,
    )
    db.add(membership)
    db.commit()
    db.refresh(ws)
    return ws


@router.get("/current", response_model=WorkspaceOut)
def get_current_workspace(ctx: WorkspaceContext = Depends(enforce_workspace)):
    return ctx.workspace


@router.get("/current/membership", response_model=MembershipOut)
def get_current_membership(ctx: WorkspaceContext = Depends(enforce_workspace)):
    return ctx.membership


# ---- Admin ----

@router.get("/{workspace_id}/members", response_model=List[MembershipOut])
def list_members(
    workspace_id: str,
    ctx: WorkspaceContext = Depends(require_roles([WorkspaceRole.admin, WorkspaceRole.owner])),
    db: Session = Depends(get_db),
):
    if ctx.workspace.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Workspace mismatch")
    return db.execute(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .order_by(WorkspaceMembership.created_at.asc())
    ).scalars().all()


@router.post("/{workspace_id}/invites", response_model=InviteCreateOut, status_code=status.HTTP_201_CREATED)
def create_invite(
    workspace_id: str,
    data: InviteCreateIn,
    ctx: WorkspaceContext = Depends(require_roles([WorkspaceRole.admin, WorkspaceRole.owner])),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if ctx.workspace.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Workspace mismatch")

    raw, token_hash = WorkspaceInvite.new_token_pair()
    inv = WorkspaceInvite(
        workspace_id=workspace_id,
        email=data.email.strip().lower(),
        role=data.role,
        token_hash=token_hash,
        created_by_user_id=str(getattr(user, "id", getattr(user, "user_id", ""))) or None,
        note=data.note,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return InviteCreateOut(invite=inv, invite_token=raw)


@router.get("/{workspace_id}/invites", response_model=List[InviteOut])
def list_invites(
    workspace_id: str,
    ctx: WorkspaceContext = Depends(require_roles([WorkspaceRole.admin, WorkspaceRole.owner])),
    db: Session = Depends(get_db),
):
    if ctx.workspace.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Workspace mismatch")
    return db.execute(
        select(WorkspaceInvite)
        .where(WorkspaceInvite.workspace_id == workspace_id)
        .order_by(WorkspaceInvite.created_at.desc())
    ).scalars().all()


@router.post("/invites/accept", response_model=MembershipOut)
def accept_invite(
    payload: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    token = str(payload.get("invite_token", "")).strip()
    if not token:
        raise HTTPException(status_code=400, detail="invite_token required")

    user_id = str(getattr(user, "id", getattr(user, "user_id", "")))
    token_hash = WorkspaceInvite.hash_raw_token(token)
    inv = db.execute(select(WorkspaceInvite).where(WorkspaceInvite.token_hash == token_hash).limit(1)).scalars().first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found")
    if inv.revoked_at is not None:
        raise HTTPException(status_code=410, detail="Invite revoked")
    if inv.accepted_at is not None:
        raise HTTPException(status_code=409, detail="Invite already used")
    if inv.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Invite expired")

    existing = db.execute(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == inv.workspace_id)
        .where(WorkspaceMembership.user_id == user_id)
        .limit(1)
    ).scalars().first()

    if existing:
        existing.is_active = True
        existing.role = inv.role
        membership = existing
    else:
        membership = WorkspaceMembership(
            workspace_id=inv.workspace_id,
            user_id=user_id,
            role=inv.role,
            is_active=True,
        )
        db.add(membership)

    inv.accepted_at = datetime.utcnow()
    db.commit()
    db.refresh(membership)
    return membership


@router.patch("/{workspace_id}/members/{user_id}", response_model=MembershipOut)
def change_role(
    workspace_id: str,
    user_id: str,
    role: str,
    ctx: WorkspaceContext = Depends(require_roles([WorkspaceRole.admin, WorkspaceRole.owner])),
    db: Session = Depends(get_db),
):
    if ctx.workspace.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Workspace mismatch")

    target = db.execute(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.user_id == user_id)
        .limit(1)
    ).scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if ctx.role == WorkspaceRole.admin and str(target.role) == WorkspaceRole.owner.value:
        raise HTTPException(status_code=403, detail="Admins cannot modify owners")

    target.role = role
    db.commit()
    db.refresh(target)
    return target


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_member(
    workspace_id: str,
    user_id: str,
    ctx: WorkspaceContext = Depends(require_roles([WorkspaceRole.admin, WorkspaceRole.owner])),
    db: Session = Depends(get_db),
):
    if ctx.workspace.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Workspace mismatch")

    target = db.execute(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.user_id == user_id)
        .limit(1)
    ).scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if str(target.role) == WorkspaceRole.owner.value:
        raise HTTPException(status_code=403, detail="Cannot revoke owner")

    target.is_active = False
    db.commit()
    return None
