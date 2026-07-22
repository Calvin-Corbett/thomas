"""Argument validation for bounded workspace resident actions."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from thomas.server.workspace_specialist_policy import WorkspaceActionSpec
from thomas.server.workspace_specialist_preferences import normalized_preference_value


def validate_workspace_action(
    action: str,
    spec: WorkspaceActionSpec,
    arguments: dict[str, Any],
) -> str:
    if action.startswith("preferences.") and action != "preferences.list":
        key = str(arguments.get("key") or "").strip()
        if not key:
            return "A preference key is required."
        if key not in spec.preference_keys:
            return "That preference key is outside this workspace's bounded policy."
    if action == "preferences.set" and "value" not in arguments:
        return "A preference value is required."
    if action == "preferences.set":
        try:
            arguments["value"] = normalized_preference_value(
                str(arguments.get("key") or "").strip(), arguments.get("value")
            )
        except (KeyError, TypeError, ValidationError, ValueError):
            return "Preference value is invalid for the live structured settings field."
    if action.startswith("mission.job.") and not str(arguments.get("target_id") or "").strip():
        return "A Mission Control job id is required."
    if action == "office.view.set_follow_agent":
        from thomas.server.office_state import normalize_follow_agent_id

        try:
            arguments["target_id"] = normalize_follow_agent_id(arguments.get("target_id"))
        except ValueError as exc:
            return str(exc)
    if action == "canvas.spec.save":
        from thomas.server.routes.canvas_studio_routes import _ID_RE

        target_id = str(arguments.get("target_id") or "").strip()
        payload = arguments.get("payload")
        if not target_id or not isinstance(payload, dict) or not isinstance(payload.get("root"), dict):
            return "A stable spec id and a Canvas spec payload with root are required."
        if _ID_RE.fullmatch(target_id) is None:
            return "Canvas spec id must use 1-128 letters, numbers, periods, underscores, or hyphens."
    if action == "library.project.move":
        payload = arguments.get("payload")
        if not str(arguments.get("target_id") or "").strip() or not isinstance(payload, dict):
            return "A project id and x/y position payload are required."
        x, y = payload.get("x"), payload.get("y")
        if not isinstance(x, int) or isinstance(x, bool) or not isinstance(y, int) or isinstance(y, bool):
            return "Library x and y must be integer coordinates."
        if x < 0 or y < 0 or x > 100_000 or y > 100_000:
            return "Library coordinates are outside the safe board bounds."
    if action in {"channels.discord.set_enabled", "marketplace.plugin.set_enabled"}:
        if action.startswith("marketplace.") and not str(arguments.get("target_id") or "").strip():
            return "An installed plugin id is required."
        if not isinstance(arguments.get("value"), bool):
            return "The enabled value must be true or false."
    if action == "paper_trading.propose":
        payload = arguments.get("payload")
        if not isinstance(payload, dict):
            return "A paper-trade proposal payload is required."
        required = ("symbol", "side", "thesis", "invalidation")
        if any(not str(payload.get(field) or "").strip() for field in required):
            return "Paper proposals require symbol, side, thesis, and invalidation."
        if str(payload.get("side") or "").strip().lower() not in {"buy", "sell"}:
            return "Paper proposal side must be buy or sell."
    return ""


__all__ = ["validate_workspace_action"]
