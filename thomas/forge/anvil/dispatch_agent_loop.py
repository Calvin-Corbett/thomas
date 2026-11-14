"""GPT/AgentLoop in-process dispatch — the ChatGPT-OAuth brain twin of dispatch_claude_cli."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from thomas.agent.tool_failures import ToolFailures

from . import run_control
from .bridge_config import emergency_stop_active, emergency_stop_path
from .bridge_prompts import compose_headless_prompt, pin_your_messages
from .build_agent_team import register_build_team
from .build_lead_tools import lead_tools as build_lead_tools
from .build_verify import PASS_WALL_CLOCK_RC, RELOAD_YIELD_RC, _verify_and_iterate
from .dispatch_agent_loop_translator import (  # noqa: F401 - the names tests and callers import from here
    _acceptance_event,
    _AgentLoopForgeTranslator,
    _summarize_agent_event_tool,
)
from .dispatch_agent_summary import _acceptance_summary, _judge_checks_summary  # noqa: F401 - re-exported for tests
from .dispatch_claude_cli import CliDispatchResult, _is_action_refusal, _is_conversational_reply
from .forge_code_settings import live_edit_allowed
from .forge_event_stream import (
    FORGE_EVENT_KEY,
)

log = logging.getLogger(__name__)

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


def _contract_level_for_build(build_effort: str) -> str:
    """The verification depth a Build pass runs its acceptance contract at.

    It follows the Build's own reasoning effort, and never drops below the first
    level with a separate judge. Below that, a judged requirement ("at least 4
    distinct race tracks") is nobody's to check: the verdict counts only checked
    items, so it read "met" with nine features unchecked, and a one-track demo
    was filed as done. Only the contract reads this value -- the worker model's
    own effort comes from its profile and is not raised here.
    """
    from thomas.agent.verification_contract import LEVELS, normalize_level

    level = normalize_level(build_effort)
    floor = "xhigh"
    return level if LEVELS.index(level) >= LEVELS.index(floor) else floor


def _clock_contract(cwd: str | Path | None = None) -> dict[str, Any]:
    """The settlement of a pass that ended at its wall clock: not finished, by
    construction. It stands in only until a pass that ran to its own end settles.
    The saved playtest sessions ride in the detail: pass 2 of a proof run replayed
    what pass 1 had proven and hit the clock again, because "continue where you
    left off" said nothing about what was already on record."""
    detail = "continue exactly where it left off; do not start over"
    if cwd is not None:
        from thomas.agent.acceptance_evaluator import _session_index_line
        from thomas.tools.web_playtest import recent_reports

        saved = recent_reports(Path(cwd), limit=20)
        if saved:
            detail += "; playtest sessions already on record (do not replay them): " + " | ".join(
                _session_index_line(r) for r in saved
            )
    return {
        "active": True,
        "verdict": {"met": False, "unmet": ["pass:wall-clock"], "unchecked": []},
        "items": [
            {
                "item_id": "pass:wall-clock",
                "kind": "requirement",
                "description": "The previous pass stopped at its wall clock before it declared the work finished.",
                "checked": True,
                "satisfied": False,
                "detail": detail,
            }
        ],
    }


def _pass_contract(cwd: str | Path, pass_state: dict[str, Any], sink: dict[str, Any]) -> dict[str, Any] | None:
    """The settlement the engine reads after a pass: an early ending, the wall clock, or the loop's own."""
    from .pass_endings import ending_contract

    if pass_state.get("ending") is not None:
        return ending_contract(pass_state["ending"])
    if pass_state.get("clock"):
        return _clock_contract(cwd)
    return sink.get("acceptance")


def _decide_first_ending(ending: Any, emit_event: Any, pass_state: dict[str, Any]) -> int:
    """0 to verify what the first pass left and go on; 1 when the Build stops here, with the reason recorded."""
    from .pass_endings import ASK, CONTINUE

    if ending.decision == CONTINUE:
        emit_event(
            {FORGE_EVENT_KEY: "meta", "text": f"the pass ended early because {ending.label}; verifying and continuing"}
        )
        return 0
    if ending.decision == ASK:
        text = f"needs you: the pass stopped because {ending.label}: {ending.text[:300]}"
    else:
        text = f"stopped: {ending.label}: {ending.text[:300]}"
    emit_event({FORGE_EVENT_KEY: "error", "text": text})
    pass_state["outcome"] = text
    return 1


async def _translate_agent_stream(
    agent: Any,
    prompt: str,
    *,
    intent_text: str | None = None,
    timeout: float,
    tools_policy: str,
    token_economy: str = "optimal",
    translator: _AgentLoopForgeTranslator,
    clock: run_control.PassClock | None = None,
) -> None:
    """Translate one agent run while enforcing its advertised wall-clock limit.

    ``clock``, on a Build run with controls, stops that limit while the run is held (paused by you, or waiting for
    your answer), so a pause never spends the pass's time."""
    import asyncio

    try:
        async with asyncio.timeout(max(0.01, float(timeout))) as pass_timeout:
            if clock is not None:
                clock.bind(pass_timeout)
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
        # The clock bounds a PASS, not the task. The engine decides what the
        # files it left behind are worth: verified and continued when something
        # changed, a failure only when nothing did.
        translator.close()
        translator.rc = PASS_WALL_CLOCK_RC
        translator._emit(
            {
                FORGE_EVENT_KEY: "meta",
                "text": f"pass wall clock ({int(timeout)} s) reached; the engine verifies what changed and continues",
            }
        )
    finally:
        if clock is not None:
            clock.unbind()


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
    acceptance_sink: dict[str, Any] | None = None,
    protected_paths: list[str] | None = None,
    scope: Any = None,
    control: run_control.RunControl | None = None,
    lead_tools: list[Any] | None = None,
) -> tuple[int, str]:
    """Run ONE in-process AgentLoop edit pass on the ``openai_codex`` provider.

    ``scope``, a files-slot ``Scope``, replaces ``cwd`` as the root the tools may reach; ``None`` keeps ``cwd``.

    ``acceptance_sink``, when given, receives the pass's acceptance settlement
    under ``"acceptance"`` so the engine can decide whether the work is done.

    Builds the pass toolset (filesystem + diff + code-search; ``check.run`` for
    tests, ruff and read-only git when the run may edit; ``shell.exec`` only
    when ``allow_shell``), constructs the loop over the ChatGPT-OAuth model
    profile, runs it, and maps each ``AgentEvent`` to the SAME forge events the claude path emits.
    Returns ``(rc, final_text)`` where ``rc`` is non-zero iff the loop raised or
    surfaced an agent error.

    The loop is async; this sync wrapper drives it in its own event loop so it
    composes cleanly with the engine's synchronous verify step.

    ``control`` and ``lead_tools`` come from a run the server launched with a
    control folder (``run_control``): the lead then holds when you pause, reads
    your messages, and has ``plan.update`` and ``ask.user``. Without them the
    pass is exactly what it was.
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
            acceptance_sink=acceptance_sink,
            protected_paths=protected_paths,
            scope=scope,
            control=control,
            lead_tools=lead_tools,
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
    acceptance_sink: dict[str, Any] | None = None,
    protected_paths: list[str] | None = None,
    scope: Any = None,
    control: run_control.RunControl | None = None,
    lead_tools: list[Any] | None = None,
) -> tuple[int, str]:
    from thomas.agent.kernel_wiring import build_agent_loop, resolve_tools_for_turn
    from thomas.agent.loop import AgentLoop
    from thomas.core.config import load_config
    from thomas.core.file_access import parse_file_access_level
    from thomas.core.llm_request_admission import admission_key, shared_provider_admission
    from thomas.core.llm_slot import models
    from thomas.tools.check_run import register_check_run_tool
    from thomas.tools.code_search import register_code_search_tools
    from thomas.tools.diff import register_diff_tools
    from thomas.tools.filesystem import register_filesystem_tools
    from thomas.tools.goals import register_goal_tools
    from thomas.tools.image_generation import register_image_generation_tools
    from thomas.tools.registry import ToolRegistry
    from thomas.tools.shell import register_shell_tools
    from thomas.tools.web_playtest import register_web_playtest_tool

    config = load_config(Path(cwd) / "thomas.toml")
    # Edits must land in the dispatched repo, and ONLY there — confine the
    # toolset's sandbox to cwd and keep shell OFF (edit-only, like SAFE_CLI_TOOLS).
    config.tools.sandbox_root = str(cwd if scope is None else scope.root)
    config.tools.allow_shell = bool(allow_shell)
    config.tools.file_access = parse_file_access_level(file_access)
    model_cfg = config.get_model(profile)
    if oauth_access_token:
        model_cfg.api_key = oauth_access_token
    lead_admission = shared_provider_admission(
        admission_key(model_cfg), team=f"build-lead:{id(emit)}", lane="interactive"
    )
    llm = models().open(model_cfg, fallback_configs=[], failover_enabled=False, request_admission=lead_admission)

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
    # The builder can play what it writes: a scripted, offline browser session
    # against the project (thomas.tools.web_playtest). Without it the worker
    # wrote "this workspace gave me no browser-control tool" and was right.
    register_web_playtest_tool(tools, Path(cwd))
    # Standing goals for the project: the contract holds every turn to them.
    register_goal_tools(tools, Path(cwd))
    # Image generation: keys come from config profiles / env here (the forge
    # layer must not import the server SecretStore); Settings-saved keys reach
    # the chat/worker path via app_helpers._build_tools.
    register_image_generation_tools(tools, config, Path(cwd))
    # A run that may edit can run the project's tests, ruff and read-only git,
    # at every guardrail: check.run runs that closed list and nothing else.
    # Without it the builder, asked to run pytest, said truthfully it could not.
    if live_edit_allowed(autonomy_level=autonomy_level, file_access=file_access):
        register_check_run_tool(tools, Path(cwd))
    if allow_shell:
        register_shell_tools(tools, sandbox, config.tools.shell_timeout, allowed=True)
    # plan.update and ask.user: the same instances every pass, so the plan keeps its step times.
    for lead_tool in lead_tools or ():
        tools.register(lead_tool)
    # Each pass gets its own clock: it stops this pass's limit and moves its deadlines while the run is held.
    clock = control.new_pass_clock() if control is not None else None

    guardrail_mode = str(guardrails or "guarded").strip().lower()
    max_parallel_tools = {"open": 6, "guarded": 3, "fortress": 1}.get(guardrail_mode, 3)
    tools_policy = "always" if guardrail_mode == "open" else "auto"
    team_deadline = register_build_team(
        tools,
        config=config,
        model_config=model_cfg,
        emit=emit,
        timeout=timeout,
        autonomy_level=autonomy_level,
        tools_policy=tools_policy,
        token_economy=token_economy,
        protected_paths=list(protected_paths or []),
        can_write=live_edit_allowed(autonomy_level=autonomy_level, file_access=file_access),
        scope=scope,
        control=control,
    )
    from .run_channel_tools import register_run_channel_tools

    register_run_channel_tools(tools, emit)
    # Only edit-capable Build turns opt in to mounted additions. Keep the
    # read-only and low-autonomy tool boundaries unchanged.
    if live_edit_allowed(autonomy_level=autonomy_level, file_access=file_access):
        tools = resolve_tools_for_turn(tools, allow_new=True)
    agent = build_agent_loop(
        config,
        llm,
        tools,
        conversation=[],
        memory=None,
        autonomy_level=autonomy_level,
        max_parallel_tools=max_parallel_tools,
        default=AgentLoop,
    )
    # Delegation owns the same bounded pass clock; ordinary tools keep their cap.
    agent._tool_deadlines = {"task.spawn": team_deadline, "task.team": team_deadline}
    if control is not None and clock is not None:
        # You can pause the lead, and it reads your messages between steps (run_control). ask.user waits up to 20
        # minutes for you, past the 10-minute cap an ordinary tool gets, so it gets its own deadline. Each is a
        # HeldDeadline: a pause moves it out while it lasts, for a call already waiting as for the next one.
        agent.run_hold = control.hold
        agent._message_queue = control.inbox(run_control.LEAD)
        # The context meter's Compact button: the loop asks this before each step and compacts when it says True.
        # The context meter's two controls, asked before each step: Compact now (once per click) and the window you
        # chose with the slider. The profile's own window is kept so the panel can say what the default is.
        agent.profile_context_window = int(getattr(agent, "_context_window", 0) or 0)
        agent.run_directives_probe = lambda: (
            run_control.take_compaction_request(control.directory),
            run_control.read_context_cap(control.directory),
        )
        agent._tool_deadlines = {
            "task.spawn": run_control.HeldDeadline(team_deadline, clock),
            "task.team": run_control.HeldDeadline(team_deadline, clock),
            "ask.user": run_control.HeldDeadline(team_deadline + run_control.ASK_WAIT_S + 60, clock),
        }
        # What you told the lead in an earlier pass is gone from this pass's empty conversation: it rides the prompt.
        prompt = pin_your_messages(prompt, control.taken_texts(run_control.LEAD))
    # The acceptance contract's depth: the Build's effort, floored at the level
    # with a separate judge. The contract reads the worker model's own effort
    # (`loop.llm.config.reasoning_effort`) unless this attribute is set, so a
    # Build can verify deeper without paying for a deeper worker.
    # The run's file fence: paths the brief or another agent's claim holds. Enforced
    # by the write tools (loop_tool_paths), not left to the prose.
    agent.protected_paths = [str(p) for p in (protected_paths or []) if str(p).strip()]
    agent.scope = scope
    agent.verification_effort = _contract_level_for_build(str(getattr(model_cfg, "reasoning_effort", "") or ""))

    # ONE translator carries the per-run insight gate + buffers and maps each
    # AgentEvent to the SAME forge events the claude path emits — INCLUDING the
    # THINKING -> insight + collapsed reasoning beat (engine parity), via the same
    # shared ``_thinking_to_events`` rule.
    translator = _AgentLoopForgeTranslator(emit)
    if control is not None:
        translator.context_sink = lambda tokens, window, breakdown=None: run_control.write_context(
            control.directory, tokens, window, breakdown, getattr(agent, "profile_context_window", None)
        )
        translator.usage_sink = lambda prompt, completion, total, seconds: run_control.add_usage(
            control.directory, prompt, completion, total, seconds
        )
        translator.first_output_sink = lambda seconds: run_control.write_first_output(control.directory, seconds)
    # The team scheduler hands its deadline on as a plain number; its wait finds this pass's clock here.
    clock_token = run_control.bind_pass_clock(clock)
    try:
        await _translate_agent_stream(
            agent,
            prompt,
            intent_text=intent_text,
            timeout=timeout,
            tools_policy=tools_policy,
            token_economy=token_economy,
            translator=translator,
            clock=clock,
        )
    finally:
        run_control.unbind_pass_clock(clock_token)
        translator.close()
        try:
            await llm.close()
        finally:
            lead_admission.close()
    if acceptance_sink is not None:
        acceptance_sink["acceptance"] = translator.acceptance
        acceptance_sink["yielded_for_reload"] = translator.yielded_for_reload
        acceptance_sink["ending"] = translator.ending if translator.rc == 1 else None
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
    protected_paths: list[str] | None = None,
    token_economy: str = "optimal",
    oauth_access_token: str = "",
    allow_without_history: bool = False,
    not_connected_msg: str = CHATGPT_NOT_CONNECTED_MSG,
) -> CliDispatchResult:
    """Dispatch a build to the GPT brain IN-PROCESS via Thomas's own AgentLoop.

    The same loop runs Claude when ``profile`` is an Anthropic profile with a key
    (``thomas/forge/anvil/agent_passes.py``); ``not_connected_msg`` is then the
    sentence naming that way in, since "connect ChatGPT" would point at the wrong
    account.

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
        project_root=cwd,
        check_run_available=live_edit_allowed(autonomy_level=autonomy_level, file_access=file_access),
        timeout=timeout,
        lead_tools_available=run_control.configured(),
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
        return CliDispatchResult(False, not_connected_msg, prompt)

    emit_sink = emit or _default_emit
    saw_reply = False
    saw_refusal = False
    tool_verdict = ToolFailures()

    def emit_event(event: dict[str, Any]) -> None:
        nonlocal saw_reply, saw_refusal
        if event.get("agent_id"):
            # Helpers' capability limits and partial findings are not the lead's
            # answer. The task.spawn result still reports success/failure to it.
            emit_sink(event)
            return
        kind = str(event.get(FORGE_EVENT_KEY) or "")
        if kind in {"final", "say"}:
            reply_text = str(event.get("text") or "")
            if _is_conversational_reply(reply_text):
                saw_reply = True
            if _is_action_refusal(reply_text):
                saw_refusal = True
        tool_verdict.observe(event)
        emit_sink(event)

    # A shell can write anywhere, so a fence and a shell cannot coexist honestly:
    # a fenced run stays edit-only, and the stream says why.
    fenced = [str(x) for x in (protected_paths or []) if str(x).strip()]
    if fenced and allow_shell:
        allow_shell = False
        emit_event(
            {
                "type": "output",
                "kind": "status",
                "text": "shell disabled for this run: it is fenced off from "
                + ", ".join(fenced[:6])
                + (" and more" if len(fenced) > 6 else "")
                + "; a shell could write anywhere, so the fence keeps this run edit-only.",
            }
        )

    # Pause, your messages and the lead's questions, when the server gave this run a control folder
    # (run_control). Without one -- the CLI, an older server, a test -- the run is exactly what it was.
    control = run_control.RunControl.from_env(emit_event)
    lead_tools = build_lead_tools(control, emit_event) if control is not None else None

    # The last pass's acceptance settlement, read by the engine after each pass.
    # An injected ``runner`` (tests) never fills it, so the engine sees no contract.
    acceptance_sink: dict[str, Any] = {}
    pass_state: dict[str, Any] = {"clock": False, "ending": None, "outcome": ""}

    def _run_pass(p: str) -> tuple[int, str]:
        acceptance_sink.pop("ending", None)
        rc_out = _run_pass_inner(p)
        pass_state["clock"] = rc_out[0] == PASS_WALL_CLOCK_RC
        pass_state["ending"] = acceptance_sink.get("ending") if rc_out[0] == 1 else None
        if acceptance_sink.get("yielded_for_reload"):
            return RELOAD_YIELD_RC, rc_out[1]
        return rc_out

    def _run_pass_inner(p: str) -> tuple[int, str]:
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
            acceptance_sink=acceptance_sink,
            protected_paths=list(protected_paths or []),
            control=control,
            lead_tools=lead_tools,
        )

    from thomas.forge.anvil import forge_code_git

    verify_failed = False
    yielded_for_reload = False
    if control is not None:
        # The lead takes messages for the whole run, its passes and the checks between them: a message that
        # arrives between passes is read by the next one, or reads undelivered if no pass follows.
        control.listen(run_control.LEAD, "Thomas")
    try:
        # The open-time choice to work without history arrives as an argument, never inferred.
        snap_before = forge_code_git.snapshot(cwd, allow_without_history=allow_without_history)
        rc, out = _run_pass(prompt)
        yielded_for_reload = bool(acceptance_sink.get("yielded_for_reload"))
        if yielded_for_reload:
            emit_event({FORGE_EVENT_KEY: "meta", "text": "Build paused for landed-code reload"})
        if (
            rc == PASS_WALL_CLOCK_RC
            and verify
            and (forge_code_git.project_delta_since(cwd, snap_before) or tool_verdict.saw_tool)
        ):
            # The clock ended a pass that was working: a pass boundary, not a
            # verdict. Files on disk are one kind of work; a pass that only
            # played and proved (the Minecraft proof run: eight sessions, no
            # file to change) is another. Only a pass that did nothing fails.
            what = "files changed" if forge_code_git.project_delta_since(cwd, snap_before) else "the pass was working"
            emit_event({FORGE_EVENT_KEY: "meta", "text": f"{what} before the wall clock; verifying and continuing"})
            rc = 0
        first_ending = pass_state["ending"]
        if verify and rc == 1 and first_ending is not None and not yielded_for_reload:
            # A pass that ended early is a decision, not the end of the Build (pass_endings).
            rc = _decide_first_ending(first_ending, emit_event, pass_state)
        # The RUN/TEST step: only verify a clean edit pass. The engine — ordinary
        # in-process Python — owns the real check regardless of the brain.
        if verify and rc == 0 and not yielded_for_reload:
            vrc = _verify_and_iterate(
                cwd,
                snap_before,
                emit_event,
                _run_pass,
                goal,
                verifier=verifier,
                max_fix_iters=max_fix_iters,
                contract=lambda: _pass_contract(cwd, pass_state, acceptance_sink),
                timeout=timeout,
                pass_ending=lambda: pass_state["ending"],
                first_ending=first_ending,
                on_outcome=lambda text: pass_state.__setitem__("outcome", text),
            )
            if vrc != 0:
                rc, verify_failed = vrc, vrc != RELOAD_YIELD_RC
                yielded_for_reload = vrc == RELOAD_YIELD_RC
                if yielded_for_reload:
                    emit_event({FORGE_EVENT_KEY: "meta", "text": "Build paused for landed-code reload"})
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        # The frame that raised is the only thing that turns "run failed" into
        # a fix; a self-edit run died on a copied venv link (WinError 1920)
        # with nothing in the record saying which walker touched it.
        log.warning("agent loop run failed: %s: %s", type(exc).__name__, exc, exc_info=True)
        return CliDispatchResult(False, f"refused: agent loop run failed: {type(exc).__name__}: {exc}", prompt)
    finally:
        if control is not None:
            control.stop_listening(run_control.LEAD)

    changed = forge_code_git.project_delta_since(cwd, snap_before)
    action_refused = saw_refusal
    # A run that changed nothing can still have answered the question. Any tool
    # use at all used to disqualify that, so "inspect this and explain it" --
    # which must read files to answer -- came back as a failure with a
    # fabricated exit 1, on top of a correct answer that was then hidden.
    #
    # Inspection failures do not disqualify. A failed shell call can recover
    # through a later successful write-capable call; a failed file edit needs
    # a later successful file edit. Clean write-capable calls leave a neutral
    # note when nothing changed. Read-only runs keep their note-free wording.
    read_only_run = tool_verdict.saw_named_tool and not tool_verdict.saw_mutating_tool
    tools_disqualify = tool_verdict.unresolved
    conversation_reply = rc == 0 and not changed and saw_reply and not tools_disqualify and not action_refused
    if yielded_for_reload:
        reason = "yielded for landed-code reload; unfinished Build will resume after restart"
    elif rc == PASS_WALL_CLOCK_RC and not verify_failed:
        reason = f"the pass reached its wall clock ({int(timeout)} s)" + (
            f"; {len(changed)} file(s) changed but verification is off"
            if changed
            else " with no file changed and no tool activity"
        )
    elif rc != 0 and pass_state["outcome"]:
        reason = pass_state["outcome"]
    elif rc != 0:
        reason = f"verification failed (exit {rc}) after fix attempts" if verify_failed else f"agent loop exited {rc}"
    elif action_refused:
        detail = " after leaving partial file changes" if changed else ""
        reason = f"GPT could not complete the requested action{detail}"
    elif not changed:
        if conversation_reply and read_only_run:
            reason = "GPT answered from the project without changing files"
        elif conversation_reply and tool_verdict.saw_tool:
            # Write-capable tool ran without an unresolved failure, and git says
            # nothing changed: the answer IS the outcome. That fact stays
            # visible as a neutral note in the event stream, not an error.
            reason = "GPT answered; a write-capable tool ran and no files changed"
            emit_sink(
                {FORGE_EVENT_KEY: "meta", "text": "a write-capable tool ran; no files changed", "is_error": False}
            )
        elif conversation_reply:
            reason = "GPT replied without changing files"
        elif saw_reply:
            # The run is rightly not a success — a tool call reported failure
            # and no changes landed — but an answer EXISTS, and calling it
            # "nothing to review" was false. Describe both facts.
            reason = (
                "GPT gave an answer but a tool call failed and no files changed — review the answer; no edit landed"
            )
        else:
            # "Nothing to review" is reserved for when it is true: no repo
            # changes AND no answer text.
            reason = "GPT ran but made NO repo changes and gave no answer — nothing to review"
    else:
        reason = f"dispatched via GPT (ChatGPT OAuth, in-process; {len(changed)} file(s) changed; engine checks passed)"
    return CliDispatchResult(
        ok=(rc == 0 and not yielded_for_reload and not action_refused and (bool(changed) or conversation_reply)),
        reason=reason,
        prompt=prompt,
        returncode=75 if yielded_for_reload else rc,
        changed_files=changed,
        stdout_tail=str(out)[-2000:],
    )
