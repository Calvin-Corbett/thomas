"""Build's Claude team can delete a file, and only a file inside its own project folder.

On 2026-09-25 a Thomas project could only empty 19 dead modules: its Claude lead had no shell and no delete.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sqlite3
import subprocess
import sys

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.forge.anvil import run_channel_mcp
from thomas.forge.anvil.dispatch_claude_cli import dispatch_via_claude_cli
from thomas.forge.anvil.run_channel_client import RunChannelClient
from thomas.forge.anvil.run_channel_mcp import DELETE_TOOL_NAME, MCP_TOOL_NAMES, handle, server_config
from thomas.server.praxis import startup
from thomas.server.praxis.recovery import PraxisRunJournal, recover_channel
from thomas.server.praxis.run_channel import MAX_DELETE_PATHS, RunChannel
from thomas.server.routes.praxis_run_routes import register_praxis_run_routes


async def _never_runs(*_args):
    raise AssertionError("a delete receipt must never start a model child")
    yield


def _project(tmp_path):
    project = tmp_path / "project"
    for name, text in (("junk/dead_module.py", ""), ("keep.py", "print('kept')\n"), (".git/config", "[core]\n")):
        (project / name).parent.mkdir(parents=True, exist_ok=True)
        (project / name).write_text(text, encoding="utf-8")
    (project / "pkg").mkdir()
    (tmp_path / "outside.txt").write_text("not the project's\n", encoding="utf-8")
    return project


def _results(report):
    return {row["path"]: row["result"] for row in report["results"]}


def _channel_env(monkeypatch):
    monkeypatch.setenv("THOMAS_RUN_CHANNEL_URL", "http://127.0.0.1:8899")
    monkeypatch.setenv("THOMAS_CODE_RUN_ID", "run-one")
    monkeypatch.setenv("THOMAS_RUN_CHANNEL_TOKEN", "secret-one")


def _rpc(method, request_id=1, **params):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, **({"params": params} if params else {})}


# dispatch_via_claude_cli with no repository lookup, no verifier and no real claude binary.
_OFFLINE = {"definition": "a test project", "claude_bin": "claude", "verify": False, "allow_without_history": True}


def _never_starts_claude(*_args):
    raise AssertionError("a dry run must never start claude")


@pytest.mark.asyncio
async def test_each_refusal_names_why_and_deletes_nothing(tmp_path):
    project = _project(tmp_path)
    channel = RunChannel("run", _never_runs, project_root=project)
    asked = {
        str(project / "keep.py"): "absolute path",
        "/keep.py": "absolute path",
        "../outside.txt": "outside this project",
        "junk/../../outside.txt": "outside this project",
        ".": "project's folder itself",
        "junk/..": "project's folder itself",
        ".git/config": ".git",
        ".GIT/config": ".git",
        ".git./config": ".git",
        "junk/../.git/config": ".git",
        "pkg": "folder",
        "missing.py": "no such file",
        "keep.py:hidden": "':'",
        "": "non-empty text",
    }
    report = await channel.delete_files([*asked, 7], why="clean junk")
    results = _results(report)
    for path, fragment in asked.items():
        assert results[path].startswith("refused: ") and fragment in results[path], (path, results[path])
    assert results["7"].startswith("refused: ")
    assert report["deleted"] == 0 and report["refused"] == len(asked) + 1
    assert (project / "keep.py").is_file() and (project / ".git" / "config").is_file()
    assert (project / "pkg").is_dir() and (tmp_path / "outside.txt").is_file()


@pytest.mark.asyncio
async def test_a_symlink_is_refused_and_its_target_survives(tmp_path):
    project = _project(tmp_path)
    try:
        os.symlink(project / "keep.py", project / "link.py")
    except (OSError, NotImplementedError):
        pytest.skip("this machine cannot create a symlink without elevation")
    channel = RunChannel("run", _never_runs, project_root=project)
    results = _results(await channel.delete_files(["link.py"], why="clean junk"))
    assert "symlink or junction" in results["link.py"]
    assert (project / "link.py").is_symlink() and (project / "keep.py").is_file()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows folder link")
async def test_a_junction_and_a_path_through_one_are_refused(tmp_path):
    import _winapi

    project = _project(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "precious.txt").write_text("keep me\n", encoding="utf-8")
    _winapi.CreateJunction(str(elsewhere), str(project / "venv_link"))
    _winapi.CreateJunction(str(project / "junk"), str(project / "inner_link"))
    channel = RunChannel("run", _never_runs, project_root=project)
    paths = ["venv_link", "venv_link/precious.txt", "inner_link/dead_module.py"]
    results = _results(await channel.delete_files(paths, why="clean junk"))
    assert all("symlink or junction" in result for result in results.values()), results
    assert (elsewhere / "precious.txt").is_file() and (project / "junk" / "dead_module.py").is_file()


@pytest.mark.asyncio
async def test_a_file_in_the_project_is_really_deleted_and_the_run_history_shows_it(tmp_path):
    project = _project(tmp_path)
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    channel = RunChannel("run", _never_runs, journal=journal, project_root=project)
    report = await channel.delete_files(["junk/dead_module.py"], why="no caller anywhere")
    assert _results(report) == {"junk/dead_module.py": "deleted"}
    assert report["deleted"] == 1 and report["refused"] == 0
    assert not (project / "junk" / "dead_module.py").exists()
    assert (project / "junk").is_dir()  # only the file goes, never its folder
    row = channel.status([report["agent_id"]])["agents"][0]
    assert row["kind"] == "delete" and row["state"] == "completed"
    results = [{"path": "junk/dead_module.py", "result": "deleted"}]
    assert row["events"] == [{"type": "deleted", "why": "no caller anywhere", "results": results}]
    saved = journal.load("run")["children"]
    assert [child["state"] for child in saved] == ["completed"]
    assert saved[0]["events"][0]["results"] == results
    assert journal.interrupted_runs() == []
    restored = recover_channel(journal, "run", _never_runs)
    await asyncio.gather(*restored._tasks.values())
    assert restored.status()["agents"][0]["events"][0]["why"] == "no caller anywhere"
    await restored.close()
    await channel.close()

    class LockedJournal:  # a journal that cannot write never costs the lead what was already deleted
        def admit(self, *_args):
            raise sqlite3.OperationalError("database is locked")

    locked = RunChannel("run", _never_runs, journal=LockedJournal(), project_root=project)
    report = await locked.delete_files(["keep.py"], why="no caller anywhere")
    assert _results(report) == {"keep.py": "deleted"} and not (project / "keep.py").exists()
    assert locked.status([report["agent_id"]])["agents"][0]["state"] == "completed"


@pytest.mark.asyncio
async def test_a_mixed_list_deletes_the_good_paths_and_refuses_the_rest_without_raising(tmp_path):
    project = _project(tmp_path)
    (project / "junk" / "also_dead.py").write_text("x = 1\n", encoding="utf-8")
    channel = RunChannel("run", _never_runs, project_root=project)
    paths = ["junk/dead_module.py", "../outside.txt", ".git/config", "junk/also_dead.py", "junk/dead_module.py"]
    report = await channel.delete_files(paths, why="clean junk")
    assert [row["result"] == "deleted" for row in report["results"]] == [True, False, False, True, False]
    assert report["results"][-1]["result"] == "refused: no such file"
    assert report["deleted"] == 2 and report["refused"] == 3
    assert not (project / "junk" / "dead_module.py").exists() and not (project / "junk" / "also_dead.py").exists()
    assert (tmp_path / "outside.txt").is_file() and (project / ".git" / "config").is_file()


@pytest.mark.asyncio
async def test_the_whole_call_is_refused_without_a_project_folder_or_after_the_run_ends(tmp_path):
    project = _project(tmp_path)
    with pytest.raises(ValueError, match="no project folder"):
        await RunChannel("run", _never_runs).delete_files(["keep.py"], why="clean junk")
    ended = RunChannel("run", _never_runs, project_root=project)
    await ended.close()
    with pytest.raises(ValueError, match="ended"):
        await ended.delete_files(["keep.py"], why="clean junk")
    live = RunChannel("run", _never_runs, project_root=project)
    for paths, why, refusal in (
        (["keep.py"] * (MAX_DELETE_PATHS + 1), "clean junk", f"at most {MAX_DELETE_PATHS}"),
        ([], "clean junk", "nonempty list"),
        ("keep.py", "clean junk", "nonempty list"),
        (["keep.py"], "  ", "say why"),
    ):
        with pytest.raises(ValueError, match=refusal):
            await live.delete_files(paths, why=why)
    assert (project / "keep.py").is_file()
    assert live.status()["agents"] == []


async def _serve(tmp_path, monkeypatch, *middlewares):
    monkeypatch.setattr(startup, "user_praxis_root", lambda: tmp_path)
    project = _project(tmp_path)
    app = web.Application(middlewares=list(middlewares))
    registry = register_praxis_run_routes(app)
    channel = registry.open("run", _never_runs, project_root=project)
    return project, registry, channel, TestClient(TestServer(app, host="127.0.0.1"))


@pytest.mark.asyncio
async def test_the_route_deletes_for_the_run_token_and_refuses_a_wrong_one(tmp_path, monkeypatch):
    project, registry, channel, served = await _serve(tmp_path, monkeypatch)
    async with served as http:
        body = {"paths": ["keep.py"], "why": "clean junk"}
        wrong = await http.post("/api/praxis/run/run/delete", json=body, headers={"X-Thomas-Run-Token": "not-it"})
        assert wrong.status == 404 and (project / "keep.py").is_file()
        client = RunChannelClient(base_url=str(http.make_url("/")), run_id="run", token=channel.token)
        report = await client.call("delete", {"paths": ["junk/dead_module.py", ".git/config"], "why": "clean junk"})
        results = _results(report)
        assert results["junk/dead_module.py"] == "deleted" and results[".git/config"].startswith("refused: ")
        assert not (project / "junk" / "dead_module.py").exists()
        with pytest.raises(RuntimeError, match="say why"):
            await client.call("delete", {"paths": ["keep.py"]})
    await registry.close("run")


@pytest.mark.asyncio
async def test_the_route_refuses_a_caller_from_another_machine_even_with_the_token(tmp_path, monkeypatch):
    @web.middleware
    async def from_another_machine(request, handler):
        return await handler(request.clone(remote="203.0.113.9"))

    project, registry, channel, served = await _serve(tmp_path, monkeypatch, from_another_machine)
    async with served as http:
        body, token = {"paths": ["keep.py"], "why": "clean junk"}, {"X-Thomas-Run-Token": channel.token}
        response = await http.post("/api/praxis/run/run/delete", json=body, headers=token)
        assert response.status == 403
    assert (project / "keep.py").is_file()
    await registry.close("run")


@pytest.mark.asyncio
async def test_the_mcp_tool_is_offered_only_to_an_editing_run_and_maps_to_the_delete_action():
    calls = []

    class Client:
        async def call(self, action, payload):
            calls.append((action, payload))
            return {"ok": True, "results": [{"path": "junk/a.py", "result": "deleted"}]}

    listed = await handle(_rpc("tools/list"), Client(), offer_delete=True)
    tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
    assert set(tools) == {"spawn_agents", "wait_agents", "agent_status", "stop_agent", "delete_files"}
    delete, schema = tools["delete_files"], tools["delete_files"]["inputSchema"]
    assert "project folder" in delete["description"] and "nothing else" in delete["description"]
    assert schema["required"] == ["paths", "why"] and schema["properties"]["paths"]["type"] == "array"

    arguments = {"paths": ["junk/a.py"], "why": "no caller"}
    called = await handle(_rpc("tools/call", 2, name="delete_files", arguments=arguments), Client(), offer_delete=True)
    assert not called["result"]["isError"]
    assert calls == [("delete", {"paths": ["junk/a.py"], "why": "no caller"})]

    read_only = await handle(_rpc("tools/list", 3), Client())
    assert "delete_files" not in {tool["name"] for tool in read_only["result"]["tools"]}
    refused = await handle(_rpc("tools/call", 4, name="delete_files", arguments=arguments), Client())
    assert refused["error"]["code"] == -32601 and len(calls) == 1


@pytest.mark.parametrize(
    "autonomy, access, may_delete",
    [(3, "project", True), (5, "workspace", True), (3, "read_only", False), (2, "project", False)],
)
def test_allowed_tools_and_the_bridge_offer_delete_only_to_a_run_that_may_edit(
    monkeypatch, capsys, tmp_path, autonomy, access, may_delete
):
    _channel_env(monkeypatch)
    seen = {}

    def runner(cmd, _cwd, _timeout):
        seen["cmd"] = cmd
        seen["config"] = json.loads(open(cmd[cmd.index("--mcp-config") + 1], encoding="utf-8").read())
        return 1, ""

    dispatch_via_claude_cli(
        "Clean", cwd=tmp_path, dry_run=False, runner=runner, **_OFFLINE, autonomy_level=autonomy, file_access=access
    )
    cmd = seen["cmd"]
    allowed = cmd[cmd.index("--allowedTools") + 1 : cmd.index("--disallowedTools")]
    assert set(MCP_TOOL_NAMES).issubset(allowed)  # the four channel tools are unchanged
    assert DELETE_TOOL_NAME == "mcp__thomas_praxis__delete_files" and DELETE_TOOL_NAME not in MCP_TOOL_NAMES
    assert (DELETE_TOOL_NAME in allowed) is may_delete
    assert (DELETE_TOOL_NAME in cmd) is may_delete  # a read-only run never sees the name at all
    args = seen["config"]["mcpServers"]["thomas_praxis"]["args"]
    assert args == server_config("python", offer_delete=may_delete)["mcpServers"]["thomas_praxis"]["args"]
    # The bridge process started from exactly that config lists delete_files exactly when the run may edit.
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_rpc("tools/list"))))
    assert run_channel_mcp.main(args[3:]) == 0
    names = {tool["name"] for tool in json.loads(capsys.readouterr().out)["result"]["tools"]}
    assert ("delete_files" in names) is may_delete
    # The same run asked as a dry run never starts claude, so it is never offered anything.
    dry = dispatch_via_claude_cli("Clean", cwd=tmp_path, dry_run=True, runner=_never_starts_claude, **_OFFLINE)
    assert not dry.ok and dry.reason.startswith("dry-run")


def test_the_bridge_runs_the_thomas_that_started_it_not_the_projects_copy(tmp_path):
    # A Thomas project's folder is a copy of Thomas's source. Started with plain `-m` in that folder, the bridge
    # imported the copy's own, older run_channel_mcp: on 2026-09-25 a team sent back with the new delete tool was
    # told "No such tool available: mcp__thomas_praxis__delete_files", because its copy predated the tool.
    stale = tmp_path / "thomas" / "forge" / "anvil"
    stale.mkdir(parents=True)
    for folder in (tmp_path / "thomas", tmp_path / "thomas" / "forge", stale):
        (folder / "__init__.py").write_text("", encoding="utf-8")
    (stale / "run_channel_mcp.py").write_text("print('STALE COPY')\n", encoding="utf-8")
    args = server_config(sys.executable)["mcpServers"]["thomas_praxis"]["args"]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("THOMAS_RUN_CHANNEL", "THOMAS_CODE_RUN_ID"))}
    done = subprocess.run(
        [sys.executable, *args], cwd=tmp_path, env=env, input="", capture_output=True, text=True, timeout=60
    )
    assert "STALE COPY" not in done.stdout
    assert "Praxis run channel is unavailable" in done.stderr  # the real bridge, refusing for want of a channel
