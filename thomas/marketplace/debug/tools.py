"""Tools for Debug module.

Provides tools for debugging, profiling, and inspection.
"""

from typing import Any

from thomas.marketplace.debug import core
from thomas.tools.base import Tool, ToolResult


class DebugSessionTool(Tool):
    """Manage debug sessions."""

    name = "debug_sessions"
    category = "debug"
    description = "Create and manage debug sessions"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_session", "list_sessions", "get_session"],
                "description": "Session action",
            },
            "session_name": {"type": "string", "description": "Name of the session"},
            "session_id": {"type": "string", "description": "Session identifier"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.toolkit = core.DebugToolkit()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_session":
                session_name = args.get("session_name", "session")
                session = self.toolkit.create_session(session_name)
                return ToolResult(
                    ok=True, data={"session_id": session.id, "session_name": session_name, "status": session.status}
                )

            elif action == "list_sessions":
                sessions = [s.to_dict() for s in self.toolkit.sessions.values()]
                return ToolResult(ok=True, data={"sessions": sessions})

            elif action == "get_session":
                session_id = args.get("session_id", "")
                session = self.toolkit.get_session(session_id)
                if session:
                    return ToolResult(ok=True, data=session.to_dict())
                else:
                    return ToolResult(ok=False, error=f"Session not found: {session_id}")

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class BreakpointTool(Tool):
    """Manage breakpoints."""

    name = "debug_breakpoints"
    category = "debug"
    description = "Create and manage breakpoints"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_breakpoint", "list_breakpoints", "remove_breakpoint"],
                "description": "Breakpoint action",
            },
            "session_id": {"type": "string", "description": "Session identifier"},
            "location": {"type": "string", "description": "File and line location"},
            "breakpoint_id": {"type": "string", "description": "Breakpoint identifier"},
        },
        "required": ["action", "session_id"],
    }

    def __init__(self):
        self.toolkit = core.DebugToolkit()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            session_id = args.get("session_id", "")

            session = self.toolkit.get_session(session_id)
            if not session:
                return ToolResult(ok=False, error=f"Session not found: {session_id}")

            if action == "add_breakpoint":
                location = args.get("location", "")
                bp = core.Breakpoint(breakpoint_type=core.BreakpointType.LINE, location=location)
                session.add_breakpoint(bp)
                return ToolResult(ok=True, data={"breakpoint_id": bp.id, "location": location})

            elif action == "list_breakpoints":
                breakpoints = [
                    {"id": b.id, "location": b.location, "enabled": b.enabled} for b in session.breakpoints.values()
                ]
                return ToolResult(ok=True, data={"breakpoints": breakpoints})

            elif action == "remove_breakpoint":
                bp_id = args.get("breakpoint_id", "")
                if session.remove_breakpoint(bp_id):
                    return ToolResult(ok=True, data={"removed": bp_id})
                else:
                    return ToolResult(ok=False, error=f"Breakpoint not found: {bp_id}")

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ProfilerTool(Tool):
    """Manage profiling."""

    name = "debug_profiler"
    category = "debug"
    description = "Profile function performance"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start_profile", "stop_profile", "get_stats"],
                "description": "Profiler action",
            },
            "function_name": {"type": "string", "description": "Function to profile"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.toolkit = core.DebugToolkit()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "start_profile":
                self.toolkit.profiler.start()
                return ToolResult(ok=True, data={"profiling": "started"})

            elif action == "stop_profile":
                self.toolkit.profiler.stop()
                return ToolResult(ok=True, data={"profiling": "stopped"})

            elif action == "get_stats":
                function_name = args.get("function_name")
                if function_name:
                    stats = self.toolkit.profiler.get_stats(function_name)
                    if stats:
                        return ToolResult(ok=True, data=stats)
                    else:
                        return ToolResult(ok=False, error=f"No stats for: {function_name}")
                else:
                    stats = self.toolkit.profiler.get_all_stats()
                    return ToolResult(ok=True, data={"stats": stats})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class InspectionTool(Tool):
    """Inspect variables and stack."""

    name = "debug_inspect"
    category = "debug"
    description = "Inspect variables, stack, and state"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get_variables", "get_stack", "add_watch"],
                "description": "Inspection action",
            },
            "session_id": {"type": "string", "description": "Session identifier"},
            "variable_name": {"type": "string", "description": "Variable to inspect"},
        },
        "required": ["action", "session_id"],
    }

    def __init__(self):
        self.toolkit = core.DebugToolkit()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            session_id = args.get("session_id", "")

            session = self.toolkit.get_session(session_id)
            if not session:
                return ToolResult(ok=False, error=f"Session not found: {session_id}")

            if action == "get_variables":
                return ToolResult(
                    ok=True, data={"variables": list(session.variables.keys()), "count": len(session.variables)}
                )

            elif action == "get_stack":
                stack = [frame.to_dict() for frame in session.call_stack]
                return ToolResult(ok=True, data={"stack_depth": len(stack), "frames": stack})

            elif action == "add_watch":
                var_name = args.get("variable_name", "")
                session.add_watch(var_name, var_name)
                return ToolResult(ok=True, data={"watch_added": var_name})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_debug_tools(registry):
    """Register all debug tools."""
    registry.register(DebugSessionTool())
    registry.register(BreakpointTool())
    registry.register(ProfilerTool())
    registry.register(InspectionTool())
