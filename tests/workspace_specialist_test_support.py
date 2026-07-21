from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from thomas.server.workspace_specialist_runtime import WorkspaceResidentOperator


class Dispatcher:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))

    async def emit_text(self, text: str) -> None:
        self.events.append({"type": "text", "text": text})

    async def emit_thinking(self, text: str, phase: str = "thinking", duration_ms: int = 0) -> None:
        self.events.append({"type": "thinking", "text": text, "phase": phase})

    async def emit_tool_start(
        self, name: str, tool_id: str = "", args: dict[str, Any] | None = None
    ) -> None:
        self.events.append({"type": "tool_start", "name": name, "id": tool_id, "args": args or {}})

    async def emit_tool_result(
        self,
        name: str,
        result: str = "",
        ok: bool = True,
        elapsed_ms: int = 0,
        tool_id: str = "",
    ) -> None:
        self.events.append(
            {"type": "tool_result", "name": name, "id": tool_id, "ok": ok, "result": result}
        )

    async def emit_done(self, **fields: Any) -> None:
        self.events.append({"type": "done", **fields})


class Tools:
    def __init__(self) -> None:
        self.values = {"theme": "light", "default_token_economy": "optimal"}
        self.proposals: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, name: str) -> object | None:
        available = {
            "paper_trading.list_proposals",
            "paper_trading.propose",
            "preferences_get",
            "preferences_list",
            "preferences_set",
        }
        return object() if name in available else None

    async def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(args)))
        if name == "preferences_get":
            return {"ok": True, "data": {"key": args["key"], "value": self.values.get(args["key"])}}
        if name == "preferences_list":
            return {"ok": True, "data": {"preferences": dict(self.values)}}
        if name == "preferences_set":
            self.values[args["key"]] = args.get("value")
            return {"ok": True, "data": {"set": True, "key": args["key"]}}
        if name == "paper_trading.propose":
            proposal = {"id": "proposal-1", "status": "pending_approval", **args}
            self.proposals.append(proposal)
            return {"ok": True, "data": proposal}
        if name == "paper_trading.list_proposals":
            return {"ok": True, "data": list(self.proposals)}
        return {"ok": False, "error": "unknown tool"}


class GuardedRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, *, executor, tool_call, **kwargs):
        self.calls.append({"tool_call": dict(tool_call), **kwargs})
        return await executor(tool_call)


def operator(
    workspace: str,
    dispatcher: Dispatcher,
    *,
    tools: Any = None,
    guarded_runner: Any = None,
    autonomy_level: int = 3,
    app: Any = None,
    config: Any = None,
    preferences_store: Any = None,
    tool_policy: Any = None,
    office_store: Any = None,
) -> WorkspaceResidentOperator:
    config = config or SimpleNamespace(
        tools=SimpleNamespace(sandbox_path="C:/sandbox"),
        memory=SimpleNamespace(root_path=Path("C:/runtime")),
    )
    return WorkspaceResidentOperator(
        app={} if app is None else app,
        context_id=f"workspace:{workspace}",
        tools=tools,
        guarded_runner=guarded_runner,
        config=config,
        session_id="resident-session",
        autonomy_level=autonomy_level,
        user_prompt="Update this workspace",
        emit_event=dispatcher.emit,
        user_id="owner-test",
        preferences_store=preferences_store,
        tool_policy=tool_policy
        or SimpleNamespace(
            allow_file_write=True,
            allow_channels=True,
            allow_network=True,
        ),
        office_store=office_store,
    )
