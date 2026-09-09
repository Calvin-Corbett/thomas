from __future__ import annotations

from fastapi import HTTPException, Request

from .config import IntakeServerConfig


def require_token_if_configured(request: Request, cfg: IntakeServerConfig) -> None:
    if not cfg.token:
        return

    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    tok = auth.split(" ", 1)[1].strip()
    if tok != cfg.token:
        raise HTTPException(status_code=403, detail="Invalid token")
