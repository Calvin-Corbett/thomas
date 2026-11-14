"""A productive Build helper owns one text file in a private project snapshot."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Any

from thomas.agent.loop_tool_paths import _sanitize_write_tool_path
from thomas.core.file_access import WORKSPACE
from thomas.tools.base import Tool, ToolResult
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.repo_code_index import RepoIndexTool
from thomas.tools.task_spawn import SpawnAgentTool

from .build_agent_workspace import BuildWorkspace, fingerprint, integration_guard, relative_file


class _AssignedWriteTool(Tool):
    name = "fs.write_file"
    category = "filesystem"
    description = "Write your one assigned text file in this private workspace. No other path is writable."

    def __init__(self, registry: Any, workspace: BuildWorkspace, max_size: int) -> None:
        self.parameters = registry.get(self.name).parameters
        self._base, self._workspace, self._max_size = registry, workspace, max_size

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        raw = Path(str(args.get("path") or ""))
        path = raw if raw.is_absolute() else self._workspace.root / raw
        if path.resolve() != self._workspace.root / self._workspace.path:
            return ToolResult(ok=False, error=f"Only assigned file {self._workspace.path} is writable")
        try:
            relative_file(self._workspace.root, self._workspace.path)
        except (OSError, ValueError) as exc:
            return ToolResult(ok=False, error=str(exc))
        content = str(args.get("content") or "")
        if len(content.encode("utf-8")) > self._max_size or "\0" in content:
            return ToolResult(ok=False, error="Assigned output must be bounded UTF-8 text without NUL bytes")
        return await self._base.execute(self.name, {"path": self._workspace.path, "content": content})


def _builder_tools(workspace: BuildWorkspace, config: Any, read_subset: Any) -> ToolRegistry:
    base = ToolRegistry()
    register_filesystem_tools(
        base,
        workspace.root,
        config.tools.max_file_size,
        file_access=WORKSPACE,
        project_root=workspace.root,
    )
    register_code_search_tools(base, workspace.root)
    base.register(RepoIndexTool(workspace.root))
    registry = read_subset(base)
    registry.register(_AssignedWriteTool(base, workspace, config.tools.max_file_size))
    return registry


class BuildTeamTool(Tool):
    optional_empty_path_keys = ("path",)
    name = "task.spawn"
    category = "agents"

    def __init__(
        self,
        *,
        review_tool: Tool,
        run_child: Any,
        record_event: Any,
        parent: Any,
        config: Any,
        deadline: float,
        can_write: bool,
        protected_paths: list[str],
        read_subset: Any,
        scope: Any = None,
    ) -> None:
        self.parameters = deepcopy(review_tool.parameters)
        self.parameters["properties"]["path"] = {
            "type": "string",
            "description": "Output file selects the builder role. Omit or use an empty string for read-only review. Whitespace-only paths are invalid.",
        }
        self.parameters["properties"]["context_files"] = {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 100,
            "description": "For large projects, copy only these exact input files plus your assigned output. The helper cannot see omitted files.",
        }
        self.description = (
            "Delegate independent work to a helper using your selected model. Give title and a complete brief. "
            "With path, the helper builds exactly that one UTF-8 text file in a private copy of current project files; "
            "its result is integrated only if the parent target is unchanged. Choose distinct files for concurrent helpers. "
            "Omit path or use an empty string for read-only source review: those helpers cannot edit files. "
            "A nonempty output path selects the builder model, even if the title says review; titles do not select models. "
            "Helpers cannot run commands, browse, or spawn. You own combined tests, preview, and final verification. "
            "A failed, cancelled, overlapping, or stale helper never counts as integrated."
        )
        if not can_write:
            self.description += " This run permits read-only review only; output paths will be refused."
        self._review = review_tool
        self._run_child, self._record = run_child, record_event
        self._parent, self._config, self._deadline = parent, config, deadline
        self._can_write, self._protected, self._read_subset = can_write, protected_paths, read_subset
        self._scope = scope
        self._active_paths: set[str] = set()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self.execute_assigned(args)

    async def execute_assigned(
        self, args: dict[str, Any], *, request_admission=None, observe=None, model_choice=None
    ) -> ToolResult:
        if "path" not in args or args["path"] == "":
            return await self._review.execute(args)
        if not isinstance(args["path"], str) or not args["path"].strip():
            return ToolResult(
                ok=False, error="path must name an output file; omit it or use an empty string for review"
            )
        if not self._can_write or self._parent.get("fs.write_file") is None:
            return ToolResult(ok=False, error="This run does not permit writable helpers; omit path for source review")
        # A new private registry cannot infer arbitrary wrappers' additional
        # authority. Keep that case closed until its policy can be translated.
        if getattr(self._parent, "policy", None) is not None:
            return ToolResult(ok=False, error="Additional inherited tool policy permits source review only")
        project = (self._config.tools.sandbox_path if self._scope is None else Path(self._scope.root)).resolve()
        try:
            path = relative_file(project, str(args["path"]))
            _, error = _sanitize_write_tool_path(
                {"path": path},
                sandbox_root=project,
                file_access=self._config.tools.file_access,
                protected_paths=self._protected,
            )
            if error:
                return ToolResult(ok=False, error=error)
            source = project / path
            if source.exists():
                if source.stat().st_size > self._config.tools.max_file_size:
                    raise ValueError("Assigned output exceeds the parent file-size limit")
                data = source.read_bytes()
                if len(data) > self._config.tools.max_file_size or b"\0" in data:
                    raise ValueError("Assigned output must be bounded UTF-8 text without NUL bytes")
                data.decode("utf-8")
        except (OSError, ValueError) as exc:
            return ToolResult(ok=False, error=str(exc))
        key = path.casefold()
        if any(key == held or key.startswith(held + "/") or held.startswith(key + "/") for held in self._active_paths):
            return ToolResult(ok=False, error=f"Another helper already owns {path}; wait for it to finish")
        self._active_paths.add(key)

        async def build(child_id: str, title: str, instructions: str):
            workspace = None
            integrated = False
            try:
                if asyncio.get_running_loop().time() >= self._deadline:
                    raise TimeoutError("Build pass deadline reached before builder started")
                workspace = BuildWorkspace.create(project, child_id, path, context_files=args.get("context_files"))
                failed = False
                completed = False
                child_options = {} if request_admission is None else {"request_admission": request_admission}
                if model_choice is not None:
                    child_options["model_choice"] = model_choice
                async for event in self._run_child(
                    child_id,
                    title,
                    instructions,
                    workspace=workspace,
                    toolset=_builder_tools(workspace, self._config, self._read_subset),
                    **child_options,
                ):
                    failed |= event.get("type") == "error"
                    completed |= event.get("type") == "text"
                    yield event
                if failed or not completed:
                    workspace.record("failed", reason="child did not complete successfully")
                    if not failed:
                        yield {"type": "error", "error": "builder did not complete successfully"}
                    return
                content = workspace.candidate(max_size=self._config.tools.max_file_size)
                async with integration_guard(project, self._deadline):
                    workspace.check_base()
                    _, error = _sanitize_write_tool_path(
                        {"path": path},
                        sandbox_root=project,
                        file_access=self._config.tools.file_access,
                        protected_paths=self._protected,
                    )
                    if error:
                        raise ValueError(error)
                    result = await self._parent.execute("fs.write_file", {"path": path, "content": content})
                    if not result.ok:
                        raise ValueError(f"parent refused integration: {result.error}")
                    expected = fingerprint(content.encode("utf-8"))
                    # Windows text-mode writes can normalize LF to CRLF. Read
                    # the actual integrated bytes for the durable receipt.
                    actual = fingerprint((project / path).read_bytes())
                    if (project / path).read_text(encoding="utf-8") != content:
                        raise ValueError("integrated file readback did not match the candidate text")
                    integrated = True
                    workspace.record("integrated", candidate_text=expected, integrated_file=actual)
                yield {"type": "text", "text": f"\nIntegrated {path}; lead must verify the combined project."}
            except asyncio.CancelledError:
                if workspace is not None:
                    workspace.record("cancelled", integrated=integrated)
                raise
            except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
                if workspace is not None:
                    workspace.record("failed", reason=str(exc), integrated=integrated)
                yield {"type": "error", "error": str(exc)}

        def record(title: str, event: dict[str, Any]) -> None:
            tagged = {**event, "agent_mode": "builder"}
            self._record(title, tagged)
            if observe is not None:
                observe(tagged)

        try:
            tool = SpawnAgentTool(
                run_child=build,
                record_event=record,
            )
            return await tool.execute(args)
        finally:
            self._active_paths.discard(key)
