from __future__ import annotations

from typing import Any

from thomas.tools.base import Tool, ToolResult

from .contracts import DesktopOperatorError
from .manager import get_global_desktop_operator_manager


class _DesktopTool(Tool):
    category = "desktop"

    def _client(self):
        return get_global_desktop_operator_manager().ensure_client()

    async def _run(self, endpoint: str, payload: dict[str, Any] | None = None) -> ToolResult:
        try:
            return ToolResult(ok=True, data=self._client().call(endpoint, payload or {}))
        except DesktopOperatorError as exc:
            return ToolResult(ok=False, error=f"{exc.code}: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")


class DesktopStartSessionTool(_DesktopTool):
    name = "desktop.start_session"
    description = "Start a desktop operator session for one allowlisted workflow profile."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["workflow_profile"],
        "properties": {
            "workflow_profile": {"type": "string"},
            "session_type": {"type": ["string", "null"]},
            "session_ttl_s": {"type": ["integer", "null"], "minimum": 30},
            "metadata": {"type": ["object", "null"]},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/start_session", args)


class DesktopPauseSessionTool(_DesktopTool):
    name = "desktop.pause_session"
    description = "Pause the active desktop session without tearing it down."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {
            "session_id": {"type": "string"},
            "reason": {"type": ["string", "null"]},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/pause_session", args)


class DesktopResumeSessionTool(_DesktopTool):
    name = "desktop.resume_session"
    description = "Resume a paused desktop session after explicit approval or recovery."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {
            "session_id": {"type": "string"},
            "approved": {"type": ["boolean", "null"]},
            "reason": {"type": ["string", "null"]},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/resume_session", args)


class DesktopTerminateSessionTool(_DesktopTool):
    name = "desktop.terminate_session"
    description = "Terminate the active desktop session and leave the VM/run in a safe stopped state."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {
            "session_id": {"type": "string"},
            "reason": {"type": ["string", "null"]},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/terminate_session", args)


class DesktopGetRiskStateTool(_DesktopTool):
    name = "desktop.get_risk_state"
    description = "Return current desktop session risk, retry budgets, and refusal state."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {"session_id": {"type": "string"}},
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/get_risk_state", args)


class DesktopListAppsTool(_DesktopTool):
    name = "desktop.list_apps"
    description = "List allowlisted desktop apps/workflows Thomas can bind in the current session target."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title_contains": {"type": ["string", "null"]},
            "executable_contains": {"type": ["string", "null"]},
            "visible_only": {"type": ["boolean", "null"]},
            "limit": {"type": ["integer", "null"], "minimum": 1},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/list_apps", args)


class DesktopBindAppTool(_DesktopTool):
    name = "desktop.bind_app"
    description = "Bind the active desktop session to one allowlisted app window for the chosen workflow profile."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {
            "session_id": {"type": "string"},
            "window_handle": {"type": ["integer", "null"]},
            "title_contains": {"type": ["string", "null"]},
            "executable_contains": {"type": ["string", "null"]},
            "move_to_primary": {"type": ["boolean", "null"]},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/bind_app", args)


class DesktopCaptureTool(_DesktopTool):
    name = "desktop.capture"
    description = "Capture the bound app window and return capture metadata."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {"session_id": {"type": "string"}},
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/capture", args)


class DesktopActTool(_DesktopTool):
    name = "desktop.act"
    description = "Execute one stable workflow action or generic scoped action in the active desktop session."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id", "action"],
        "properties": {
            "session_id": {"type": "string"},
            "action": {"type": "string"},
            "params": {"type": ["object", "null"]},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/act", args)


class DesktopVerifyTool(_DesktopTool):
    name = "desktop.verify"
    description = "Verify desktop workflow state or output artifacts before claiming success."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {
            "session_id": {"type": "string"},
            "mode": {"type": ["string", "null"]},
            "title_contains": {"type": ["string", "null"]},
            "ocr_contains": {"type": ["string", "null"]},
            "artifact_path": {"type": ["string", "null"]},
            "capture_source": {"type": ["string", "null"]},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/verify", args)


class DesktopRecoverTool(_DesktopTool):
    name = "desktop.recover"
    description = "Attempt a scoped desktop recovery step such as ensure_visible, refresh_state, or rebind_foreground."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {
            "session_id": {"type": "string"},
            "strategy": {"type": ["string", "null"]},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/recover", args)


class DesktopEndSessionTool(_DesktopTool):
    name = "desktop.end_session"
    description = "End the active desktop operator session and clear scoped state."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {"session_id": {"type": "string"}},
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/end_session", args)


class DesktopListWindowsTool(_DesktopTool):
    name = "desktop.list_windows"
    description = "Compatibility alias for desktop.list_apps."
    parameters = DesktopListAppsTool.parameters

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/list_windows", args)


class DesktopBindWindowTool(_DesktopTool):
    name = "desktop.bind_window"
    description = "Compatibility tool that starts a workflow session and binds a matching window in one call."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "window_handle": {"type": ["integer", "null"]},
            "title_contains": {"type": ["string", "null"]},
            "executable_contains": {"type": ["string", "null"]},
            "move_to_primary": {"type": ["boolean", "null"]},
            "session_ttl_s": {"type": ["integer", "null"], "minimum": 30},
            "workflow_profile": {"type": ["string", "null"]},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/bind_window", args)


class DesktopCaptureWindowTool(_DesktopTool):
    name = "desktop.capture_window"
    description = "Compatibility alias for desktop.capture."
    parameters = DesktopCaptureTool.parameters

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/capture_window", args)


class DesktopAccessibilitySnapshotTool(_DesktopTool):
    name = "desktop.ax_snapshot"
    description = "Return an accessibility snapshot for the bound window when UIAutomation is available."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {"session_id": {"type": "string"}},
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/ax_snapshot", args)


class DesktopReadStateTool(_DesktopTool):
    name = "desktop.read_state"
    description = "Return merged desktop state including capture, accessibility, OCR summary, workflow readiness, and risk posture."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {"session_id": {"type": "string"}},
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/read_state", args)


class DesktopClickTool(_DesktopTool):
    name = "desktop.click"
    description = "Low-level scoped click inside the bound app window."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {
            "session_id": {"type": "string"},
            "x": {"type": ["integer", "null"]},
            "y": {"type": ["integer", "null"]},
            "selector": {"type": ["object", "null"]},
            "button": {"type": ["string", "null"]},
            "double": {"type": ["boolean", "null"]},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/click", args)


class DesktopTypeTool(_DesktopTool):
    name = "desktop.type"
    description = "Low-level scoped typing inside the bound app window."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id", "text"],
        "properties": {"session_id": {"type": "string"}, "text": {"type": "string"}},
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/type", args)


class DesktopPressKeysTool(_DesktopTool):
    name = "desktop.press_keys"
    description = "Low-level approved key input for the bound app window."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id", "keys"],
        "properties": {
            "session_id": {"type": "string"},
            "keys": {"type": "array", "items": {"type": "string"}},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/press_keys", args)


class DesktopDragTool(_DesktopTool):
    name = "desktop.drag"
    description = "Low-level bounded drag inside the bound app client rect."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id", "start_x", "start_y", "end_x", "end_y"],
        "properties": {
            "session_id": {"type": "string"},
            "start_x": {"type": "integer"},
            "start_y": {"type": "integer"},
            "end_x": {"type": "integer"},
            "end_y": {"type": "integer"},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/drag", args)


class DesktopEnsureVisibleTool(_DesktopTool):
    name = "desktop.ensure_visible"
    description = "Low-level focus/visibility recovery for the bound app window."
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "required": ["session_id"],
        "properties": {
            "session_id": {"type": "string"},
            "move_to_primary": {"type": ["boolean", "null"]},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._run("/ensure_visible", args)


def register_desktop_operator_tools(registry) -> None:
    for tool in [
        DesktopStartSessionTool(),
        DesktopPauseSessionTool(),
        DesktopResumeSessionTool(),
        DesktopTerminateSessionTool(),
        DesktopGetRiskStateTool(),
        DesktopListAppsTool(),
        DesktopBindAppTool(),
        DesktopCaptureTool(),
        DesktopActTool(),
        DesktopVerifyTool(),
        DesktopRecoverTool(),
        DesktopEndSessionTool(),
        DesktopListWindowsTool(),
        DesktopBindWindowTool(),
        DesktopCaptureWindowTool(),
        DesktopAccessibilitySnapshotTool(),
        DesktopReadStateTool(),
        DesktopClickTool(),
        DesktopTypeTool(),
        DesktopPressKeysTool(),
        DesktopDragTool(),
        DesktopEnsureVisibleTool(),
    ]:
        registry.register(tool)
