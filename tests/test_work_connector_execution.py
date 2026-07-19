from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from aiohttp import web

from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.server import worker_runtime
from thomas.server.app_keys import APP_SECRETS
from thomas.server.routes.work import APP_WORK_STORE
from thomas.server.work_connector_registry import WorkExecutionBinding, bind_work_connector_tools
from thomas.server.work_connector_runtime import APP_WORK_CONNECTOR_EXECUTOR, request_work_tools
from thomas.server.work_google_connector import GoogleWorkspaceConnectorExecutor
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry
from thomas.work import WorkStore


class _EmailReadTool(Tool):
    name = "email.read"
    description = "Read email"
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        self.calls.append(dict(args))
        return ToolResult(ok=True, data={"unsafe_base_execution": True})


class _SecretStore:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = dict(values)

    def get(self, key: str) -> str | None:
        return self.values.get(key)


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def execute(
        self,
        binding: WorkExecutionBinding,
        tool_name: str,
        args: dict[str, Any],
        credential_secret: str,
    ) -> ToolResult:
        await asyncio.sleep(0.02 if binding.account_id.endswith("alpha") else 0)
        self.calls.append((binding.account_id, credential_secret, dict(args)))
        return ToolResult(ok=True, data={"account_id": binding.account_id, "tool": tool_name})


def _job_with_account(
    store: WorkStore,
    *,
    app_id: str,
    job_id: str,
    account_id: str,
    credential_ref: str,
) -> str:
    if not any(row.get("id") == app_id for row in store.list_apps()):
        store.create_app({"id": app_id, "name": app_id.title(), "goal": "Process mail"})
    job = store.create_job(app_id, {"id": job_id, "name": job_id.title(), "goal": "Process mail"})
    store.create_account(
        {
            "id": account_id,
            "provider": "gmail",
            "label": account_id,
            "identity": f"{account_id}@example.com",
            "credential_ref": credential_ref,
        }
    )
    store.bind_account(app_id, job["id"], {"account_id": account_id, "scopes": ["mail.read"]})
    return f"{app_id}:{job_id}"


def _registry() -> tuple[ToolRegistry, _EmailReadTool]:
    registry = ToolRegistry()
    tool = _EmailReadTool()
    registry.register(tool)
    return registry, tool


def test_two_work_jobs_consume_their_own_gmail_credentials_concurrently(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    alpha_context = _job_with_account(
        store,
        app_id="mail",
        job_id="alpha",
        account_id="gmail-alpha",
        credential_ref="secret:gmail-alpha",
    )
    beta_context = _job_with_account(
        store,
        app_id="mail",
        job_id="beta",
        account_id="gmail-beta",
        credential_ref="secret:gmail-beta",
    )
    secrets = _SecretStore({"secret:gmail-alpha": "TOKEN_ALPHA", "secret:gmail-beta": "TOKEN_BETA"})
    executor = _RecordingExecutor()
    registry, base_tool = _registry()
    alpha_tools = bind_work_connector_tools(
        registry, store=store, secret_store=secrets, context_id=alpha_context, executor=executor
    )
    beta_tools = bind_work_connector_tools(
        registry, store=store, secret_store=secrets, context_id=beta_context, executor=executor
    )

    async def run() -> tuple[ToolResult, ToolResult]:
        alpha, beta = await asyncio.gather(
            alpha_tools.execute("email.read", {"count": 2}),
            beta_tools.execute("email.read", {"count": 3}),
        )
        return alpha, beta

    alpha_result, beta_result = asyncio.run(run())
    assert alpha_result.ok and alpha_result.data["account_id"] == "gmail-alpha"
    assert beta_result.ok and beta_result.data["account_id"] == "gmail-beta"
    assert {(account, secret) for account, secret, _args in executor.calls} == {
        ("gmail-alpha", "TOKEN_ALPHA"),
        ("gmail-beta", "TOKEN_BETA"),
    }
    assert base_tool.calls == []

    alias_result = asyncio.run(alpha_tools.execute("functions.email.read", {}))
    assert alias_result.ok and alias_result.data["account_id"] == "gmail-alpha"
    assert base_tool.calls == []


def test_connector_execution_fails_closed_for_ambiguous_inactive_and_missing_secrets(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    context = _job_with_account(
        store,
        app_id="mail",
        job_id="triage",
        account_id="gmail-alpha",
        credential_ref="secret:gmail-alpha",
    )
    store.create_account(
        {
            "id": "gmail-beta",
            "provider": "gmail",
            "label": "Beta",
            "identity": "beta@example.com",
            "credential_ref": "secret:gmail-beta",
        }
    )
    store.bind_account("mail", "triage", {"account_id": "gmail-beta", "scopes": ["mail.read"]})
    executor = _RecordingExecutor()
    registry, base_tool = _registry()
    tools = bind_work_connector_tools(
        registry,
        store=store,
        secret_store=_SecretStore({"secret:gmail-alpha": "ALPHA"}),
        context_id=context,
        executor=executor,
    )

    ambiguous = asyncio.run(tools.execute("email.read", {}))
    missing = asyncio.run(tools.execute("email.read", {"work_account_id": "gmail-beta"}))
    store.update_account("gmail-alpha", {"status": "needs_reconnect"})
    inactive_tools = bind_work_connector_tools(
        registry,
        store=store,
        secret_store=_SecretStore({"secret:gmail-alpha": "ALPHA"}),
        context_id=context,
        executor=executor,
    )
    inactive = asyncio.run(inactive_tools.execute("email.read", {"work_account_id": "gmail-alpha"}))
    assert not ambiguous.ok and "Multiple gmail accounts" in str(ambiguous.error)
    assert not missing.ok and "unavailable" in str(missing.error)
    assert not inactive.ok and "No active gmail account" in str(inactive.error)
    combined = f"{ambiguous.error} {missing.error} {inactive.error}"
    assert "secret:gmail" not in combined and "ALPHA" not in combined
    assert executor.calls == [] and base_tool.calls == []


def test_server_wiring_uses_injected_executor_without_exposing_credential_ref(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    context = _job_with_account(
        store,
        app_id="mail",
        job_id="owner",
        account_id="gmail-owner",
        credential_ref="secret:owner-private",
    )
    executor = _RecordingExecutor()
    registry, _base_tool = _registry()
    app = web.Application()
    app[APP_WORK_STORE] = store
    app[APP_SECRETS] = _SecretStore({"secret:owner-private": "OWNER_TOKEN"})  # type: ignore[assignment]
    app[APP_WORK_CONNECTOR_EXECUTOR] = executor

    tools = request_work_tools(app, registry, context_id=context)
    result = asyncio.run(tools.execute("email.read", {}))

    assert result.ok and result.data == {"account_id": "gmail-owner", "tool": "email.read"}
    assert executor.calls == [("gmail-owner", "OWNER_TOKEN", {})]
    assert "secret:owner-private" not in json.dumps(result.data)


def test_google_executor_passes_only_selected_token_to_fresh_integration() -> None:
    observed: list[dict[str, Any]] = []

    class FakeIntegration:
        def __init__(self, **kwargs: Any) -> None:
            self.store = kwargs["secrets_manager"]

        async def connect(self) -> None:
            observed.append({"tokens": json.loads(self.store.get("tokens") or "{}")})

        async def execute(self, **kwargs: Any) -> dict[str, Any]:
            observed[-1]["call"] = kwargs
            return {"message_ids": ["msg-1"]}

        async def disconnect(self) -> None:
            return None

    binding = WorkExecutionBinding(
        binding_id="binding-owner",
        account_id="gmail-owner",
        provider="gmail",
        scopes=frozenset({"mail.read"}),
        credential_ref="secret:owner-private",
        account_status="active",
    )
    secret = json.dumps(
        {
            "oauth": {"client_id": "client", "client_secret": "client-secret"},
            "tokens": {"access_token": "ACCESS_OWNER", "expires_at": "2999-01-01T00:00:00"},
        }
    )
    executor = GoogleWorkspaceConnectorExecutor(integration_factory=FakeIntegration)
    result = asyncio.run(executor.execute(binding, "email.read", {"count": 4}, secret))

    assert result.ok
    assert observed[0]["tokens"]["access_token"] == "ACCESS_OWNER"
    assert observed[0]["call"]["service"] == "gmail"
    assert observed[0]["call"]["operation"] == "list_messages"
    assert observed[0]["call"]["max_results"] == 4
    assert "ACCESS_OWNER" not in json.dumps(result.data)
    assert "client-secret" not in json.dumps(result.data)


def test_provider_native_worker_uses_job_bound_registry(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    context = _job_with_account(
        store,
        app_id="mail",
        job_id="worker",
        account_id="gmail-worker",
        credential_ref="secret:gmail-worker",
    )
    executor = _RecordingExecutor()
    store.update_job_memory(
        "mail",
        "worker",
        {"summary": "Prepare only the owner's morning inbox brief."},
    )
    skill = store.create_skill(
        "mail",
        "worker",
        {
            "name": "Owner brief",
            "description": "Use the owner's preferred concise format.",
            "skill_ref": "Lead with urgent messages and named actions.",
        },
    )
    store.update_skill("mail", "worker", skill["id"], {"status": "active"})
    registry, base_tool = _registry()
    cfg = AppConfig()
    cfg.models = {"local": ModelConfig(name="local", provider="ollama", model="llama3")}
    cfg.default_model = "local"
    app = {
        worker_runtime.APP_CONFIG: cfg,
        worker_runtime.APP_SECRETS: _SecretStore({"secret:gmail-worker": "WORKER_TOKEN"}),
        worker_runtime.APP_MEMORY: None,
        APP_WORK_STORE: store,
        APP_WORK_CONNECTOR_EXECUTOR: executor,
    }

    class FakeLLM:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.config = _args[0]

        def reset_runtime_trace(self) -> None:
            return None

        async def close(self) -> None:
            return None

    system_prompts: list[str] = []

    class CallingAgentLoop:
        def __init__(self, _config: Any, _llm: Any, tools: Any, **kwargs: Any) -> None:
            self.tools = tools
            system_prompts.append(str(kwargs.get("system_prompt") or ""))

        async def run(self, _prompt: str, **_kwargs: Any):
            result = await self.tools.execute("email.read", {})
            yield SimpleNamespace(
                type=EventType.TOOL_RESULT,
                data={
                    "tool_name": "email.read",
                    "ok": result.ok,
                    "result_text": result.to_content(),
                },
            )
            yield SimpleNamespace(type=EventType.AGENT_DONE, data={"text": "Mail read", "iterations": 1})

    async def run() -> list[dict[str, Any]]:
        with (
            patch.object(worker_runtime, "LLMClient", FakeLLM),
            patch.object(worker_runtime, "AgentLoop", CallingAgentLoop),
            patch("thomas.server.app_helpers._build_tools", return_value=registry),
        ):
            return [
                event
                async for event in worker_runtime.run_agent_worker_events(
                    app,
                    prompt="Read the job inbox",
                    instructions="Use the bound account.",
                    work_dir=tmp_path,
                    profile="local",
                    work_context_id=context,
                )
            ]

    events = asyncio.run(run())
    assert any(event.get("type") == "tool_output" and event.get("ok") for event in events)
    assert executor.calls == [("gmail-worker", "WORKER_TOKEN", {})]
    assert base_tool.calls == []
    assert "Prepare only the owner's morning inbox brief." in system_prompts[0]
    assert "Lead with urgent messages and named actions." in system_prompts[0]
    assert "gmail-worker@example.com" in system_prompts[0]
    assert "secret:gmail-worker" not in system_prompts[0]
    assert "WORKER_TOKEN" not in system_prompts[0]
