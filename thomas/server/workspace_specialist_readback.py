"""Post-action readback and registry adapters for workspace residents."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from thomas.server.workspace_specialist_preferences import WorkspacePreferencesMixin
from thomas.tools.base import ToolResult


class WorkspaceReadbackMixin(WorkspacePreferencesMixin):
    app: Any
    config: Any
    tools: Any

    async def _readback(
        self,
        action: str,
        arguments: dict[str, Any],
        *,
        mutation_result: dict[str, Any] | None = None,
    ) -> Any:
        if action == "preferences.set":
            return self._read_structured_preference(str(arguments.get("key") or "").strip())
        if action == "canvas.spec.save":
            from thomas.server.routes.canvas_studio_routes import _default_repo_root, _read_spec

            return _read_spec(_default_repo_root(), str(arguments.get("target_id") or "").strip())
        if action == "library.project.move":
            return self._library_position(str(arguments.get("target_id") or "").strip())
        if action == "channels.discord.set_enabled":
            from thomas.integrations.discord_bridge_runtime import DiscordBridgeRuntime

            return await asyncio.to_thread(DiscordBridgeRuntime(self.config).status)
        if action == "marketplace.plugin.set_enabled":
            from thomas.server.desktop_plugins import list_installed_plugins

            plugin_id = str(arguments.get("target_id") or "").strip()
            return next(
                (
                    row
                    for row in list_installed_plugins(self.config, include_disabled=True)
                    if str(row.get("plugin_id") or row.get("id") or "") == plugin_id
                ),
                None,
            )
        if action == "paper_trading.propose":
            proposal = (mutation_result or {}).get("data")
            proposal_id = str(proposal.get("id") or "") if isinstance(proposal, dict) else ""
            if not proposal_id:
                return None
            result = await self._execute_registry_tool("paper_trading.list_proposals", {})
            rows = result.get("data") if result.get("ok") else []
            return next(
                (row for row in rows if isinstance(row, dict) and str(row.get("id") or "") == proposal_id),
                None,
            )
        if action == "office.view.set_follow_agent":
            return self._office_state_store().get(user_id=self.user_id)
        if action.startswith("mission.job."):
            store = self.app.get("autonomy_store")
            job_id = str(arguments.get("target_id") or "").strip()
            try:
                return self._mission_job_summary(store.get_job(job_id)) if store is not None else None
            except (KeyError, RuntimeError, TypeError, ValueError):
                return None
        return None

    def _library_position(self, project_id: str) -> Any:
        from thomas.server.routes.local_projects_helpers_aiohttp import _find_project, _refresh_projects

        try:
            _, project = _find_project(_refresh_projects(self.app), project_id)
            return dict(project.get("board_position") or {})
        except (KeyError, web.HTTPException):
            return None

    @staticmethod
    def _readback_matches(action: str, arguments: dict[str, Any], after: Any) -> bool:
        if action == "preferences.set":
            return isinstance(after, dict) and after.get("value") == arguments.get("value")
        if action == "canvas.spec.save":
            return isinstance(after, dict) and str(after.get("id") or "") == str(arguments.get("target_id") or "")
        if action == "library.project.move":
            payload = arguments.get("payload") or {}
            return isinstance(after, dict) and after == {"x": payload.get("x"), "y": payload.get("y")}
        if action == "channels.discord.set_enabled":
            bridge = after.get("bridge") if isinstance(after, dict) else None
            return isinstance(bridge, dict) and bool(bridge.get("enabled")) is bool(arguments.get("value"))
        if action == "marketplace.plugin.set_enabled":
            return isinstance(after, dict) and bool(after.get("enabled")) is bool(arguments.get("value"))
        if action == "paper_trading.propose":
            return isinstance(after, dict) and str(after.get("status") or "") in {
                "pending_approval",
                "blocked_by_risk",
            }
        if action == "office.view.set_follow_agent":
            return isinstance(after, dict) and str(after.get("follow_agent_id") or "") == str(
                arguments.get("target_id") or ""
            )
        expected = {
            "mission.job.cancel": "cancelled",
            "mission.job.requeue": "queued",
            "mission.job.run_now": "queued",
        }.get(action)
        return bool(expected and isinstance(after, dict) and str(after.get("status") or "") == expected)

    def _list_mission_jobs(self, *, limit: int) -> list[dict[str, Any]]:
        store = self.app.get("autonomy_store")
        if store is None:
            return []
        try:
            jobs = list(store.list_jobs(limit=limit, offset=0) or [])
        except (KeyError, RuntimeError, TypeError, ValueError):
            return []
        return [self._mission_job_summary(job) for job in jobs]

    @staticmethod
    def _mission_job_summary(job: Any) -> dict[str, Any]:
        return {
            "id": str(getattr(job, "id", "") or ""),
            "name": str(getattr(job, "name", "") or ""),
            "kind": str(getattr(job, "kind", "") or ""),
            "status": str(getattr(job, "status", "") or ""),
            "next_run_at": str(getattr(job, "next_run_at", "") or ""),
            "updated_at": str(getattr(job, "updated_at", "") or ""),
        }

    async def _execute_registry_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.tools is None or not hasattr(self.tools, "get") or self.tools.get(name) is None:
            return {"ok": False, "data": None, "error": f"Required tool '{name}' is unavailable."}
        try:
            result = await self.tools.execute(name, args)
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            return {"ok": False, "data": None, "error": str(exc)}
        if isinstance(result, ToolResult):
            return {"ok": bool(result.ok), "data": result.data, "error": result.error}
        if isinstance(result, dict):
            return {
                "ok": bool(result.get("ok")),
                "data": result.get("data"),
                "error": str(result.get("error") or ""),
            }
        return {"ok": False, "data": None, "error": "Tool returned an unsupported result."}


__all__ = ["WorkspaceReadbackMixin"]
