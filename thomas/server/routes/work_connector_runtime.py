"""Credential boundary helpers for canonical Thomas Work connector routes."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from aiohttp import web

from thomas.server.app_keys import APP_SECRETS
from thomas.work import WorkDependencyUnavailableError, WorkNotFoundError, WorkStore
from thomas.work.validation import clean_text

log = logging.getLogger(__name__)


def public_account(account: dict[str, Any]) -> dict[str, Any]:
    """Return connector identity and status without its SecretStore key."""

    public = dict(account)
    public["has_credentials"] = bool(public.pop("credential_ref", ""))
    return public


def connect_account_secret(
    app: web.Application,
    store: WorkStore,
    account_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist a connector credential before exposing only its safe status."""

    credential = clean_text(payload.get("credential"), field="credential", required=True, max_length=100_000)
    account = next(
        (row for row in store.list_accounts(include_archived=True) if row.get("id") == account_id),
        None,
    )
    if not isinstance(account, dict) or account.get("status") == "archived":
        raise WorkNotFoundError("active connector account not found")
    secret_store = app.get(APP_SECRETS)
    setter = getattr(secret_store, "set", None)
    if not callable(setter):
        raise WorkDependencyUnavailableError("connector credential storage is unavailable")

    previous_ref = str(account.get("credential_ref") or "")
    credential_ref = f"secret:work/{account['provider']}/{account_id}/{uuid4().hex}"
    clearer = getattr(secret_store, "clear", None)
    try:
        setter(credential_ref, credential, persist=True)
        connected = store.update_account(
            account_id,
            {"credential_ref": credential_ref, "status": "active"},
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        try:
            if callable(clearer):
                clearer(credential_ref)
        except (OSError, RuntimeError, TypeError, ValueError) as cleanup_exc:
            log.error(
                "Could not remove an unbound staged connector credential (%s)",
                type(cleanup_exc).__name__,
            )
        raise WorkDependencyUnavailableError("connector credentials could not be stored safely") from exc
    if previous_ref and previous_ref != credential_ref and callable(clearer):
        try:
            clearer(previous_ref)
        except (OSError, RuntimeError, TypeError, ValueError) as cleanup_exc:
            log.warning("Could not remove superseded connector credential (%s)", type(cleanup_exc).__name__)
    return public_account(connected)


__all__ = ["connect_account_secret", "public_account"]
