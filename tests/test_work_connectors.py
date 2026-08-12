from __future__ import annotations

import pytest

from thomas.work import WorkStore, WorkValidationError
from thomas.work.connectors import list_work_connectors


def test_work_connector_catalog_only_exposes_installed_integrations() -> None:
    rows = list_work_connectors()
    ids = {str(row["id"]) for row in rows}

    assert ids == {"gmail", "google_drive", "google_calendar"}
    assert len(ids) == len(rows)
    assert all(row["installed"] is True for row in rows)
    assert all(row["identity_hint"] and row["scopes"] for row in rows)
    assert {str(row["id"]): row["scopes"] for row in rows} == {
        "gmail": ["read", "send"],
        "google_drive": ["read", "write"],
        "google_calendar": ["read", "write"],
    }


def test_connector_accounts_reject_uninstalled_provider(tmp_path) -> None:
    store = WorkStore(tmp_path)
    with pytest.raises(WorkValidationError, match="not an installed Work connector"):
        store.create_account({"provider": "made_up_connector", "label": "Nope", "identity": "nobody@example.com"})
