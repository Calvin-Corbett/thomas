"""Bounded read and mutation implementations for workspace residents."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from thomas.server.workspace_specialist_policy import WORKSPACE_LABELS
from thomas.server.workspace_specialist_readback import WorkspaceReadbackMixin


class WorkspaceActionExecutorMixin(WorkspaceReadbackMixin):
    """Implement only the operations explicitly exposed by workspace policy."""

    workspace_key: str
    context_id: str
    policy: dict[str, Any]

    async def _perform_read(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if action == "workspace.inspect":
            snapshot: dict[str, Any] = {
                "workspace": self.workspace_key,
                "label": WORKSPACE_LABELS[self.workspace_key],
                "context_id": self.context_id,
                "available_actions": sorted(self.policy),
            }
            await self._enrich_snapshot(snapshot)
            return {"ok": True, "data": snapshot, "error": ""}
        if action == "mission.jobs.list":
            jobs = self._list_mission_jobs(limit=100)
            return {"ok": True, "data": {"jobs": jobs, "count": len(jobs)}, "error": ""}
        if action in {"preferences.get", "preferences.list"}:
            if action == "preferences.get":
                data = self._read_structured_preference(str(arguments.get("key") or "").strip())
            else:
                data = self._list_structured_preferences(self.policy[action].preference_keys)
            return {"ok": True, "data": data, "error": ""}
        return {"ok": False, "data": None, "error": "Read action is not implemented."}

    async def _enrich_snapshot(self, snapshot: dict[str, Any]) -> None:
        if self.workspace_key in {"mission", "office"}:
            jobs = self._list_mission_jobs(limit=40)
            snapshot.update(mission_jobs=jobs, mission_job_count=len(jobs))
        elif self.workspace_key == "app_builder":
            from thomas.server.routes.canvas_studio_routes import _canvas_dir, _default_repo_root

            directory = _canvas_dir(_default_repo_root())
            snapshot["saved_spec_ids"] = sorted(path.stem for path in directory.glob("*.json"))[:100]
        elif self.workspace_key == "my_stuff":
            from thomas.server.routes.local_projects_helpers_aiohttp import _refresh_projects

            snapshot["projects"] = [
                {
                    "id": str(row.get("id") or ""),
                    "name": str(row.get("name") or ""),
                    "board_position": dict(row.get("board_position") or {}),
                }
                for row in _refresh_projects(self.app)[:100]
            ]
        elif self.workspace_key == "channels":
            from thomas.integrations.discord_bridge_runtime import DiscordBridgeRuntime

            snapshot["discord"] = await asyncio.to_thread(DiscordBridgeRuntime(self.config).status)
        elif self.workspace_key == "marketplace":
            from thomas.server.desktop_plugins import list_installed_plugins

            snapshot["installed_plugins"] = list_installed_plugins(
                self.config, include_disabled=True
            )[:100]
        elif self.workspace_key == "paper_trading":
            result = await self._execute_registry_tool("paper_trading.list_proposals", {})
            snapshot["proposals"] = result.get("data") if result.get("ok") else []
        if self.workspace_key == "office":
            snapshot["office_state"] = self._office_state_store().get(user_id=self.user_id)

    async def _perform_mutation(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if action == "preferences.set":
            data = self._patch_structured_preference(
                str(arguments.get("key") or "").strip(), arguments.get("value")
            )
            return {"ok": True, "data": data, "error": ""}
        if action == "canvas.spec.save":
            from thomas.server.routes.canvas_studio_routes import _default_repo_root, _write_spec

            spec_id = str(arguments.get("target_id") or "").strip()
            spec = dict(arguments.get("payload") or {})
            spec["id"] = spec_id
            saved_id = _write_spec(_default_repo_root(), spec)
            return {"ok": True, "data": {"id": saved_id}, "error": ""}
        if action == "library.project.move":
            try:
                return self._move_library_project(arguments)
            except (KeyError, web.HTTPException):
                return {"ok": False, "data": None, "error": "Library project was not found."}
        if action == "channels.discord.set_enabled":
            from thomas.integrations.discord_bridge_runtime import DiscordBridgeRuntime

            runtime = DiscordBridgeRuntime(self.config)
            state = await asyncio.to_thread(runtime.set_enabled, bool(arguments.get("value")))
            return {"ok": True, "data": {"state": state}, "error": ""}
        if action == "marketplace.plugin.set_enabled":
            from thomas.server.desktop_plugins import set_installed_plugin_enabled

            plugin_id = str(arguments.get("target_id") or "").strip()
            plugin = set_installed_plugin_enabled(
                self.config, plugin_id, bool(arguments.get("value"))
            )
            return {"ok": True, "data": {"plugin": plugin}, "error": ""}
        if action == "paper_trading.propose":
            return await self._execute_registry_tool(
                "paper_trading.propose", dict(arguments.get("payload") or {})
            )
        if action == "office.view.set_follow_agent":
            state = self._office_state_store().set_follow_agent(
                arguments.get("target_id"), user_id=self.user_id
            )
            return {"ok": True, "data": state, "error": ""}
        if action.startswith("mission.job."):
            return self._mutate_mission_job(action, arguments)
        return {"ok": False, "data": None, "error": "Mutation action is not implemented."}

    def _office_state_store(self) -> Any:
        if self.office_store is None:
            from thomas.server.office_state import OfficeStateStore

            root = getattr(getattr(self.config, "memory", None), "root_path", ".")
            self.office_store = OfficeStateStore(root)
        return self.office_store

    def _move_library_project(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from thomas.server.routes.local_projects_helpers_aiohttp import (
            _find_project,
            _refresh_projects,
            _utc_now_iso,
            _write_registry,
        )

        projects = _refresh_projects(self.app)
        project_id = str(arguments.get("target_id") or "").strip()
        index, project = _find_project(projects, project_id)
        payload = arguments.get("payload") or {}
        position = {"x": int(payload.get("x")), "y": int(payload.get("y"))}
        project["board_position"] = position
        project["updated_at"] = _utc_now_iso()
        projects[index] = project
        _write_registry(self.app, projects)
        return {
            "ok": True,
            "data": {"project_id": project_id, "board_position": position},
            "error": "",
        }

    def _mutate_mission_job(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        store = self.app.get("autonomy_store")
        if store is None:
            return {"ok": False, "data": None, "error": "Mission autonomy store is unavailable."}
        job_id = str(arguments.get("target_id") or "").strip()
        if action == "mission.job.cancel":
            store.cancel_job(job_id, actor="workspace_resident")
        elif action == "mission.job.run_now":
            store.set_job_status(
                job_id, "queued", next_run_at=datetime.now(timezone.utc), lock_clear=True
            )
        elif action == "mission.job.requeue":
            store.set_job_status(
                job_id,
                "queued",
                error=None,
                result=None,
                attempts=0,
                next_run_at=datetime.now(timezone.utc),
                lock_clear=True,
            )
        else:
            return {"ok": False, "data": None, "error": "Mission action is not implemented."}
        engine = self.app.get("autonomy_engine")
        wake = getattr(engine, "wake_up", None)
        if callable(wake):
            wake()
        return {"ok": True, "data": {"job_id": job_id, "action": action}, "error": ""}


__all__ = ["WorkspaceActionExecutorMixin"]
