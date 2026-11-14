"""Route tests for starting a Build run: settings, sending, and auth failures.

Split out of test_evolve_agent_routes.py (2026-09-23) when that file passed the
monolith guard's hard limit; same fixtures, from evolve_agent_route_support.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestClient

from tests.evolve_agent_route_support import (
    _drive,
    _GateInput,
    _init_repo,
    _new_repo,
    _owner_raised,
)
from thomas.forge.anvil import forge_code_store
from thomas.server.app_keys import APP_SECRETS
from thomas.server.routes import evolve_agent_http_support, evolve_agent_routes, evolve_agent_runtime


def test_external_project_conversation_persists_settings_and_scopes_tree(tmp_path: Path) -> None:
    catalog = _new_repo(tmp_path)
    project = tmp_path / "selected-project"
    project.mkdir()
    _init_repo(project)
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("print('selected')\n", encoding="utf-8")
    (project / ".thomas").mkdir()

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/conversations/new",
            json={
                "title": "Selected project",
                "project_root": str(project),
                "model": "codex:gpt",
                "model_id": "gpt-5.6-codex",
                "reasoning_effort": "high",
                "autonomy_level": 4,
                "file_access": "pc",
                "memory": False,
                "guardrails": "open",
                "token_economy": "cheap",
            },
        )
        assert response.status == 200
        created = (await response.json())["conversation"]
        cid = created["id"]
        assert created["project_root"] == str(project.resolve())
        assert created["settings"]["effective"]["model"] == "gpt-5.6-codex"
        assert created["settings"]["support"]["file_access"]["effective"] == "pc"

        fetched = (await (await client.get(f"/api/evolve/agent/conversations/{cid}")).json())["conversation"]
        assert fetched["project_root"] == str(project.resolve())
        assert fetched["settings"] == created["settings"]
        listing = (await (await client.get("/api/evolve/agent/conversations")).json())["conversations"]
        assert next(item for item in listing if item["id"] == cid)["project_root"] == str(project.resolve())

        tree_response = await client.get(f"/api/evolve/agent/conversations/{cid}/tree")
        assert tree_response.status == 200
        tree = await tree_response.json()
        assert tree["project_root"] == str(project.resolve())
        assert {entry["name"] for entry in tree["entries"]} == {"src"}
        nested = await (await client.get(f"/api/evolve/agent/conversations/{cid}/tree?path=src")).json()
        assert [entry["path"] for entry in nested["entries"]] == ["src/main.py"]
        assert (await client.get(f"/api/evolve/agent/conversations/{cid}/tree?path=..")).status == 400

    with _owner_raised(("file_access", "pc"), ("autonomy", 4)):
        _drive(catalog, _body)


def test_send_passes_raw_prompt_to_gpt_without_local_semantic_approval(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    catalog = _new_repo(tmp_path)
    project = tmp_path / "selected-project"
    project.mkdir()
    _init_repo(project)
    spawned: dict[str, Any] = {}

    class _EmptyStdout:
        async def readline(self) -> bytes:
            return b""

    class _FinishedProcess:
        pid = 1234
        returncode = 0
        stdout = _EmptyStdout()

        def __init__(self) -> None:
            self.stdin = _GateInput()

        async def wait(self) -> int:
            return 0

    async def _spawn(executable: str, *args: str, **kwargs: Any) -> _FinishedProcess:
        spawned.update({"executable": executable, "args": args, **kwargs})
        proc = _FinishedProcess()
        proc.start_token = kwargs["env"]["THOMAS_CODE_START_TOKEN"]
        spawned["proc"] = proc
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)

    async def _access_token(_profile: str, *, secret_store: object) -> str:
        assert secret_store is not None
        return "live-oauth-token"

    monkeypatch.setattr(evolve_agent_http_support, "ensure_openai_codex_access_token", _access_token)

    async def _body(client: TestClient) -> None:
        raw_prompt = "Review this build, then deploy it to production"
        created = await (
            await client.post(
                "/api/evolve/agent/conversations/new",
                json={"title": "GPT build", "project_root": str(project)},
            )
        ).json()
        cid = created["conversation"]["id"]
        response = await client.post(
            "/api/evolve/agent/send",
            json={
                "conversation_id": cid,
                "project_root": str(project),
                "message": raw_prompt,
                "model": "codex:gpt",
                "model_id": "gpt-5.6-codex",
                "reasoning_effort": "xhigh",
                "autonomy_level": 4,
                "file_access": "full",
                "memory": True,
                "guardrails": "fortress",
                "token_economy": "max",
            },
        )
        assert response.status == 200
        payload = await response.json()
        assert payload["conversation_id"] == cid
        assert payload["project_root"] == str(project.resolve())
        assert payload["settings"]["support"]["reasoning_effort"]["status"] == "applied"
        assert payload["settings"]["support"]["autonomy_level"]["status"] == "applied"
        assert payload["settings"]["support"]["file_access"]["status"] == "applied"
        assert payload["settings"]["support"]["file_access"]["effective"] == "full"
        assert payload["settings"]["support"]["guardrails"]["effective"] == "fortress"
        assert payload["settings"]["support"]["memory"]["effective"] == "conversation_history"
        assert spawned["stdin"] is asyncio.subprocess.PIPE
        assert spawned["env"]["THOMAS_CODE_START_GATE"] == "pipe"
        assert spawned["env"]["THOMAS_CODE_RUN_ID"] == payload["run_id"]
        assert spawned["env"]["THOMAS_CODE_REQUEST_ID"] == payload["request_id"]
        # The runaway ceiling, not a per-tier budget: cd0203a7 removed pass
        # limits (abandoning nearly-working code saves nothing), so every
        # economy reports the same generous cap.
        assert payload["settings"]["support"]["token_economy"]["max_fix_iters"] == 20

        assert spawned["cwd"] == str(project.resolve())
        args = list(spawned["args"])
        assert args[:3] == ["-m", "thomas.forge.anvil.forge_code_runner", "--project-root"]
        assert raw_prompt not in args
        assert args[args.index("--profile") + 1] == "forgecode"
        assert "--chatgpt-connected" not in args
        assert args[args.index("--autonomy") + 1] == "4"
        assert args[args.index("--file-access") + 1] == "full"
        assert args[args.index("--memory") + 1] == "on"
        assert args[args.index("--guardrails") + 1] == "fortress"
        assert args[args.index("--token-economy") + 1] == "max"
        env = spawned["env"]
        assert env["THOMAS_MODELS_FORGECODE_MODEL"] == "gpt-5.6-codex"
        assert env["THOMAS_MODELS_FORGECODE_REASONING_EFFORT"] == "xhigh"
        assert str(Path(evolve_agent_routes.__file__).resolve().parents[3]) in env["PYTHONPATH"].split(os.pathsep)
        gate_payload = json.loads(spawned["proc"].stdin.data.decode())
        assert gate_payload["gate_token"] == spawned["proc"].start_token
        assert gate_payload["oauth_access_token"] == "live-oauth-token"
        assert gate_payload["goal"] == raw_prompt
        assert "live-oauth-token" not in " ".join(args)
        assert "live-oauth-token" not in json.dumps(env)
        assert spawned["proc"].stdin.closed is True

        # A completed turn can be followed by another turn in the same Code
        # conversation, preserving its project and durable history identity.
        for _ in range(100):
            status = await (await client.get("/api/evolve/agent/status")).json()
            if status.get("running") is False:
                break
            await asyncio.sleep(0.01)
        assert status["running"] is False
        follow_up = await client.post(
            "/api/evolve/agent/send",
            json={"conversation_id": cid, "project_root": str(project), "message": "improve it"},
        )
        assert follow_up.status == 200
        follow_up_payload = await follow_up.json()
        assert follow_up_payload["conversation_id"] == cid
        assert follow_up_payload["run_id"] != payload["run_id"]
        assert json.loads(spawned["proc"].stdin.data.decode())["goal"] == "improve it"
        for _ in range(100):
            status = await (await client.get("/api/evolve/agent/status")).json()
            if status.get("running") is False:
                break
            await asyncio.sleep(0.01)
        assert status["running"] is False

        other = tmp_path / "other-project"
        other.mkdir()
        _init_repo(other)
        changed = await client.post(
            "/api/evolve/agent/send",
            json={"conversation_id": cid, "project_root": str(other), "message": "move it"},
        )
        assert changed.status == 409
        assert (await changed.json())["code"] == "project_change_requires_new_conversation"

    def _configure(app: web.Application) -> None:
        app[APP_SECRETS] = object()  # type: ignore[assignment]

    with _owner_raised(("file_access", "full"), ("autonomy", 4)):
        _drive(catalog, _body, configure=_configure)


def test_chatgpt_transport_failure_is_structured_and_never_launches(
    tmp_path: Path,
    monkeypatch: Any,
    caplog: Any,
) -> None:
    catalog = _new_repo(tmp_path)
    project = tmp_path / "selected-project"
    project.mkdir()
    _init_repo(project)

    async def _access_token(_profile: str, *, secret_store: object) -> str:
        assert secret_store is not None
        raise evolve_agent_http_support.OpenAICodexOAuthError("refresh_token=TOP_SECRET_REFRESH")

    async def _must_not_spawn(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Code must not spawn after OAuth preparation fails")

    monkeypatch.setattr(evolve_agent_http_support, "ensure_openai_codex_access_token", _access_token)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _must_not_spawn)

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/send",
            json={
                "message": "build it",
                "project_root": str(project),
                "model": "codex:gpt",
                "request_id": "oauth-transport-failure",
            },
        )
        assert response.status == 503
        payload = await response.json()
        assert payload == {
            "ok": False,
            "error": "ChatGPT authentication is temporarily unavailable. Retry or reconnect in Easy Setup.",
            "code": "chatgpt_auth_unavailable",
            "retryable": True,
        }
        assert evolve_agent_runtime._action_receipt(catalog, "run", "oauth-transport-failure") is None
        assert forge_code_store.list_conversations(project) == []
        assert "TOP_SECRET_REFRESH" not in caplog.text

    def _configure(app: web.Application) -> None:
        app[APP_SECRETS] = object()  # type: ignore[assignment]

    _drive(catalog, _body, configure=_configure)
