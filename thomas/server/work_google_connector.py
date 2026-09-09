"""Google Workspace execution for a single Work connector credential."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from thomas.integrations.google_workspace import GoogleWorkspaceIntegration
from thomas.integrations.google_workspace.integration import GoogleWorkspaceIntegrationError
from thomas.server.work_connector_registry import WorkConnectorExecutionError, WorkExecutionBinding
from thomas.tools.base import ToolResult


class _ScopedCredentialStore:
    """Expose only one credential to a short-lived integration instance."""

    def __init__(self, token_json: str) -> None:
        self._token_json = token_json

    def get(self, key: str) -> str | None:
        return self._token_json if key == "tokens" else None

    def put(self, key: str, value: str) -> None:
        if key == "tokens":
            self._token_json = str(value or "")


def _credential_payload(secret: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(str(secret or ""))
    except json.JSONDecodeError as exc:
        raise WorkConnectorExecutionError("The selected Google Workspace credential is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise WorkConnectorExecutionError("The selected Google Workspace credential has an invalid shape.")
    nested = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else None
    tokens = dict(nested or payload)
    if not str(tokens.get("access_token") or tokens.get("refresh_token") or "").strip():
        raise WorkConnectorExecutionError("The selected Google Workspace credential contains no usable token.")
    oauth = payload.get("oauth") if isinstance(payload.get("oauth"), dict) else payload
    return tokens, dict(oauth)


def _calendar_window(days: int) -> tuple[str, str]:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=max(1, int(days)))
    return start.isoformat(), end.isoformat()


def _operation(tool_name: str, args: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    name = str(tool_name or "").strip().lower()
    data = dict(args or {})
    if name == "email.read":
        folder = str(data.pop("folder", "inbox") or "inbox").strip()
        query = str(data.pop("filter", "") or "").strip()
        return (
            "gmail",
            "list_messages",
            {
                "query": query,
                "max_results": max(1, min(50, int(data.pop("count", 10) or 10))),
                "label_ids": [folder.upper()] if folder else None,
            },
        )
    if name == "email.get":
        return "gmail", "get_message", {"message_id": str(data.get("message_id") or "")}
    if name == "email.send":
        return (
            "gmail",
            "send_message",
            {
                "to": str(data.get("to") or ""),
                "subject": str(data.get("subject") or ""),
                "body": str(data.get("body") or ""),
            },
        )
    if name == "email.reply":
        return (
            "gmail",
            "reply_to_message",
            {
                "message_id": str(data.get("message_id") or ""),
                "body": str(data.get("body") or ""),
            },
        )
    if name in {"calendar.today", "calendar.week"}:
        time_min, time_max = _calendar_window(1 if name.endswith("today") else 7)
        return (
            "calendar",
            "list_events",
            {
                "calendar_id": "primary",
                "time_min": time_min,
                "time_max": time_max,
                "max_results": 50,
            },
        )
    if name == "calendar.create":
        return (
            "calendar",
            "create_event",
            {
                "calendar_id": "primary",
                "summary": str(data.get("title") or ""),
                "start": str(data.get("start") or ""),
                "end": str(data.get("end") or ""),
                "description": str(data.get("description") or ""),
            },
        )
    if name == "calendar.suggest_times":
        days = max(1, min(90, int(data.get("days_ahead", 14) or 14)))
        time_min, time_max = _calendar_window(days)
        calendars = data.get("calendars") or ["primary"]
        if isinstance(calendars, str):
            calendars = [calendars]
        return (
            "calendar",
            "check_freebusy",
            {
                "calendar_ids": [str(value) for value in calendars],
                "time_min": time_min,
                "time_max": time_max,
            },
        )
    if name == "drive.list":
        return (
            "drive",
            "list_files",
            {
                "query": str(data.get("query") or ""),
                "folder_id": str(data.get("folder_id") or "") or None,
                "max_results": max(1, min(100, int(data.get("max_results", 50) or 50))),
            },
        )
    if name == "drive.get":
        return "drive", "get_file", {"file_id": str(data.get("file_id") or "")}
    if name == "drive.search":
        return (
            "drive",
            "search_files",
            {
                "query": str(data.get("query") or ""),
                "max_results": max(1, min(100, int(data.get("max_results", 50) or 50))),
            },
        )
    if name == "drive.create_folder":
        return (
            "drive",
            "create_folder",
            {
                "name": str(data.get("name") or ""),
                "parent_id": str(data.get("parent_id") or "") or None,
            },
        )
    if name == "drive.share":
        return (
            "drive",
            "share_file",
            {
                "file_id": str(data.get("file_id") or ""),
                "email": str(data.get("email") or ""),
                "role": str(data.get("role") or "reader"),
            },
        )
    raise WorkConnectorExecutionError("This Google Workspace tool is not supported by Work execution.")


class GoogleWorkspaceConnectorExecutor:
    """Execute one call with a fresh integration bound to one credential."""

    def __init__(
        self,
        integration_factory: Callable[..., Any] = GoogleWorkspaceIntegration,
    ) -> None:
        self._integration_factory = integration_factory

    async def execute(
        self,
        binding: WorkExecutionBinding,
        tool_name: str,
        args: dict[str, Any],
        credential_secret: str,
    ) -> ToolResult:
        try:
            tokens, oauth = _credential_payload(credential_secret)
            service, operation, kwargs = _operation(tool_name, args)
            scoped_store = _ScopedCredentialStore(json.dumps(tokens, ensure_ascii=True))
            integration = self._integration_factory(
                client_id=str(oauth.get("client_id") or ""),
                client_secret=str(oauth.get("client_secret") or ""),
                redirect_uri=str(oauth.get("redirect_uri") or "http://127.0.0.1"),
                scopes=[str(scope) for scope in oauth.get("scopes") or []] or None,
                secrets_manager=scoped_store,
                secrets_key="tokens",
            )
            await integration.connect()
            try:
                data = await integration.execute(
                    command=str(tool_name or ""),
                    service=service,
                    operation=operation,
                    **kwargs,
                )
            finally:
                await integration.disconnect()
            return ToolResult(
                ok=True,
                data={"account_id": binding.account_id, "provider": binding.provider, "result": data},
            )
        except WorkConnectorExecutionError as exc:
            return ToolResult(ok=False, error=str(exc))
        except (GoogleWorkspaceIntegrationError, OSError, RuntimeError, TypeError, ValueError):
            return ToolResult(
                ok=False,
                error=f"Google Workspace execution failed for Work account '{binding.account_id}'.",
            )


__all__ = ["GoogleWorkspaceConnectorExecutor"]
