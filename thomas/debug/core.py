"""Debug toolkit with breakpoints, variable inspection, and profiling.

Implements debugging and profiling capabilities for development.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BreakpointType(str, Enum):
    """Types of breakpoints."""

    LINE = "line"
    CONDITIONAL = "conditional"
    EXCEPTION = "exception"
    FUNCTION = "function"


@dataclass
class Breakpoint:
    """A breakpoint in the debugger."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    breakpoint_type: BreakpointType = BreakpointType.LINE
    location: str = ""  # file:line or function name
    condition: Callable | None = None
    enabled: bool = True
    hit_count: int = 0

    def should_break(self) -> bool:
        """Check if breakpoint should trigger."""
        if not self.enabled:
            return False
        if self.breakpoint_type == BreakpointType.CONDITIONAL and self.condition:
            try:
                return self.condition()
            except Exception:
                return False
        return True

    def on_hit(self) -> None:
        """Record a breakpoint hit."""
        self.hit_count += 1


@dataclass
class StackFrame:
    """A stack frame in the execution stack."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    function_name: str = ""
    file: str = ""
    line_number: int = 0
    local_variables: dict[str, Any] = field(default_factory=dict)
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "function": self.function_name,
            "file": self.file,
            "line": self.line_number,
            "local_vars": list(self.local_variables.keys()),
            "arguments": list(self.arguments.keys()),
        }


class DebugSession:
    """A debugging session."""

    _MAX_EXECUTION_LOG_SIZE = 1000

    def __init__(self, name: str = "session"):
        self.id = str(uuid.uuid4())
        self.name = name
        self.status = "active"  # active, paused, stopped
        self.breakpoints: dict[str, Breakpoint] = {}
        self.call_stack: list[StackFrame] = []
        self.variables: dict[str, Any] = {}
        self.watches: dict[str, str] = {}  # var_name -> expression
        self.execution_log: list[dict[str, Any]] = []
        self.created_at = datetime.now()

    def add_breakpoint(self, breakpoint: Breakpoint) -> None:
        """Add a breakpoint."""
        self.breakpoints[breakpoint.id] = breakpoint

    def remove_breakpoint(self, breakpoint_id: str) -> bool:
        """Remove a breakpoint."""
        if breakpoint_id in self.breakpoints:
            del self.breakpoints[breakpoint_id]
            return True
        return False

    def push_frame(self, frame: StackFrame) -> None:
        """Push a frame onto the call stack."""
        self.call_stack.append(frame)
        self.execution_log.append(
            {"timestamp": datetime.now().isoformat(), "action": "frame_push", "function": frame.function_name}
        )
        # Keep only last 1000 entries
        if len(self.execution_log) > self._MAX_EXECUTION_LOG_SIZE:
            self.execution_log = self.execution_log[-self._MAX_EXECUTION_LOG_SIZE:]

    def pop_frame(self) -> StackFrame | None:
        """Pop a frame from the call stack."""
        if self.call_stack:
            frame = self.call_stack.pop()
            self.execution_log.append(
                {"timestamp": datetime.now().isoformat(), "action": "frame_pop", "function": frame.function_name}
            )
            # Keep only last 1000 entries
            if len(self.execution_log) > self._MAX_EXECUTION_LOG_SIZE:
                self.execution_log = self.execution_log[-self._MAX_EXECUTION_LOG_SIZE:]
            return frame
        return None

    def get_current_frame(self) -> StackFrame | None:
        """Get the current frame."""
        if self.call_stack:
            return self.call_stack[-1]
        return None

    def set_variable(self, name: str, value: Any) -> None:
        """Set a variable value."""
        self.variables[name] = value

    def get_variable(self, name: str) -> Any | None:
        """Get a variable value."""
        return self.variables.get(name)

    def add_watch(self, name: str, expression: str) -> None:
        """Add a watch expression."""
        self.watches[name] = expression

    def pause(self) -> None:
        """Pause execution."""
        self.status = "paused"
        self.execution_log.append({"timestamp": datetime.now().isoformat(), "action": "paused"})
        # Keep only last 1000 entries
        if len(self.execution_log) > self._MAX_EXECUTION_LOG_SIZE:
            self.execution_log = self.execution_log[-self._MAX_EXECUTION_LOG_SIZE:]

    def resume(self) -> None:
        """Resume execution."""
        self.status = "active"
        self.execution_log.append({"timestamp": datetime.now().isoformat(), "action": "resumed"})
        # Keep only last 1000 entries
        if len(self.execution_log) > self._MAX_EXECUTION_LOG_SIZE:
            self.execution_log = self.execution_log[-self._MAX_EXECUTION_LOG_SIZE:]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.id,
            "name": self.name,
            "status": self.status,
            "breakpoints": len(self.breakpoints),
            "call_stack_depth": len(self.call_stack),
            "variables": len(self.variables),
        }


class Profiler:
    """Performance profiler."""

    def __init__(self, name: str = "profiler"):
        self.id = str(uuid.uuid4())
        self.name = name
        self.function_stats: dict[str, dict[str, Any]] = {}
        self.enabled = False

    def start(self) -> None:
        """Start profiling."""
        self.enabled = True

    def stop(self) -> None:
        """Stop profiling."""
        self.enabled = False

    def profile_function(self, func_name: str) -> None:
        """Start profiling a function."""
        if func_name not in self.function_stats:
            self.function_stats[func_name] = {
                "call_count": 0,
                "total_time": 0.0,
                "min_time": float("inf"),
                "max_time": 0.0,
                "calls": [],
            }

    def record_call(self, func_name: str, duration_ms: float) -> None:
        """Record a function call."""
        if not self.enabled:
            return

        if func_name not in self.function_stats:
            self.profile_function(func_name)

        stats = self.function_stats[func_name]
        stats["call_count"] += 1
        stats["total_time"] += duration_ms
        stats["min_time"] = min(stats["min_time"], duration_ms)
        stats["max_time"] = max(stats["max_time"], duration_ms)
        stats["calls"].append({"timestamp": datetime.now().isoformat(), "duration_ms": duration_ms})

    def get_stats(self, func_name: str) -> dict[str, Any] | None:
        """Get statistics for a function."""
        if func_name not in self.function_stats:
            return None

        stats = self.function_stats[func_name]
        call_count = stats["call_count"]

        return {
            "function": func_name,
            "call_count": call_count,
            "total_time_ms": stats["total_time"],
            "avg_time_ms": stats["total_time"] / call_count if call_count > 0 else 0,
            "min_time_ms": stats["min_time"] if stats["min_time"] != float("inf") else 0,
            "max_time_ms": stats["max_time"],
        }

    def get_all_stats(self) -> list[dict[str, Any]]:
        """Get statistics for all profiled functions."""
        return [self.get_stats(name) for name in self.function_stats.keys()]

    def reset(self) -> None:
        """Reset all statistics."""
        self.function_stats.clear()


class DebugToolkit:
    """Main debug toolkit."""

    _MAX_ALERT_HISTORY_SIZE = 1000

    def __init__(self, name: str = "debug"):
        self.id = str(uuid.uuid4())
        self.name = name
        self.sessions: dict[str, DebugSession] = {}
        self.profiler = Profiler()
        self.logs: list[dict[str, Any]] = []

    def create_session(self, name: str = "session") -> DebugSession:
        """Create a debug session."""
        session = DebugSession(name)
        self.sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> DebugSession | None:
        """Get a debug session."""
        return self.sessions.get(session_id)

    def log_event(self, level: str, message: str, context: dict | None = None) -> None:
        """Log a debug event."""
        self.logs.append(
            {"timestamp": datetime.now().isoformat(), "level": level, "message": message, "context": context or {}}
        )
        # Keep only last 1000 entries
        if len(self.logs) > self._MAX_ALERT_HISTORY_SIZE:
            self.logs = self.logs[-self._MAX_ALERT_HISTORY_SIZE:]

    def get_logs(self, level: str | None = None) -> list[dict[str, Any]]:
        """Get debug logs."""
        if level:
            return [l for l in self.logs if l["level"] == level]
        return self.logs

    def get_toolkit_stats(self) -> dict[str, Any]:
        """Get toolkit statistics."""
        return {
            "toolkit_id": self.id,
            "name": self.name,
            "active_sessions": sum(1 for s in self.sessions.values() if s.status == "active"),
            "total_sessions": len(self.sessions),
            "profiled_functions": len(self.profiler.function_stats),
            "log_entries": len(self.logs),
        }
