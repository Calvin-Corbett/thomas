from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from thomas.server.app_keys import APP_SECRETS
from thomas.server.routes.work_connector_runtime import connect_account_secret
from thomas.server.secrets import SecretStore
from thomas.work import WorkDependencyUnavailableError, WorkStore


def test_failed_staged_reconnect_cannot_replace_active_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WorkStore(tmp_path / "work")
    account = store.create_account(
        {"id": "owner", "provider": "gmail", "label": "Owner", "identity": "owner@example.com"}
    )
    secret_store = SecretStore(tmp_path / "secrets")
    old_ref = "secret:work/gmail/owner/original"
    secret_store.set(old_ref, "old-token", persist=True)
    store.update_account(account["id"], {"credential_ref": old_ref, "status": "active"})
    app = web.Application()
    app[APP_SECRETS] = secret_store

    def fail_persist(_state: dict[str, Any]) -> None:
        raise OSError("Work state disk unavailable")

    def fail_clear(_reference: str) -> None:
        raise OSError("Secret cleanup disk unavailable")

    monkeypatch.setattr(store, "_persist", fail_persist)
    monkeypatch.setattr(secret_store, "clear", fail_clear)

    with pytest.raises(WorkDependencyUnavailableError):
        connect_account_secret(app, store, account["id"], {"credential": "new-token"})

    stored = next(row for row in store.list_accounts(include_archived=True) if row["id"] == account["id"])
    assert stored["credential_ref"] == old_ref
    assert stored["status"] == "active"
    assert secret_store.get(old_ref) == "old-token"
