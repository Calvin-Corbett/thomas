"""GPT/AgentLoop in-process dispatch — the ChatGPT-OAuth brain twin of dispatch_claude_cli."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .bridge_config import emergency_stop_active, emergency_stop_path
from .bridge_prompts import compose_headless_prompt
from .build_verify import _verify_and_iterate
from .dispatch_claude_cli import CliDispatchResult, _is_action_refusal, _is_conversational_reply
from .forge_event_stream import (
    FORGE_EVENT_KEY,
    _StreamState,
    _summarize_tool_input,
    _thinking_to_events,
)

# The honest message shown when the GPT brain is selected but the user's ChatGPT
# subscription is not connected. NEVER a silent fallback to another brain, never
# raw OAuth/MCP error spew — just a clear, actionable instruction.
CHATGPT_NOT_CONNECTED_MSG = "ChatGPT isn't connected — connect it in Easy Setup to use GPT"

# The in-process GPT brain runs through Thomas's OWN ChatGPT-OAuth provider
# (``openai_codex``), NOT the codex CLI. This profile resolves to
# ``ModelConfig(provider="openai_codex")``, which LLMClient streams via the user's
# ChatGPT login token (subscription-only — never the paid OPENAI_API_KEY).
OPENAI_CODEX_PROFILE = "openai_codex"


def chatgpt_oauth_connected() -> bool:
    """Fail closed when a frontend has not injected its trusted OAuth check.

    Forge is deliberately independent of the HTTP server and its secret store.
    Server and CLI entry points that can safely inspect owner credentials pass a
    ``token_check`` callback to :func:`dispatch_via_agent_loop`; direct library
    callers must do the same for a live run. Preview calls need no credential.
    """
    return False


def _summarize_agent_event_tool(name: str, args: Any) -> str:
    """Compact summary for an AgentLoop tool call (reuses the tool-input summarizer)."""
    summary = _summarize_tool_input(args if isinstance(args, dict) else {})
    return summary or str(name or "tool")


class _AgentLoopForgeTranslator:
    """Map Thomas's own ``AgentEvent`` stream (the GPT in-process loop) onto the
    SAME forge events the claude stream-json path emits — including the mid-task
    insight + collapsed reasoning beat, via the SAME shared gate.

    This is the GPT twin of ``ClaudeStreamTranslator``. Both engines carry a
    per-run ``_StreamState`` and funnel reasoning through ``_thinking_to_events``,
    so a user who picks GPT sees the IDENTICAL genuine post-observation insight
    cards (deduped, enumeration-stripped, honest) a claude run shows — never zero.

    Two stream-shape differences from the claude path are absorbed here:

      * ``THINKING`` arrives as token DELTAS, not whole blocks, so reasoning is
        ACCUMULATED in ``_think_buf`` and flushed as ONE block at the next
        boundary (a tool, an error, or done).
      * the flush happens BEFORE a tool flips ``seen_observation``: reasoning that
        precedes the run's first observation is the plan (gated to NO card, only
        its collapsed ``reason``); reasoning that follows an observation is
        insight-eligible — exactly the claude positional rule.

    ``rc`` is set to 1 on an agent error and ``final_text`` holds the loop's final
    message, so the async driver keeps returning the genuine ``(rc, final_text)``.
    """

    def __init__(self, emit: Callable[[dict[str, Any]], None]) -> None:
        from thomas.core.events import EventType

        self._emit = emit
        self._ET = EventType
        self._state = _StreamState()
        self._say_buf: list[str] = []
        self._think_buf: list[str] = []
        # True once we've forwarded token-progressive ``say`` deltas for the current
        # prose run, so the boundary flush does NOT re-emit the same text as a block.
        self._streamed_say = False
        self.rc = 0
        self.final_text = ""

    def _flush_say(self) -> None:
        # If the prose was already streamed token-by-token (the live path), the
        # deltas ARE the message — just drop the accumulator and re-arm for the next
        # block. Only the non-streaming fallback emits the buffered text as one block.
        if self._streamed_say:
            self._say_buf.clear()
            self._streamed_say = False
            return
        text = "".join(self._say_buf).strip()
        self._say_buf.clear()
        if text:
            self._emit({FORGE_EVENT_KEY: "say", "text": text})

    def _flush_think(self) -> None:
        # The reasoning accumulated since the last boundary is ONE block: distil its
        # insight (gated) and emit the collapsed reason via the SHARED helper. Flush
        # BEFORE a tool flips the observation gate so pre-observation reasoning stays
        # plan (no card) and post-observation reasoning is insight-eligible.
        text = "".join(self._think_buf).strip()
        self._think_buf.clear()
        for ev in _thinking_to_events(text, self._state):
            self._emit(ev)

    def feed(self, et: str, data: dict[str, Any] | None) -> None:
        """Translate one AgentLoop event, emitting forge events as a side effect."""
        ET = self._ET
        data = data or {}
        if et == ET.TEXT_DELTA.value:
            # Forward each token PROMPTLY as a progressive ``say`` delta (RAW — no
            # strip, so inter-token spaces survive). The accumulator is still kept
            # so the boundary flush knows prose was streamed (must not re-emit as block).
            piece = str(data.get("text") or "")
            if piece:
                self._say_buf.append(piece)
                self._streamed_say = True
                self._emit({FORGE_EVENT_KEY: "say", "text": piece, "delta": True})
        elif et == ET.THINKING.value:
            # Accumulate reasoning deltas; they flush as one block at the next
            # boundary so the shared insight/reason rule sees a whole thought.
            self._think_buf.append(str(data.get("text") or ""))
        elif et == ET.TOOL_START.value:
            # Reasoning BEFORE the tool is flushed (and gated) FIRST, then the tool
            # marks the run as having OBSERVED so later reasoning can surface.
            self._flush_think()
            self._flush_say()
            self._emit(
                {
                    FORGE_EVENT_KEY: "tool",
                    "name": str(data.get("tool_name") or "tool"),
                    "text": _summarize_agent_event_tool(data.get("tool_name"), data.get("args")),
                }
            )
            self._state.seen_observation = True
        elif et == ET.TOOL_RESULT.value:
            self._emit(
                {
                    FORGE_EVENT_KEY: "tool_result",
                    "text": str(data.get("result") or "")[:500],
                    "is_error": not bool(data.get("ok", True)),
                }
            )
            # A tool RESULT is the clearest observation — following reasoning is
            # insight-eligible, mirroring the claude ``tool_result`` branch.
            self._state.seen_observation = True
        elif et == ET.AGENT_ERROR.value:
            self._flush_think()
            self._flush_say()
            self.rc = 1
            self._emit({FORGE_EVENT_KEY: "error", "text": str(data.get("error") or "agent loop reported an error")})
        elif et == ET.AGENT_DONE.value:
            self._flush_think()
            self.final_text = str(data.get("text") or "")
            if self._say_buf:
                self._flush_say()
            if self.final_text:
                self._emit({FORGE_EVENT_KEY: "final", "text": self.final_text})

    def close(self) -> None:
        """Drain any trailing reasoning/say buffered when the stream ends."""
        self._flush_think()
        self._flush_say()


async def _translate_agent_stream(
    agent: Any,
    prompt: str,
    *,
    intent_text: str | None = None,
    timeout: float,
    tools_policy: str,
    token_economy: str = "optimal",
    translator: _AgentLoopForgeTranslator,
) -> None:
    """Translate one agent run while enforcing its advertised wall-clock limit."""
    import asyncio

    from thomas.core.events import EventType

    try:
        async with asyncio.timeout(max(0.01, float(timeout))):
            async for event in agent.run(
                prompt,
                intent_text=intent_text,
                mode="auto",
                tools_policy=tools_policy,
                token_economy=token_economy,
                job_type="coding",
            ):
                translator.feed(getattr(event.type, "value", ""), event.data)
    except TimeoutError:
        translator.feed(
            EventType.AGENT_ERROR.value,
            {"error": f"Agent run exceeded the {int(timeout)}-second execution limit."},
        )


def _run_agent_loop_pass(
    prompt: str,
    cwd: str,
    timeout: int,
    emit: Callable[[dict[str, Any]], None],
    *,
    intent_text: str | None = None,
    profile: str = OPENAI_CODEX_PROFILE,
    allow_shell: bool = False,
    file_access: str = "project",
    guardrails: str = "guarded",
    autonomy_level: int = 3,
    token_economy: str = "optimal",
    oauth_access_token: str = "",
) -> tuple[int, str]:
    """Run ONE in-process AgentLoop edit pass on the ``openai_codex`` provider.

    Builds an edit-only toolset (filesystem + diff + code-search; NO shell/git/
    network), constructs the loop over the ChatGPT-OAuth model profile, runs it,
    and maps each ``AgentEvent`` to the SAME forge events the claude path emits.
    Returns ``(rc, final_text)`` where ``rc`` is non-zero iff the loop raised or
    surfaced an agent error.

    The loop is async; this sync wrapper drives it in its own event loop so it
    composes cleanly with the engine's synchronous verify step.
    """
    import asyncio

    return asyncio.run(
        _agent_loop_pass_async(
            prompt,
            cwd,
            timeout,
            emit,
            intent_text=intent_text,
            profile=profile,
            allow_shell=allow_shell,
            file_access=file_access,
            guardrails=guardrails,
            autonomy_level=autonomy_level,
            token_economy=token_economy,
            oauth_access_token=oauth_access_token,
        )
    )


async def _agent_loop_pass_async(
    prompt: str,
    cwd: str,
    timeout: int,
    emit: Callable[[dict[str, Any]], None],
    *,
    intent_text: str | None = None,
    profile: str = OPENAI_CODEX_PROFILE,
    allow_shell: bool = False,
    file_access: str = "project",
    guardrails: str = "guarded",
    autonomy_level: int = 3,
    token_economy: str = "optimal",
    oauth_access_token: str = "",
) -> tuple[int, str]:
    from thomas.agent.loop import AgentLoop
    from thomas.core.config import load_config
    from thomas.core.file_access import parse_file_access_level
    from thomas.core.llm_client import LLMClient
    from thomas.tools.code_search import register_code_search_tools
    from thomas.tools.diff import register_diff_tools
    from thomas.tools.filesystem import register_filesystem_tools
    from thomas.tools.registry import ToolRegistry
    from thomas.tools.shell import register_shell_tools

    config = load_config(Path(cwd) / "thomas.toml")
    # Edits must land in the dispatched repo, and ONLY there — confine the
    # toolset's sandbox to cwd and keep shell OFF (edit-only, like SAFE_CLI_TOOLS).
    config.tools.sandbox_root = str(cwd)
    config.tools.allow_shell = bool(allow_shell)
    config.tools.file_access = parse_file_access_level(file_access)
    model_cfg = config.get_model(profile)
    if oauth_access_token:
        model_cfg.api_key = oauth_access_token
    llm = LLMClient(model_cfg, fallback_configs=[], failover_enabled=False)

    sandbox = config.tools.sandbox_path
    tools = ToolRegistry()
    register_filesystem_tools(
        tools,
        sandbox,
        config.tools.max_file_size,
        file_access=config.tools.file_access,
        project_root=Path(cwd),
        home_dir=Path.home(),
    )
    register_diff_tools(tools, sandbox)
    register_code_search_tools(tools, sandbox)
    if allow_shell:
        register_shell_tools(tools, sandbox, config.tools.shell_timeout, allowed=True)

    guardrail_mode = str(guardrails or "guarded").strip().lower()
    max_parallel_tools = {"open": 6, "guarded": 3, "fortress": 1}.get(guardrail_mode, 3)
    agent = AgentLoop(
        config,
        llm,
        tools,
        conversation=[],
        memory=None,
        autonomy_level=autonomy_level,
        max_parallel_tools=max_parallel_tools,
    )

    # ONE translator carries the per-run insight gate + buffers and maps each
    # AgentEvent to the SAME forge events the claude path emits — INCLUDING the
    # THINKING -> insight + collapsed reasoning beat (engine parity), via the same
    # shared ``_thinking_to_events`` rule.
    translator = _AgentLoopForgeTranslator(emit)
    try:
        tools_policy = "always" if guardrail_mode == "open" else "auto"
        await _translate_agent_stream(
            agent,
            prompt,
            intent_text=intent_text,
            timeout=timeout,
            tools_policy=tools_policy,
            token_economy=token_economy,
            translator=translator,
        )
    finally:
        translator.close()
        await llm.close()
    return translator.rc, translator.final_text


def dispatch_via_agent_loop(
    goal: str,
    *,
    cwd: str | Path,
    definition: str = "",
    plan: str = "",
    branch_only: bool = True,
    profile: str = OPENAI_CODEX_PROFILE,
    timeout: int = 900,
    dry_run: bool = True,
    runner: Any = None,
    emit: Callable[[dict[str, Any]], None] | None = None,
    verify: bool = True,
    verifier: Any = None,
    max_fix_iters: int = 2,
    history: Any = None,
    token_check: Any = None,
    allow_shell: bool = False,
    file_access: str = "project",
    guardrails: str = "guarded",
    autonomy_level: int = 3,
    token_economy: str = "optimal",
    oauth_access_token: str = "",
) -> CliDispatchResult:
    """Dispatch a build to the GPT brain IN-PROCESS via Thomas's own AgentLoop.

    The GPT twin of ``dispatch_via_claude_cli`` — same contract, same kill switch,
    same engine verify loop, same forge-event stream — but it NEVER shells out to
    the codex CLI. It drives Thomas's own ``AgentLoop`` over the ``openai_codex``
    provider (GPT via the user's ChatGPT OAuth token), with an edit-only toolset.

    If ChatGPT is not connected, it returns the honest connect-ChatGPT failure
    (``CHATGPT_NOT_CONNECTED_MSG``) — never a silent fallback, never raw OAuth/MCP
    spew. ``dry_run`` (the default) returns the composed prompt without running.

    It is a reason→edit→verify LOOP: after the loop's edit pass, the ENGINE
    (``verify=True``) runs the SAME real verification subprocess the claude path
    uses over the files THIS run changed and, on failure, feeds the failure back
    for up to ``max_fix_iters`` more passes.

    ``runner`` is injectable for tests: a callable ``(prompt, cwd, timeout, emit)
    -> (rc:int, text:str)`` that stands in for the in-process loop pass.
    ``token_economy`` controls the bounded AgentLoop pass count.
    ``token_check`` is injectable too (``() -> bool``). Live entry points must
    inject a trusted check; absent one, this library layer fails closed.
    """
    from .forge_event_stream import _default_emit

    prompt = compose_headless_prompt(
        goal,
        definition=definition,
        plan=plan,
        history=history,
        file_access=file_access,
        guardrails=guardrails,
        autonomy_level=autonomy_level,
    )
    if dry_run:
        return CliDispatchResult(False, "dry-run (agent loop not invoked)", prompt)

    # The kill switch guards EVERY live dispatch path.
    if emergency_stop_active():
        return CliDispatchResult(False, f"refused: emergency stop active ({emergency_stop_path()})", prompt)

    # Honest, fail-closed gate: no ChatGPT token => no GPT build. Never fall back
    # to another brain or leak OAuth internals — just tell the user to connect it.
    is_connected = token_check if token_check is not None else chatgpt_oauth_connected
    if not is_connected():
        return CliDispatchResult(False, CHATGPT_NOT_CONNECTED_MSG, prompt)

    emit_sink = emit or _default_emit
    saw_reply = False
    saw_refusal = False
    saw_tool_activity = False

    def emit_event(event: dict[str, Any]) -> None:
        nonlocal saw_reply, saw_refusal, saw_tool_activity
        kind = str(event.get(FORGE_EVENT_KEY) or "")
        if kind in {"final", "say"}:
            reply_text = str(event.get("text") or "")
            if _is_conversational_reply(reply_text):
                saw_reply = True
            if _is_action_refusal(reply_text):
                saw_refusal = True
        elif kind in {"tool", "tool_result"}:
            saw_tool_activity = True
        emit_sink(event)

    def _run_pass(p: str) -> tuple[int, str]:
        if runner is not None:
            return runner(p, str(cwd), timeout, emit_event)
        return _run_agent_loop_pass(
            p,
            str(cwd),
            timeout,
            emit_event,
            intent_text=goal,
            profile=profile,
            allow_shell=allow_shell,
            file_access=file_access,
            guardrails=guardrails,
            autonomy_level=autonomy_level,
            token_economy=token_economy,
            oauth_access_token=oauth_access_token,
        )

    from thomas.forge.anvil import forge_code_git

    verify_failed = False
    try:
        snap_before = forge_code_git.snapshot(cwd)
        rc, out = _run_pass(prompt)
        # The RUN/TEST step: only verify a clean edit pass. The engine — ordinary
        # in-process Python — owns the real check regardless of the brain.
        if verify and rc == 0:
            vrc = _verify_and_iterate(
                cwd, snap_before, emit_event, _run_pass, goal, verifier=verifier, max_fix_iters=max_fix_iters
            )
            if vrc != 0:
                rc, verify_failed = vrc, True
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        return CliDispatchResult(False, f"refused: agent loop run failed: {exc}", prompt)

    changed = forge_code_git.project_delta_since(cwd, snap_before)
    action_refused = saw_refusal
    conversation_reply = rc == 0 and not changed and saw_reply and not saw_tool_activity and not action_refused
    if rc != 0:
        reason = f"verification failed (exit {rc}) after fix attempts" if verify_failed else f"agent loop exited {rc}"
    elif action_refused:
        detail = " after leaving partial file changes" if changed else ""
        reason = f"GPT could not complete the requested action{detail}"
    elif not changed:
        if conversation_reply:
            reason = "GPT replied without changing files"
        else:
            reason = "GPT ran but made NO repo changes (no-op) — nothing to review"
    else:
        reason = f"dispatched via GPT (ChatGPT OAuth, in-process; {len(changed)} file(s) changed; engine checks passed)"
    return CliDispatchResult(
        ok=(rc == 0 and not action_refused and (bool(changed) or conversation_reply)),
        reason=reason,
        prompt=prompt,
        returncode=rc,
        changed_files=changed,
        stdout_tail=str(out)[-2000:],
    )
