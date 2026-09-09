from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.workspace_specialist_test_support import Dispatcher, GuardedRunner, Tools, operator
from thomas.preferences.store import PreferencesStore


@pytest.mark.asyncio
async def test_guarded_preference_mutation_uses_live_structured_store(tmp_path: Path) -> None:
    dispatcher = Dispatcher()
    store = PreferencesStore(db_path=str(tmp_path / "prefs.db"))
    guard = GuardedRunner()
    receipt = await operator(
        "settings", dispatcher, preferences_store=store, guarded_runner=guard
    ).execute({"action": "preferences.set", "key": "ui_density", "value": "dense"})
    assert receipt["ok"] is True
    assert receipt["approval"] == "policy_checked"
    assert receipt["evidence"]["before"]["value"] == "comfortable"
    assert receipt["evidence"]["after"]["value"] == "dense"
    assert receipt["evidence"]["after"]["path"] == "advanced.interface.ui_density"
    assert guard.calls[0]["tool_call"]["name"] == "db.command"
    persisted = store.get(user_id="owner-test")
    assert persisted.advanced.interface.ui_density == "dense"
    assert persisted.thomads == {}


@pytest.mark.asyncio
async def test_canvas_spec_save_is_atomic_and_read_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server.routes import canvas_studio_routes

    monkeypatch.setattr(canvas_studio_routes, "_default_repo_root", lambda: tmp_path)
    receipt = await operator(
        "app_builder", Dispatcher(), guarded_runner=GuardedRunner()
    ).execute(
        {
            "action": "canvas.spec.save",
            "target_id": "owner-dashboard",
            "payload": {"root": {"type": "frame", "children": []}},
        }
    )
    saved = tmp_path / ".thomas" / "canvas" / "owner-dashboard.json"
    assert receipt["ok"] is True
    assert saved.is_file()
    assert '"id": "owner-dashboard"' in saved.read_text(encoding="utf-8")
    assert receipt["evidence"]["after"]["root"]["type"] == "frame"


@pytest.mark.asyncio
async def test_canvas_rejects_invalid_spec_id_before_any_file_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server.routes import canvas_studio_routes

    monkeypatch.setattr(canvas_studio_routes, "_default_repo_root", lambda: tmp_path)
    receipt = await operator(
        "app_builder", Dispatcher(), guarded_runner=GuardedRunner()
    ).execute(
        {
            "action": "canvas.spec.save",
            "target_id": "../../orphan",
            "payload": {"root": {"type": "frame", "children": []}},
        }
    )
    assert receipt["ok"] is False
    assert receipt["state"] == "rejected"
    assert not (tmp_path / ".thomas" / "canvas").exists()


@pytest.mark.asyncio
async def test_library_project_move_persists_and_reads_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from thomas.server.routes import local_projects_helpers_aiohttp as helpers

    projects = [{"id": "project-1", "name": "One", "board_position": {"x": 1, "y": 2}}]
    writes: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(helpers, "_refresh_projects", lambda _app: projects)
    monkeypatch.setattr(
        helpers,
        "_find_project",
        lambda rows, project_id: (0, rows[0])
        if project_id == "project-1"
        else (_ for _ in ()).throw(KeyError()),
    )
    monkeypatch.setattr(helpers, "_utc_now_iso", lambda: "2026-07-21T00:00:00Z")
    monkeypatch.setattr(
        helpers, "_write_registry", lambda _app, rows: writes.append([dict(row) for row in rows])
    )
    receipt = await operator(
        "my_stuff", Dispatcher(), guarded_runner=GuardedRunner()
    ).execute(
        {"action": "library.project.move", "target_id": "project-1", "payload": {"x": 900, "y": 240}}
    )
    assert receipt["ok"] is True
    assert writes[-1][0]["board_position"] == {"x": 900, "y": 240}
    assert receipt["evidence"]["after"] == {"x": 900, "y": 240}


@pytest.mark.asyncio
async def test_library_missing_project_returns_failed_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiohttp import web

    from thomas.server.routes import local_projects_helpers_aiohttp as helpers

    monkeypatch.setattr(helpers, "_refresh_projects", lambda _app: [])
    monkeypatch.setattr(helpers, "_find_project", lambda _rows, _id: (_ for _ in ()).throw(web.HTTPNotFound()))
    receipt = await operator(
        "my_stuff", Dispatcher(), guarded_runner=GuardedRunner()
    ).execute(
        {"action": "library.project.move", "target_id": "missing", "payload": {"x": 1, "y": 2}}
    )
    assert receipt["ok"] is False
    assert "not found" in receipt["error"].lower()


@pytest.mark.asyncio
async def test_active_tool_policy_denies_file_and_channel_mutations(tmp_path: Path) -> None:
    from thomas.server.routes import canvas_studio_routes

    original_root = canvas_studio_routes._default_repo_root
    canvas_studio_routes._default_repo_root = lambda: tmp_path
    denied_files = SimpleNamespace(allow_file_write=False, allow_channels=True)
    try:
        canvas = await operator(
            "app_builder",
            Dispatcher(),
            guarded_runner=GuardedRunner(),
            tool_policy=denied_files,
        ).execute(
            {
                "action": "canvas.spec.save",
                "target_id": "blocked",
                "payload": {"root": {"type": "frame", "children": []}},
            }
        )
    finally:
        canvas_studio_routes._default_repo_root = original_root
    denied_channels = SimpleNamespace(allow_file_write=True, allow_channels=False)
    channels = await operator(
        "channels", Dispatcher(), guarded_runner=GuardedRunner(), tool_policy=denied_channels
    ).execute({"action": "channels.discord.set_enabled", "value": True})
    assert canvas["ok"] is False and canvas["approval"] == "policy_denied"
    assert channels["ok"] is False and channels["approval"] == "policy_denied"
    assert not (tmp_path / ".thomas" / "canvas").exists()


@pytest.mark.asyncio
async def test_channels_enabled_state_is_persisted_and_read_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from thomas.integrations import discord_bridge_runtime

    class _Discord:
        enabled = False

        def __init__(self, _config):
            pass

        def status(self):
            return {"bridge": {"enabled": type(self).enabled}}

        def set_enabled(self, enabled: bool):
            type(self).enabled = bool(enabled)
            return {"enabled": type(self).enabled}

    monkeypatch.setattr(discord_bridge_runtime, "DiscordBridgeRuntime", _Discord)
    receipt = await operator(
        "channels", Dispatcher(), guarded_runner=GuardedRunner()
    ).execute({"action": "channels.discord.set_enabled", "value": True})
    assert receipt["ok"] is True
    assert receipt["evidence"]["before"]["bridge"]["enabled"] is False
    assert receipt["evidence"]["after"]["bridge"]["enabled"] is True


@pytest.mark.asyncio
async def test_marketplace_enablement_uses_installed_registry_and_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from thomas.server import desktop_plugins

    installed = {"plugin_id": "verified-app", "enabled": False}

    def _set(_config, plugin_id: str, enabled: bool):
        assert plugin_id == installed["plugin_id"]
        installed["enabled"] = bool(enabled)
        return dict(installed)

    monkeypatch.setattr(desktop_plugins, "set_installed_plugin_enabled", _set)
    monkeypatch.setattr(
        desktop_plugins,
        "list_installed_plugins",
        lambda _config, include_disabled=True: [dict(installed)],
    )
    receipt = await operator(
        "marketplace", Dispatcher(), guarded_runner=GuardedRunner()
    ).execute(
        {"action": "marketplace.plugin.set_enabled", "target_id": "verified-app", "value": True}
    )
    assert receipt["ok"] is True
    assert receipt["evidence"]["before"]["enabled"] is False
    assert receipt["evidence"]["after"]["enabled"] is True


@pytest.mark.asyncio
async def test_paper_trade_proposal_persists_without_submit_and_is_read_back() -> None:
    tools = Tools()
    receipt = await operator(
        "paper_trading",
        Dispatcher(),
        tools=tools,
        guarded_runner=GuardedRunner(),
    ).execute(
        {
            "action": "paper_trading.propose",
            "payload": {
                "symbol": "AAPL",
                "side": "buy",
                "thesis": "Test thesis",
                "invalidation": "Test invalidation",
                "notional": 100,
            },
        }
    )
    assert receipt["ok"] is True
    assert receipt["evidence"]["after"]["status"] == "pending_approval"
    names = [name for name, _args in tools.calls]
    assert names == ["paper_trading.propose", "paper_trading.list_proposals"]
    assert "paper_trading.submit" not in names


@pytest.mark.asyncio
async def test_virtual_office_persists_live_follow_state_without_mission_dispatch(tmp_path: Path) -> None:
    from thomas.server.office_state import OfficeStateStore

    job = SimpleNamespace(
        id="job-1",
        name="Office job",
        kind="workflow_task",
        status="waiting",
        next_run_at=None,
        updated_at=None,
    )

    class _MissionStore:
        def list_jobs(self, **_kwargs):
            return [job]

        def get_job(self, job_id: str):
            assert job_id == job.id
            return job

        def set_job_status(self, job_id: str, status: str, **_kwargs):
            assert job_id == job.id
            job.status = status

    store = OfficeStateStore(tmp_path)
    resident = operator(
        "office",
        Dispatcher(),
        guarded_runner=GuardedRunner(),
        app={"autonomy_store": _MissionStore()},
        office_store=store,
    )
    receipt = await resident.execute(
        {"action": "office.view.set_follow_agent", "target_id": "agent-4"}
    )
    rejected_dispatch = await resident.execute(
        {"action": "mission.job.run_now", "target_id": "job-1"}
    )
    assert receipt["ok"] is True
    assert receipt["evidence"]["before"]["follow_agent_id"] == ""
    assert receipt["evidence"]["after"]["follow_agent_id"] == "agent-4"
    assert OfficeStateStore(tmp_path).get(user_id="owner-test")["follow_agent_id"] == "agent-4"
    assert rejected_dispatch["ok"] is False
    assert job.status == "waiting"
