"""Direct Build's bounded review helpers and isolated one-file builders."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from copy import copy, deepcopy
from typing import Any

from thomas.agent.kernel_wiring import build_agent_loop
from thomas.agent.loop import AgentLoop
from thomas.agent.verification_contract import normalize_level
from thomas.core.events import EventType
from thomas.core.file_access import parse_file_access_level
from thomas.core.llm_client import LLMClient
from thomas.core.llm_request_admission import admission_key, shared_provider_admission
from thomas.core.llm_slot import models as model_slot
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry
from thomas.tools.task_spawn import SpawnAgentTool

from .build_agent_scheduler import BuildTeamScheduler
from .build_agent_writer import BuildTeamTool
from .build_claude_writer import run_claude_file_writer
from .build_team_tasks import drain_owned, owned_events
from .dispatch_agent_loop_translator import _AgentLoopForgeTranslator
from .forge_code_roles import ROLE_ENV, role_configs
from .run_control import HeldDeadline, RunControl

_READ_TOOLS = frozenset(
    {
        "fs.read_file",
        "fs.list_dir",
        "fs.search",
        "code.repo_index",
        "code.search",
        "code.find_definition",
        "code.find_references",
        "code.project_structure",
    }
)
_REVIEW_DESCRIPTION = (
    "Delegate a self-contained source inspection or review to a read-only helper using your selected model. "
    "The helper can read and search project files, then return findings. It cannot edit files, run commands, "
    "browse, generate images, or spawn agents. You own implementation, tests, and integration. "
    "Give a title and complete review brief. Calls wait for results; independent reviews may run together."
)
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_PROFILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
# You asked (2026-09-23): "make thomas split the game into multiple builders." At
# maximum reasoning effort only, the lead is told plainly to split independent work
# with task.team rather than leaving it a judgment call; below max it stays optional.
_MAX_SPLIT_INSTRUCTIONS = (
    " At maximum reasoning effort: when this request has two or more independent parts, "
    "split it with task.team in one call -- one builder per independent part, each owning "
    "only its own files -- then integrate and check the whole."
)
# A read-only reviewer's own cap, inside the pass's: its working time, so a pause does not count against it.
_REVIEW_CAP_S = 300.0


class _InheritedReadTool(Tool):
    """Forward through the parent's registry, including any policy wrapper."""

    def __init__(self, parent: Any, tool: Tool) -> None:
        self._parent = parent
        self.name = tool.name
        self.category = tool.category
        self.description = tool.description
        self.parameters = tool.parameters

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return await self._parent.execute(self.name, args)


def review_tools(parent: Any) -> ToolRegistry:
    registry = ToolRegistry()
    for name in sorted(_READ_TOOLS):
        tool = parent.get(name)
        if tool is not None:
            registry.register(_InheritedReadTool(parent, tool))
    return registry


def register_build_team(
    registry: Any,
    *,
    config: Any,
    model_config: Any,
    emit: Any,
    timeout: float,
    autonomy_level: int,
    tools_policy: str,
    token_economy: str,
    protected_paths: list[str],
    can_write: bool = False,
    scope: Any = None,
    control: RunControl | None = None,
) -> float:
    """Register helpers and return their shared absolute parent-pass deadline.

    ``control`` (a run with a control folder, ``run_control``): each helper's loop holds while you have the run
    paused and reads its own inbox, keyed by its id, so you can message it directly; the deadline moves out by every
    held stretch, for the helpers and team calls that start after it, and a helper already running waits on a
    :class:`HeldDeadline` that a pause moves out as it lasts."""
    deadline = asyncio.get_running_loop().time() + max(0.01, float(timeout))
    clock = control.clock if control is not None else None  # this pass's clock (register runs once per pass)
    model = str(model_config.model)
    configs = role_configs(model_config, os.environ.get(ROLE_ENV, ""))
    models = {"builder": str(configs["builder"].model), "read_only": str(configs["reviewer"].model)}

    def resolve_builder(choice: dict[str, str] | None) -> tuple[str, str]:
        if choice is None:
            selected = configs["builder"]
        else:
            profile, model_id = choice["profile"], choice["model_id"]
            if not _PROFILE.fullmatch(profile) or not _MODEL_ID.fullmatch(model_id):
                raise ValueError("invalid Build file-writer model choice")
            if profile == "claude_cli":
                if not model_id.startswith("claude:") or not (shutil.which("claude") or shutil.which("claude.cmd")):
                    raise ValueError("Claude CLI file-writer model is unavailable in this run")
                return model_id, "claude_cli"
            configured = config.models.get(profile)
            if configured is None:
                raise ValueError(f"Build file-writer profile is not configured: {profile}")
            selected = copy(configured)
            selected.model = model_id
            if selected.provider == "openai_codex":
                if profile != model_config.name or not getattr(model_config, "api_key", ""):
                    raise ValueError(f"Build file-writer account is not connected in this run: {profile}")
                selected.api_key = model_config.api_key
                selected._openai_codex_token_ready = getattr(model_config, "_openai_codex_token_ready", False)
            elif not selected.api_key:
                raise ValueError(f"Build file-writer API key is unavailable in this run: {profile}")
        return str(selected.model), admission_key(selected)

    emit(
        {
            "fc": "planning",
            "text": f"Build team models · Task manager: {model} · Builders: {models['builder']} · Reviewers: {models['read_only']}",
        }
    )
    last_speaker = ""

    def emit_child(child_id: str, title: str, event: dict[str, Any]) -> None:
        nonlocal last_speaker
        mode = str(event.get("agent_mode") or "read_only")
        tagged = {
            "agent_mode": mode,
            **event,
            "agent_id": child_id,
            "agent_title": title,
            "model": event.get("model") or models[mode],
        }
        # Child answers and contracts must never settle or overwrite the lead.
        if tagged.get("fc") in {"final", "acceptance", "error"}:
            tagged["fc"] = "meta"
        if tagged.get("name"):
            tagged["name"] = f"{title} > {tagged['name']}"
        if tagged.get("fc") == "say" and tagged.get("delta"):
            if last_speaker != child_id:
                tagged["text"] = f"\n[{title}] {tagged.get('text') or ''}"
            last_speaker = child_id
        elif tagged.get("text"):
            tagged["text"] = f"[{title}] {tagged['text']}"
            last_speaker = ""
        emit(tagged)

    def record(title: str, event: dict[str, Any]) -> None:
        kind = event.get("type")
        mode = str(event.get("agent_mode") or "read_only")
        text = str(event.get("text") or event.get("error") or "")
        if kind == "error":
            text = f"{title} failed: {text}"
        elif text.startswith("Spawned "):
            text += f" — {'isolated file builder' if mode == 'builder' else 'read-only source review'} · {models[mode]}"
        emit_child(
            str(event["child_id"]),
            title,
            {
                "fc": "meta",
                "text": text,
                "is_error": kind == "error",
                "agent_mode": mode,
                "model": event.get("model") or models[mode],
            },
        )

    async def run_child(
        child_id: str,
        title: str,
        instructions: str,
        *,
        workspace=None,
        toolset=None,
        request_admission=None,
        model_choice=None,
    ):
        mode = "builder" if workspace is not None else "read_only"
        now = asyncio.get_running_loop().time()
        # A hold already going when this helper starts is not its working time: its cap starts when that hold ends.
        holding = clock.held_seconds() - clock.held_seconds(current=False) if clock is not None else 0.0
        start_deadline = deadline if workspace is not None else min(deadline, now + _REVIEW_CAP_S - holding)
        # Without controls the fixed deadline, as before; with them, one a pause moves out while this helper runs.
        child_deadline = start_deadline if clock is None else HeldDeadline(start_deadline, clock)
        due_now = child_deadline() if callable(child_deadline) else child_deadline
        if due_now <= now:
            yield {"type": "error", "error": "Build pass deadline reached before helper started"}
            return
        child_config = deepcopy(config)
        child_config.tools.allow_shell = False
        child_config.tools.file_access = parse_file_access_level("workspace" if workspace else "read_only")
        if workspace is not None:
            child_config.tools.sandbox_root = str(workspace.root)
        # copy preserves dynamic OAuth readiness/account attributes as well as
        # the selected model and effort. No provider/profile fallback is allowed.
        selected = configs["builder" if workspace is not None else "reviewer"]
        if workspace is not None and model_choice is not None:
            resolve_builder(model_choice)
            if model_choice["profile"] == "claude_cli":
                # A `claude -p` writer cannot hold, so it keeps the fixed deadline it starts with.
                async for event in run_claude_file_writer(
                    workspace, toolset, instructions, model_id=model_choice["model_id"], deadline=due_now
                ):
                    yield event
                return
            selected = copy(config.models[model_choice["profile"]])
            selected.model = model_choice["model_id"]
            if selected.provider == "openai_codex":
                selected.api_key = model_config.api_key
                selected._openai_codex_token_ready = getattr(model_config, "_openai_codex_token_ready", False)
        owned_admission = request_admission is None
        if owned_admission:
            request_admission = shared_provider_admission(admission_key(selected), team=f"review:{child_id}")
        child_model = copy(selected)
        if workspace is None and str(getattr(child_model, "reasoning_effort", "")).lower() in {"high", "max"}:
            child_model.reasoning_effort = "medium"
        if selected.provider == "openai_codex":
            # One key per helper (not one for every helper of this mode and model in every team): each helper's calls
            # resend its own conversation, so its own key keeps them on the machines holding its last call.
            child_model._build_prompt_cache_key = f"build-helper:{mode}:{selected.model}:{child_id}"
        llm = model_slot().open(
            child_model,
            default=LLMClient,
            fallback_configs=[],
            failover_enabled=False,
            request_admission=request_admission,
        )
        translator = _AgentLoopForgeTranslator(
            lambda event: emit_child(child_id, title, {**event, "agent_mode": mode, "model": selected.model}),
            root=workspace.root if workspace is not None else None,
        )
        listening = False
        try:
            agent = build_agent_loop(
                child_config,
                llm,
                review_tools(registry) if toolset is None else toolset,
                conversation=[],
                memory=None,
                autonomy_level=autonomy_level,
                max_parallel_tools=4,
                default=AgentLoop,
            )
            # Concurrent children verify where their tools write, never process cwd.
            agent.verify_in_tool_workspace = workspace is not None
            agent._build_read_parallel_only = True
            if workspace is not None:
                agent.acceptance_owned_output = workspace.path
            agent.protected_paths = list(protected_paths)
            if control is not None:
                # Your pause holds this helper too, and what you send it directly arrives between its steps.
                agent.run_hold = control.hold
                agent._message_queue = control.inbox(child_id, title=title)
                control.listen(child_id, title)
                listening = True
            role_text = (
                "You are a read-only source-review helper. Read/search the project and report findings. "
                "You cannot edit files, run commands, browse, or delegate. The lead owns implementation "
                "and verification. Do not claim to have built or tested anything."
            )
            prompt = instructions
            if workspace is not None:
                role_text = (
                    f"You are an isolated builder. Your only writable file is {workspace.path}. "
                    "Read the private project snapshot and implement that one file with fs.write_file. "
                    "You cannot run commands, browse, or delegate. The lead will integrate your candidate "
                    "only if the parent target has not changed, then verify the combined project. "
                    "After writing, read back your owned file. Report in one plain sentence what you "
                    "changed, not a file report; do not claim tests or integration happened. If the acceptance contract requests "
                    "EVIDENCE and VERIFY lines, include them in your final reply: the engine runs "
                    "that verification command in your private workspace after you reply. This is "
                    "a finish declaration, not a tool call you need permission to execute. Do not "
                    "keep rewriting an unchanged file to satisfy a missing finish declaration."
                )
                if workspace.path.endswith((".py", ".pyi")):
                    role_text += (
                        "\n\nFor this Python file, the basic syntax verification line is:\n"
                        f'VERIFY: python -m py_compile "{workspace.path}"\n'
                        "Use a stronger task-specific check when assigned, and never replace a failing "
                        "assigned check with this syntax check. Put VERIFY on its own line. "
                        "The lead still owns behavioral tests and combined-project verification."
                    )
            agent._build_helper_role_text = role_text
            stream = agent.run(
                prompt,
                intent_text=instructions,
                mode="auto",
                tools_policy=tools_policy,
                token_economy=token_economy,
                job_type="coding",
            )
            async with owned_events(
                stream,
                deadline=child_deadline,
                name=f"build-stream:{child_id}",
            ) as events:
                async for event in events:
                    if event.type in {EventType.AGENT_ERROR, EventType.AGENT_END}:
                        detail = event.data.get("error") or event.data.get("reason") or event.data.get("message")
                        yield {"type": "error", "error": str(detail or "review ended before completion")}
                        return
                    if event.type == EventType.AGENT_DONE:
                        trace_fn = getattr(llm, "runtime_trace", None)
                        if callable(trace_fn):
                            trace = trace_fn()
                            active = trace.get("active") or {}
                            if (
                                active.get("model") != selected.model
                                or active.get("provider") != selected.provider
                                or active.get("profile") != selected.name
                                or trace.get("failover_used")
                            ):
                                yield {
                                    "type": "error",
                                    "error": "builder runtime model did not match its exact assignment",
                                }
                                return
                            yield {
                                "type": "model_runtime",
                                "model_used": active["model"],
                                "profile_used": active["profile"],
                                "provider_used": active["provider"],
                                "model": active["model"],
                            }
                        report = event.data.get("token_report") or {}
                        acceptance = report.get("acceptance_contract") or {}
                        if workspace is not None and acceptance.get("verdict", {}).get("met") is False:
                            yield {"type": "error", "error": "builder finished with unmet acceptance requirements"}
                            return
                        yield {"type": "text", "text": str(event.data.get("text") or "")}
                        return
                    translator.feed(event.type.value, event.data)
            yield {"type": "error", "error": "review stream ended without a completion event"}
        except (asyncio.TimeoutError, TimeoutError):
            yield {"type": "error", "error": f"{mode} helper deadline reached before completion"}
        finally:
            if listening and control is not None:
                control.stop_listening(child_id)
            translator.close()
            try:
                await drain_owned(llm.close())
            finally:
                if owned_admission:
                    request_admission.close()

    tool = SpawnAgentTool(run_child=run_child, record_event=record)
    tool.description = _REVIEW_DESCRIPTION.replace(
        "your selected model", f"the saved reviewer model {models['read_only']}"
    )
    writer = BuildTeamTool(
        review_tool=tool,
        run_child=run_child,
        record_event=record,
        parent=registry,
        config=config,
        deadline=deadline,
        can_write=can_write,
        protected_paths=protected_paths,
        read_subset=review_tools,
        scope=scope,
    )
    writer.description = writer.description.replace(
        "using your selected model",
        f"using the saved builder model {models['builder']} (review model {models['read_only']})",
    )
    registry.register(writer)
    if can_write and getattr(registry, "policy", None) is None:
        scheduler = BuildTeamScheduler(
            writer,
            project=config.tools.sandbox_path,
            model=models["builder"],
            provider=admission_key(configs["builder"]),
            emit=emit,
            deadline=deadline,
            resolve_model=resolve_builder,
        )
        scheduler.description = scheduler.description.replace(
            "the selected model", f"the saved builder model {models['builder']}"
        )
        if normalize_level(getattr(model_config, "reasoning_effort", "")) == "max":
            scheduler.description += _MAX_SPLIT_INSTRUCTIONS
        registry.register(scheduler)
    else:
        scheduler = None
    if control is not None:

        def shift_deadline(held_s: float) -> None:
            # A paused stretch is given back: helpers and team calls started after it keep the time they had.
            nonlocal deadline
            deadline += held_s
            writer._deadline += held_s
            if scheduler is not None:
                scheduler._deadline += held_s

        control.clock.add_shift(shift_deadline)
    return deadline
