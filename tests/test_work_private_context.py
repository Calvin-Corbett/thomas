from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web

from thomas.server.routes.chat_v2_work_context import (
    WorkContextError,
    resolve_work_private_context,
)
from thomas.server.routes.work import APP_WORK_STORE
from thomas.work import WorkStore


def _app_with_jobs(root: Path) -> web.Application:
    store = WorkStore(root)
    app = store.create_app({"id": "mail", "name": "Mail", "goal": "Triage mail"})
    first = store.create_job(app["id"], {"id": "alpha", "name": "Alpha", "goal": "Alpha goal"})
    second = store.create_job(app["id"], {"id": "beta", "name": "Beta", "goal": "Beta goal"})
    store.update_job_memory(
        app["id"],
        first["id"],
        {"summary": "ALPHA_ONLY_MEMORY", "workflows": [{"name": "alpha-flow"}]},
    )
    store.update_job_memory(
        app["id"],
        second["id"],
        {"summary": "BETA_ONLY_MEMORY", "workflows": [{"name": "beta-flow"}]},
    )
    store.create_skill(
        app["id"],
        first["id"],
        {"id": "alpha-skill", "name": "ALPHA_ONLY_SKILL", "description": "alpha"},
    )
    store.create_account(
        {
            "id": "gmail-alpha",
            "provider": "gmail",
            "label": "Alpha Inbox",
            "identity": "alpha@example.com",
            "credential_ref": "secret:gmail-alpha",
        }
    )
    store.bind_account(app["id"], first["id"], {"account_id": "gmail-alpha", "scopes": ["mail.read"]})
    aiohttp_app = web.Application()
    aiohttp_app[APP_WORK_STORE] = store
    return aiohttp_app


def test_work_private_context_is_derived_from_exact_server_job(tmp_path: Path) -> None:
    app = _app_with_jobs(tmp_path)

    alpha = json.loads(
        resolve_work_private_context(
            app,
            surface_mode="work",
            context_id="mail:alpha",
            client_private_context=None,
        )
    )
    beta = json.loads(
        resolve_work_private_context(
            app,
            surface_mode="work",
            context_id="mail:beta",
            client_private_context=None,
        )
    )

    assert alpha["work_job_id"] == "alpha"
    assert alpha["job_memory"]["summary"] == "ALPHA_ONLY_MEMORY"
    assert alpha["private_skills"][0]["name"] == "ALPHA_ONLY_SKILL"
    assert alpha["connector_bindings"][0]["identity"] == "alpha@example.com"
    assert "credential_ref" not in alpha["connector_bindings"][0]
    assert beta["work_job_id"] == "beta"
    assert beta["job_memory"]["summary"] == "BETA_ONLY_MEMORY"
    assert beta["private_skills"] == []


def test_work_private_context_rejects_client_injection_and_unknown_jobs(tmp_path: Path) -> None:
    app = _app_with_jobs(tmp_path)

    with pytest.raises(WorkContextError, match="cannot be supplied") as injection:
        resolve_work_private_context(
            app,
            surface_mode="work",
            context_id="mail:beta",
            client_private_context='{"job_memory":"ALPHA_ONLY_MEMORY"}',
        )
    assert injection.value.status == 400

    with pytest.raises(WorkContextError, match="not found") as missing:
        resolve_work_private_context(
            app,
            surface_mode="work",
            context_id="mail:missing",
            client_private_context=None,
        )
    assert missing.value.status == 404


def test_onboarding_namespaces_do_not_claim_job_private_context(tmp_path: Path) -> None:
    app = _app_with_jobs(tmp_path)

    assert (
        resolve_work_private_context(
            app,
            surface_mode="work",
            context_id="mail:onboarding:session-1",
            client_private_context=None,
        )
        == ""
    )
