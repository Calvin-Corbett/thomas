"""The Claude CLI gets the same per-run authenticated child channel."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from thomas.forge.anvil.dispatch_claude_cli import SAFE_CLI_TOOLS, dispatch_via_claude_cli
from thomas.forge.anvil.run_channel_client import RunChannelClient
from thomas.forge.anvil.run_channel_mcp import MCP_TOOL_NAMES, handle, server_config
from thomas.server.praxis import claude_child, launch
from thomas.server.routes.praxis_run_routes import register_praxis_run_routes


@pytest.mark.asyncio
async def test_mcp_shim_maps_spawn_wait_status_to_one_run_client():
    calls = []

    class Client:
        async def call(self, action, payload):
            calls.append((action, payload))
            return {"ok": True, "run_id": "run-one", "agents": []}

    client = Client()
    init = await handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, client)
    listed = await handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, client)
    assert init["result"]["serverInfo"]["name"] == "thomas_praxis"
    assert {tool["name"] for tool in listed["result"]["tools"]} == {
        "spawn_agents",
        "wait_agents",
        "agent_status",
        "stop_agent",
    }
    for name, args in (
        ("spawn_agents", {"units": [{"title": "Review"}], "why_parallel": "independent_reads"}),
        ("wait_agents", {"agent_ids": ["one"], "timeout": 1}),
        ("agent_status", {"agent_ids": ["one"]}),
    ):
        response = await handle(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": name, "arguments": args}}, client
        )
        assert not response["result"]["isError"]
        assert json.loads(response["result"]["content"][0]["text"])["run_id"] == "run-one"
    assert [action for action, _ in calls] == ["spawn", "wait", "status"]
    assert (await handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "other"}}, client))[
        "error"
    ]["code"] == -32601


def test_claude_launch_adds_only_run_scoped_mcp_without_changing_model_or_builtin_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("THOMAS_RUN_CHANNEL_URL", "http://127.0.0.1:8899")
    monkeypatch.setenv("THOMAS_CODE_RUN_ID", "run-one")
    monkeypatch.setenv("THOMAS_RUN_CHANNEL_TOKEN", "secret-one")
    seen = {}

    def runner(cmd, _cwd, _timeout):
        seen["cmd"] = cmd
        config = json.loads(open(cmd[cmd.index("--mcp-config") + 1], encoding="utf-8").read())
        seen["config"] = config
        return 1, ""

    dispatch_via_claude_cli(
        "Inspect project",
        cwd=tmp_path,
        model="sonnet",
        dry_run=False,
        runner=runner,
        claude_bin="claude",
        verify=False,
        allow_without_history=True,
    )
    cmd = seen["cmd"]
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    assert "--strict-mcp-config" in cmd
    assert tuple(cmd[cmd.index("--tools") + 1 : cmd.index("--allowedTools")]) == SAFE_CLI_TOOLS
    assert set(MCP_TOOL_NAMES).issubset(cmd)
    assert "Task" in cmd[cmd.index("--disallowedTools") + 1 : cmd.index("--output-format")]
    assert seen["config"] == server_config(seen["config"]["mcpServers"]["thomas_praxis"]["command"])
    assert "secret-one" not in json.dumps(seen["config"])


@pytest.mark.asyncio
async def test_mcp_shim_uses_real_loopback_token_and_rejects_another_run():
    app = web.Application()
    registry = register_praxis_run_routes(app)

    async def child(_agent_id, _kind, _title, _brief):
        yield {"type": "done", "text": "reviewed"}

    first = registry.open("first", child)
    registry.open("second", child)
    async with TestServer(app) as server:
        url = f"http://127.0.0.1:{server.port}"
        client = RunChannelClient(base_url=url, run_id="first", token=first.token)
        spawn = await handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "spawn_agents",
                    "arguments": {"units": [{"kind": "review", "title": "Review", "brief": "Inspect"}]},
                },
            },
            client,
        )
        child_id = json.loads(spawn["result"]["content"][0]["text"])["agents"][0]["agent_id"]
        waited = await handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "wait_agents", "arguments": {"agent_ids": [child_id], "timeout": 1}},
            },
            client,
        )
        assert json.loads(waited["result"]["content"][0]["text"])["agents"][0]["state"] == "completed"
        wrong = RunChannelClient(base_url=url, run_id="second", token=first.token)
        denied = await handle(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "agent_status", "arguments": {}}},
            wrong,
        )
        assert denied["result"]["isError"]


@pytest.mark.asyncio
@pytest.mark.parametrize("observed, success", [("claude-sonnet-real", True), ("gpt-5.6-luna", False)])
async def test_claude_child_uses_read_only_cli_and_observed_model(monkeypatch, tmp_path, observed, success):
    seen = {}

    class Stdin:
        def write(self, data):
            seen["prompt"] = data

        async def drain(self):
            pass

        def close(self):
            pass

    class Stdout:
        def __aiter__(self):
            self.lines = iter(
                [
                    json.dumps({"type": "system", "subtype": "init", "model": observed}).encode() + b"\n",
                    b'{"type":"result","is_error":false,"result":"Reviewed"}\n',
                ]
            )
            return self

        async def __anext__(self):
            try:
                return next(self.lines)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class Process:
        stdin = Stdin()
        stdout = Stdout()
        returncode = 0

        async def wait(self):
            return 0

        def kill(self):
            raise AssertionError("completed child must not be killed")

    async def create(*args, **kwargs):
        seen["args"], seen["cwd"] = args, kwargs["cwd"]
        return Process()

    monkeypatch.setattr(claude_child.shutil, "which", lambda name: "claude.exe" if name == "claude" else None)
    monkeypatch.setattr(claude_child.asyncio, "create_subprocess_exec", create)
    events = [
        event
        async for event in claude_child.build_claude_read_child_runner(tmp_path, model_id="claude:sonnet")(
            "child", "review", "Review", "Inspect project"
        )
    ]
    assert seen["args"][seen["args"].index("--model") + 1] == "sonnet"
    assert seen["cwd"] == str(tmp_path)
    assert "Task" in seen["args"] and "Edit" in seen["args"]
    assert b"Inspect project" in seen["prompt"]
    if success:
        assert events[-1] == {"type": "done", "text": "Reviewed", "model_used": observed}
    else:
        assert events[-1]["type"] == "error" and "expected sonnet" in events[-1]["error"]


@pytest.mark.asyncio
async def test_claude_build_launch_never_selects_gpt_child_runner(monkeypatch, tmp_path):
    captured = {}

    class Registry:
        def open(self, run_id, runner, **kwargs):
            captured.update(run_id=run_id, runner=runner)
            return SimpleNamespace(token="run-secret")

    def forbidden_gpt(*_args, **_kwargs):
        raise AssertionError("Claude lead cannot silently use the GPT child runner")

    async def sentinel(*_args):
        yield {"type": "done"}

    monkeypatch.setattr(launch, "build_read_child_runner", forbidden_gpt)
    monkeypatch.setattr(launch, "build_claude_read_child_runner", lambda *_args, **_kwargs: sentinel)
    monkeypatch.setattr(launch, "PraxisRunJournal", lambda _path: SimpleNamespace(record_launch=lambda *_args: None))
    env = {}
    settings = SimpleNamespace(family="claude", dispatch_model="claude:sonnet")
    app = {launch.APP_PRAXIS_RUN_CHANNELS: Registry()}
    _, registry = launch.prepare_launch(app, settings, tmp_path, "run-one", "request-one", env, 8899)
    assert registry is app[launch.APP_PRAXIS_RUN_CHANNELS]
    assert captured["run_id"] == "run-one"
    assert [event async for event in captured["runner"]("child", "review", "Review", "Inspect")] == [{"type": "done"}]
    assert env["THOMAS_RUN_CHANNEL_TOKEN"] == "run-secret"
