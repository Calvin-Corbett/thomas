"""A server restart reattaches durable child work without changing its model."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.praxis import launch, startup
from thomas.server.praxis.recovery import PraxisRunJournal
from thomas.server.routes.evolve_agent_watch_routes import build_evolve_agent_watch_handlers
from thomas.server.routes.praxis_run_routes import register_praxis_run_routes


@pytest.mark.asyncio
async def test_startup_resumes_exact_choices_and_waits_for_quota_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "user_praxis_root", lambda: tmp_path)
    monkeypatch.setattr(startup, "user_praxis_root", lambda: tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    begun = asyncio.Event()
    count = 0

    def original_factory(_app, _project, _settings, _run_id):
        async def child(_id, _kind, _title, _brief, _choice=None):
            nonlocal count
            count += 1
            if count == 2:
                begun.set()
            await asyncio.Event().wait()
            yield {"type": "done"}

        return child

    monkeypatch.setattr(launch, "build_dispatching_child_runner", original_factory)
    first_app = web.Application()
    first_registry = register_praxis_run_routes(first_app)
    settings = SimpleNamespace(
        family="gpt", model_id="gpt-5.6-sol", reviewer_model="gpt-5.6-luna", dispatch_model="codex:gpt"
    )
    launch.prepare_launch(first_app, settings, project, "restart", "request", {}, 8899, conversation_id="conv-1")
    original = first_registry._runs["restart"]
    handles = await original.spawn(
        [
            {
                "kind": "review",
                "title": "Claude",
                "brief": "Inspect A",
                "model_choice": {"profile": "anthropic", "model_id": "claude-sonnet-4-5"},
            },
            {
                "kind": "verify",
                "title": "GPT",
                "brief": "Inspect B",
                "model_choice": {"profile": "openai_codex", "model_id": "gpt-5.6-luna"},
            },
        ]
    )
    await asyncio.wait_for(begun.wait(), 2)
    deadline = time.time() + 0.7
    parked_id = handles[1]["agent_id"]
    original._children[parked_id]["state"] = "quota_wait"
    original._children[parked_id]["resume_at"] = deadline
    original._checkpoint(parked_id)
    await original.suspend()

    observed = []

    def resumed_factory(_app, restored_project, restored_settings, run_id):
        assert restored_project == project.resolve()
        assert restored_settings.family == "gpt"
        assert restored_settings.reviewer_model == "gpt-5.6-luna"
        assert run_id == "restart"

        async def child(child_id, _kind, _title, _brief, choice=None):
            observed.append((child_id, choice, time.time()))
            yield {"type": "done"}

        return child

    monkeypatch.setattr(launch, "build_dispatching_child_runner", resumed_factory)
    second_app = web.Application()
    second_registry = register_praxis_run_routes(second_app)
    watch = build_evolve_agent_watch_handlers(
        second_app,
        require_api_access=lambda _request: None,
        catalog_root=lambda: tmp_path,
        running=lambda: False,
    )
    second_app.router.add_get("/code/status", watch["status"])
    async with TestClient(TestServer(second_app)) as client:
        assert second_app[startup.APP_PRAXIS_RECOVERY_REPORT]["resumed"] == [
            {"run_id": "restart", "conversation_id": "conv-1", "agents": 2}
        ]
        recovered = second_registry._runs["restart"]
        assert recovered.token != original.token
        assert not recovered.authorized(original.token)
        card = await (await client.get("/code/status?conversation_id=conv-1")).json()
        assert card["running"] is False
        assert card["run_id"] == "restart"
        assert card["praxis_recovered"]["lead_attached"] is False
        assert len(card["praxis_recovered"]["agents"]) == 2
        await recovered._tasks[handles[0]["agent_id"]]
        assert observed[0][1] == {"profile": "anthropic", "model_id": "claude-sonnet-4-5"}
        assert len(observed) == 1
        assert recovered.status([parked_id])["agents"][0]["state"] == "quota_wait"
        await recovered._tasks[parked_id]
        assert observed[1][1] == {"profile": "openai_codex", "model_id": "gpt-5.6-luna"}
        assert observed[1][2] >= deadline - 0.02
        assert all(row["state"] == "completed" for row in recovered.status()["agents"])


@pytest.mark.asyncio
async def test_old_journal_without_runner_identity_is_skipped_truthfully(tmp_path, monkeypatch):
    monkeypatch.setattr(startup, "user_praxis_root", lambda: tmp_path)
    journal = PraxisRunJournal(tmp_path / "praxis" / "runs.sqlite3")
    journal.admit(
        "old",
        "Inspect",
        [
            {
                "agent_id": "child",
                "plan_id": "unit",
                "kind": "review",
                "title": "Review",
                "brief": "Inspect",
                "dependencies": [],
            }
        ],
    )
    app = web.Application()
    registry = register_praxis_run_routes(app)
    async with TestServer(app):
        assert "old" not in registry._runs
        assert app[startup.APP_PRAXIS_RECOVERY_REPORT]["skipped"] == [
            {"run_id": "old", "reason": "missing_launch_context"}
        ]


@pytest.mark.asyncio
async def test_restart_keeps_external_builder_interrupted_without_running_read_child(tmp_path, monkeypatch):
    monkeypatch.setattr(startup, "user_praxis_root", lambda: tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    journal = PraxisRunJournal(tmp_path / "praxis" / "runs.sqlite3")
    journal.record_launch(
        "external-restart",
        {
            "project_root": str(project.resolve()),
            "family": "gpt",
            "model_id": "gpt-5.6-sol",
            "reviewer_model": "",
            "dispatch_model": "codex:gpt",
            "praxis_reviewer_profile": "",
            "praxis_reviewer_model": "",
            "conversation_id": "conv-external",
        },
    )
    journal.admit(
        "external-restart",
        "Build a module",
        [
            {
                "agent_id": "writer",
                "plan_id": "unit",
                "kind": "write",
                "title": "Build module",
                "brief": "Write code",
                "dependencies": [],
                "execution_origin": "external_builder",
                "path": "src/module.py",
                "model_choice": {"profile": "claude_cli", "model_id": "sonnet"},
            }
        ],
    )

    def factory(_app, _project, _settings, _run_id):
        async def must_not_run(*_args, **_kwargs):
            raise AssertionError("external Build writer must not be relaunched as a read child")
            yield  # pragma: no cover

        return must_not_run

    monkeypatch.setattr(launch, "build_dispatching_child_runner", factory)
    app = web.Application()
    registry = register_praxis_run_routes(app)
    watch = build_evolve_agent_watch_handlers(
        app,
        require_api_access=lambda _request: None,
        catalog_root=lambda: tmp_path,
        running=lambda: False,
    )
    app.router.add_get("/code/status", watch["status"])
    async with TestClient(TestServer(app)) as client:
        recovered = registry._runs["external-restart"]
        await asyncio.gather(*recovered._tasks.values())
        response = await client.get("/code/status?conversation_id=conv-external")
        card = await response.json()
        assert card["running"] is False
        assert card["praxis_recovered"]["lead_attached"] is False
        assert card["praxis_recovered"]["agents"][0]["state"] == "interrupted"
        assert card["praxis_recovered"]["agents"][0]["execution_origin"] == "external_builder"
        assert journal.load("external-restart")["children"][0]["path"] == "src/module.py"


def test_fresh_python_process_resumes_saved_child(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    journal = PraxisRunJournal(tmp_path / "praxis" / "runs.sqlite3")
    journal.record_launch(
        "cross-process",
        {
            "project_root": str(project.resolve()),
            "family": "gpt",
            "model_id": "gpt-5.6-sol",
            "reviewer_model": "gpt-5.6-luna",
            "dispatch_model": "codex:gpt",
            "praxis_reviewer_profile": "",
            "praxis_reviewer_model": "",
        },
    )
    journal.admit(
        "cross-process",
        "Inspect",
        [
            {
                "agent_id": "child",
                "plan_id": "unit",
                "kind": "review",
                "title": "Review",
                "brief": "Inspect",
                "dependencies": [],
                "model_choice": {"profile": "openai_codex", "model_id": "gpt-5.6-luna"},
            }
        ],
    )
    journal.checkpoint(
        "cross-process",
        {"agent_id": "child", "state": "running", "attempts": 1, "events": []},
    )
    script = textwrap.dedent("""
        import asyncio, json, sys
        from pathlib import Path
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        from thomas.server.praxis import launch, startup
        from thomas.server.routes.praxis_run_routes import register_praxis_run_routes

        root = Path(sys.argv[1])
        startup.user_praxis_root = lambda: root
        seen = []
        def factory(_app, project, settings, run_id):
            async def child(_id, _kind, _title, _brief, choice=None):
                seen.append({'choice': choice, 'project': str(project), 'family': settings.family})
                yield {'type': 'done'}
            return child
        launch.build_dispatching_child_runner = factory

        async def main():
            app = web.Application()
            registry = register_praxis_run_routes(app)
            async with TestServer(app):
                channel = registry._runs['cross-process']
                await channel._tasks['child']
                print(json.dumps({'recovery': app[startup.APP_PRAXIS_RECOVERY_REPORT],
                                  'state': channel.status()['agents'][0]['state'], 'seen': seen}))
        asyncio.run(main())
    """)
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["recovery"]["resumed"] == [{"run_id": "cross-process", "conversation_id": "", "agents": 1}]
    assert report["state"] == "completed"
    assert report["seen"] == [
        {
            "choice": {"profile": "openai_codex", "model_id": "gpt-5.6-luna"},
            "project": str(project.resolve()),
            "family": "gpt",
        }
    ]
