"""GPT/AgentLoop in-process dispatch — the ChatGPT-OAuth brain twin of dispatch_claude_cli."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from thomas.agent.loop_tool_protocol import is_inspection_tool, tool_call_access

from .bridge_config import emergency_stop_active, emergency_stop_path
from .bridge_prompts import compose_headless_prompt
from .build_verify import PASS_WALL_CLOCK_RC, _verify_and_iterate
from .dispatch_agent_loop_translator import (  # noqa: F401 - the names tests and callers import from here
    _acceptance_event,
    _AgentLoopForgeTranslator,
    _summarize_agent_event_tool,
)
from .dispatch_agent_summary import _acceptance_summary, _judge_checks_summary  # noqa: F401 - re-exported for tests
from .dispatch_claude_cli import CliDispatchResult, _is_action_refusal, _is_conversational_reply
from .forge_event_stream import (
    FORGE_EVENT_KEY,
    _StreamState,
    _summarize_tool_input,
    _thinking_to_events,
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
) -> tuple[int, str]:
    """Run ONE in-process AgentLoop edit pass on the ``openai_codex`` provider.

    ``acceptance_sink``, when given, receives the pass's acceptance settlement
    under ``"acceptance"`` so the engine can decide whether the work is done.

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
            acceptance_sink=acceptance_sink,
            protected_paths=protected_paths,
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
) -> tuple[int, str]:
    from thomas.agent.loop import AgentLoop
    from thomas.core.config import load_config
    from thomas.core.file_access import parse_file_access_level
    from thomas.core.llm_client import LLMClient
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
    # The acceptance contract's depth: the Build's effort, floored at the level
    # with a separate judge. The contract reads the worker model's own effort
    # (`loop.llm.config.reasoning_effort`) unless this attribute is set, so a
    # Build can verify deeper without paying for a deeper worker.
    # The run's file fence: paths the brief or another agent's claim holds. Enforced
    # by the write tools (loop_tool_paths), not left to the prose.
    agent.protected_paths = [str(p) for p in (protected_paths or []) if str(p).strip()]
    agent.verification_effort = _contract_level_for_build(str(getattr(model_cfg, "reasoning_effort", "") or ""))

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
    if acceptance_sink is not None:
        acceptance_sink["acceptance"] = translator.acceptance
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
        project_root=cwd,
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
    saw_named_tool = False
    saw_mutating_tool = False
    saw_failed_tool = False

    def emit_event(event: dict[str, Any]) -> None:
        nonlocal saw_reply, saw_refusal, saw_tool_activity, saw_named_tool, saw_mutating_tool, saw_failed_tool
        kind = str(event.get(FORGE_EVENT_KEY) or "")
        if kind in {"final", "say"}:
            reply_text = str(event.get("text") or "")
            if _is_conversational_reply(reply_text):
                saw_reply = True
            if _is_action_refusal(reply_text):
                saw_refusal = True
        elif kind in {"tool", "tool_result"}:
            saw_tool_activity = True
            # A call that REPORTED failure is the one genuine failed-edit
            # signal a no-change run can carry (see the verdict below).
            if kind == "tool_result" and bool(event.get("is_error")):
                saw_failed_tool = True
            # Only ``tool`` carries a name; ``tool_result`` does not. Record what
            # we can, and stay conservative about what we cannot see.
            name = str(event.get("name") or "").strip()
            if name and name != "tool":
                saw_named_tool = True
                # Prefer the per-call classification the translator stamped on
                # the event (``access``): it judges shell.exec by the COMMAND it
                # ran, so "dir" counts as inspection and "del x" as a write.
                # The name-list check alone called every shell call a write,
                # which filed explain-only runs ("dir" + a correct answer) as
                # failed edits. Events without the stamp keep the name rule.
                access = str(event.get("access") or "")
                if access == "write" or (not access and not is_inspection_tool(name)):
                    saw_mutating_tool = True
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

    # The last pass's acceptance settlement, read by the engine after each pass.
    # An injected ``runner`` (tests) never fills it, so the engine sees no contract.
    acceptance_sink: dict[str, Any] = {}
    pass_state: dict[str, bool] = {"clock": False}

    def _run_pass(p: str) -> tuple[int, str]:
        rc_out = _run_pass_inner(p)
        pass_state["clock"] = rc_out[0] == PASS_WALL_CLOCK_RC
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
        )

    from thomas.forge.anvil import forge_code_git

    verify_failed = False
    try:
        # The open-time choice to work without history arrives as an argument, never inferred.
        snap_before = forge_code_git.snapshot(cwd, allow_without_history=allow_without_history)
        rc, out = _run_pass(prompt)
        if (
            rc == PASS_WALL_CLOCK_RC
            and verify
            and (forge_code_git.project_delta_since(cwd, snap_before) or saw_tool_activity)
        ):
            # The clock ended a pass that was working: a pass boundary, not a
            # verdict. Files on disk are one kind of work; a pass that only
            # played and proved (the Minecraft proof run: eight sessions, no
            # file to change) is another. Only a pass that did nothing fails.
            what = "files changed" if forge_code_git.project_delta_since(cwd, snap_before) else "the pass was working"
            emit_event({FORGE_EVENT_KEY: "meta", "text": f"{what} before the wall clock; verifying and continuing"})
            rc = 0
        # The RUN/TEST step: only verify a clean edit pass. The engine — ordinary
        # in-process Python — owns the real check regardless of the brain.
        if verify and rc == 0:
            vrc = _verify_and_iterate(
                cwd,
                snap_before,
                emit_event,
                _run_pass,
                goal,
                verifier=verifier,
                max_fix_iters=max_fix_iters,
                contract=lambda: _clock_contract(cwd) if pass_state["clock"] else acceptance_sink.get("acceptance"),
            )
            if vrc != 0:
                rc, verify_failed = vrc, True
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        # The frame that raised is the only thing that turns "run failed" into
        # a fix; a self-edit run died on a copied venv link (WinError 1920)
        # with nothing in the record saying which walker touched it.
        log.warning("agent loop run failed: %s: %s", type(exc).__name__, exc, exc_info=True)
        return CliDispatchResult(False, f"refused: agent loop run failed: {type(exc).__name__}: {exc}", prompt)

    changed = forge_code_git.project_delta_since(cwd, snap_before)
    action_refused = saw_refusal
    # A run that changed nothing can still have answered the question. Any tool
    # use at all used to disqualify that, so "inspect this and explain it" --
    # which must read files to answer -- came back as a failure with a
    # fabricated exit 1, on top of a correct answer that was then hidden.
    #
    # Reading is not a failed edit -- and neither is a write-capable tool that
    # RAN AND SUCCEEDED while git truth says nothing changed. The previous rule
    # demoted that whole answered run to a synthetic failure, which meant one
    # misclassified shell command (measured 2026-08-05: a PowerShell directory
    # listing stamped access='write') buried a correct answer under a
    # fabricated exit 1. The only genuine failed-edit signal a no-change run
    # can carry is a tool call that REPORTED failure (``is_error`` on its
    # result -- a mutating tool that failed is exactly that), so only that
    # still disqualifies. A clean write-capable run files as the conversation
    # outcome with a visible neutral note in the events (below), never an
    # error. Read-only runs keep their existing, note-free wording.
    read_only_run = saw_named_tool and not saw_mutating_tool
    tools_disqualify = saw_tool_activity and not read_only_run and saw_failed_tool
    conversation_reply = rc == 0 and not changed and saw_reply and not tools_disqualify and not action_refused
    if rc == PASS_WALL_CLOCK_RC and not verify_failed:
        reason = f"the pass reached its wall clock ({int(timeout)} s)" + (
            f"; {len(changed)} file(s) changed but verification is off"
            if changed
            else " with no file changed and no tool activity"
        )
    elif rc != 0:
        reason = f"verification failed (exit {rc}) after fix attempts" if verify_failed else f"agent loop exited {rc}"
    elif action_refused:
        detail = " after leaving partial file changes" if changed else ""
        reason = f"GPT could not complete the requested action{detail}"
    elif not changed:
        if conversation_reply and read_only_run:
            reason = "GPT answered from the project without changing files"
        elif conversation_reply and saw_tool_activity:
            # Write-capable tool ran, every result succeeded, git says nothing
            # changed: the answer IS the outcome. The fact worth knowing stays
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
        ok=(rc == 0 and not action_refused and (bool(changed) or conversation_reply)),
        reason=reason,
        prompt=prompt,
        returncode=rc,
        changed_files=changed,
        stdout_tail=str(out)[-2000:],
    )
