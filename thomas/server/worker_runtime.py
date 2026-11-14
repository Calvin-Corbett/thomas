"""Provider-agnostic background worker.

This is the engine that replaced the legacy ``CodexBridge`` worker fork.  The
old worker hardwired the background task to Codex's *own* native sandbox tools,
throwing away Thomas's tool schemas — so it only worked for one provider.

``run_agent_worker_events`` instead drives the **standard ``AgentLoop`` with the
full Thomas ``ToolRegistry``** — the same engine the CLI and chat already use —
so the worker inherits provider-agnosticism for free.  ``anthropic``,
``openai_codex`` (gpt-5.5 over OAuth), and local ``ollama`` models all run
through this *one* code path; the provider is selected entirely by config.

The split is symmetric with the chatbot-only law:
  * chat surface = ``AgentLoop`` with an empty tool registry -> talks only.
  * worker       = the *same* ``AgentLoop`` with the FULL registry -> does the
    work, in an isolated per-task workspace.

It yields the same bridge-style event dicts the old ``bridge.chat()`` emitted
(``{"type": "text"|"tool_start"|"tool_output"|"done"|"error", ...}``) so the
delegation layer's task-runtime + emitter glue is reused verbatim — only the
event *producer* changed.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from thomas.agent.kernel_wiring import build_agent_loop, resolve_tools_for_turn
from thomas.agent.loop import AgentLoop
from thomas.core import session_scope
from thomas.core.config import AppConfig
from thomas.core.events import EventType
from thomas.core.kernel import late, seams
from thomas.core.llm_client import LLMClient
from thomas.core.llm_slot import models
from thomas.core.token_economy import compute_max_passes, effective_effort
from thomas.models.worker_overrides import resolve_override
from thomas.server import green_checkout
from thomas.server.app_keys import APP_CONFIG, APP_MEMORY, APP_SECRETS, APP_TOOLS
from thomas.server.chat_app_keys import APP_CHAT_BUDGET_LEDGER
from thomas.server.chat_budget_ledger import ChatBudgetError, ChatBudgetExceeded, budget_context, get_chat_budget_ledger
from thomas.server.chat_budget_scope import scope_from_runtime_policy
from thomas.server.chat_delegation_tool_receipts import tool_action_id
from thomas.server.chat_runtime_policy import (
    ModelRuntimePolicy,
    PolicyToolRegistryView,
    model_endpoint_is_local,
    tool_policy_from_payload,
)
from thomas.server.issue_ledger import record_issue
from thomas.server.model_credentials import embed_credentials
from thomas.server.model_runtime_receipt import model_runtime_receipt
from thomas.server.plugin_hook_bridge import make_plugin_hook_runner
from thomas.server.praxis.quota import QuotaClassifier
from thomas.tools.registry import ToolRegistry

log = logging.getLogger(__name__)
_QUOTA_CLASSIFIER = QuotaClassifier()


def _session_usage_total(llm: Any) -> int:
    usage = getattr(llm, "session_usage", None)
    prompt = max(0, int(getattr(usage, "prompt_tokens", 0) or 0))
    completion = max(0, int(getattr(usage, "completion_tokens", 0) or 0))
    return max(prompt + completion, max(0, int(getattr(usage, "total_tokens", 0) or 0)))


def _embed_secrets(model_cfg: Any, profile: str, secret_store: Any) -> Any:
    """``model_cfg`` with its API key / OAuth token embedded; a key may live under the profile name."""
    return embed_credentials(model_cfg, profile, secret_store, profile_name_fallback=True)


def _resolve_profile(cfg: AppConfig, profile: str | None, role: str | None = None) -> str:
    """Pick the model profile the worker should run, provider-blind.

    Precedence (by design, chat is separate from the pipeline):
      1. Per-specialist (role) override — the top model selector's per-agent
         choice (e.g. "researcher -> Grok") wins over everything.
      2. The chat's selected model — the pipeline default when no role override.
      3. Global user preference / project default / any configured model.
    """
    db_path = None
    try:
        from thomas.preferences.store import get_db_path

        db_path = get_db_path()
    # Locating the prefs DB: ImportError when the preferences package is absent,
    # OSError when the home/app directory cannot be resolved, ValueError/
    # AttributeError when it hands back something unusable. None means "resolve
    # the model without stored preferences", which every step below tolerates.
    except (ImportError, OSError, ValueError, AttributeError):
        db_path = None

    # 1. Per-specialist (role) override.
    if role:
        try:
            from thomas.core.model_resolution import resolve_model_profile_name
            from thomas.preferences.model_prefs import read_user_model_role_preferences

            role_profile, _role_model_id = read_user_model_role_preferences(
                user_id="default", role=role, db_path=db_path
            )
            role_profile = resolve_model_profile_name(cfg, role_profile)
            if role_profile:
                return role_profile
        # A sqlite read behind an optional import, then a name lookup in config:
        # ImportError, OSError/sqlite3.Error for the DB, and TypeError/ValueError/
        # KeyError/AttributeError for a stored preference that no longer matches
        # any configured profile. Falls through to the chat default.
        except (ImportError, OSError, sqlite3.Error, TypeError, ValueError, KeyError, AttributeError) as exc:
            log.debug("worker: role model pref lookup failed for role=%s: %s", role, exc)

    # 2. The chat's selected model is the pipeline default.
    if profile and profile in cfg.models:
        return profile

    # 3. Global user preference / project default.
    try:
        from os import environ

        from thomas.preferences.model_resolution import resolve_effective_model

        resolved_profile, _model_id = resolve_effective_model(
            cfg,
            env_profile=str(environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
            user_id="default",
            db_path=db_path,
        )
        if resolved_profile in cfg.models:
            return resolved_profile
    # Same shape as the role lookup above -- env var, sqlite preferences, then a
    # config lookup. Falls back to cfg.default_model.
    except (ImportError, OSError, sqlite3.Error, TypeError, ValueError, KeyError, AttributeError) as exc:
        log.debug("worker: resolve_effective_model failed: %s", exc)
    fallback = str(cfg.default_model or "").strip()
    if fallback not in cfg.models and cfg.models:
        fallback = next(iter(cfg.models))
    return fallback


def _apply_tool_deny(tools: Any, deny: frozenset[str]) -> None:
    """Drop denied tools from the registry, matching by name, dotted-prefix, or category."""
    if not deny:
        return
    registered = getattr(tools, "_tools", None)
    if not isinstance(registered, dict):
        return
    for name, tool in list(registered.items()):
        category = str(getattr(tool, "category", "") or "")
        if any(name == tok or name.startswith(f"{tok}.") or category == tok for tok in deny):
            try:
                tools.unregister(name)
            # A registry that does not implement unregister the way we assume
            # (AttributeError/TypeError) or a name already gone (KeyError). Say
            # so: a tool that survives a deny list is worth a line in the log.
            except (AttributeError, TypeError, KeyError):
                log.warning("worker: could not unregister denied tool %s", name, exc_info=True)


def _task_prompt_reminder() -> str:
    """The hard file-tool rule, restated at the top of the task prompt.

    Models weight the user turn more heavily than the system prompt (observed:
    gpt-5.x ignores the system rule and reaches for Unix shell builtins like
    `printf`/`mkdir -p`, which fail on Windows cmd.exe), so it is restated
    here. `diff.create` is also named explicitly: workers offered it only in
    the system prompt's "Editing Policy" kept rewriting existing files whole
    from memory instead, truncating them once earlier tool arguments were
    compacted out of context (self-fix evidence, 2026-09-24).
    """
    return (
        "Reminder: change an EXISTING file with `diff.create` — it edits only the "
        "part that changed and cannot truncate the rest of the file. Use "
        "`fs.write_file` to create a file that does not exist yet, or to replace "
        "one whole file when that is really what is intended (pass "
        "replace_whole_file: true); on a file of at least 20 lines or 2,000 characters, "
        "`fs.write_file` refuses a write that cuts more than 40% of its lines OR "
        "characters, because rewriting a large file from memory is how truncations "
        "happen. Write to a nested path to "
        "make folders; never use shell commands like printf, echo, touch, cat, or "
        "mkdir for files. Use `fs.list_dir` to list. "
        "CRITICAL: when the task is to produce or change a file, document, game, "
        "script, or app, you MUST actually CALL `diff.create` (existing file) or "
        "`fs.write_file` (new file) with the real edit/contents. Do NOT paste the "
        "code or text into your reply and tell the user to save it — pasting it "
        "does NOT create or change the file, so the deliverable would not exist. "
        "The tool call is the only thing that creates or changes it; make the "
        "call first, then briefly say what you made. "
        "Browser tools ARE available: when the task names `browser.open`, "
        "`browser.extract`, or another browser tool, call those exact tools in the "
        "requested order. Carry real returned values into later file writes; never "
        "substitute placeholders. Preserve exact requested filenames and read back "
        "the same file before finishing."
    )


async def run_agent_worker_events(
    app: Any,
    *,
    prompt: str,
    instructions: str,
    work_dir: Path | str,
    profile: str | None = None,
    model_id: str | None = None,
    reasoning_effort: str | None = None,
    role: str | None = None,
    effort: str = "diligent",
    session_id: str | None = None,
    execution_id: str | None = None,
    autonomy_level: int = 4,
    file_access: int | None = None,
    guardrails: str = "",
    guardrail_modes: dict[str, str] | None = None,
    job_type: str | None = None,
    work_context_id: str = "",
    memory_enabled: bool = True,
    tools_enabled: bool = True,
    runtime_policy: dict[str, Any] | None = None,
    can_spawn: bool = True,
    steering_queue: Any | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run the standard ``AgentLoop`` (full tools, workspace-confined) and yield
    bridge-style event dicts.

    The tool registry is confined to ``work_dir`` via ``sandbox_root`` — bound at
    tool *registration*, which is per-registry, NOT process-global — so deliverables
    land in the workspace and escapes are blocked WITHOUT an ``os.chdir`` (which is
    process-global and would race across concurrent workers).
    """
    # A card this run raises belongs to the chat that asked for the work, not to
    # the per-attempt session bound for budgets (thomas/core/session_scope.py).
    session_scope.set_chat_from_execution(str(execution_id or ""))
    yield {"type": "progress", "text": "Provider-native worker is initializing."}

    cfg: AppConfig = app[APP_CONFIG]
    secret_store = app.get(APP_SECRETS)
    policy_payload = dict(runtime_policy or {})
    memory_policy_payload = dict(policy_payload.get("memory") or {})
    memory = app.get(APP_MEMORY) if memory_enabled and bool(memory_policy_payload.get("enabled", True)) else None
    tool_policy = tool_policy_from_payload(policy_payload.get("tools"))
    model_policy_payload = dict(policy_payload.get("model") or {})
    model_policy = ModelRuntimePolicy(**model_policy_payload) if model_policy_payload else None

    resolved_profile = _resolve_profile(cfg, profile, role)
    base_model_cfg = cfg.models.get(resolved_profile) or cfg.get_model(resolved_profile)
    if bool(policy_payload.get("local_only", False)) and not model_endpoint_is_local(base_model_cfg):
        raise PermissionError("local_only_mode blocks non-local worker model endpoints")
    requested_model_id = str(model_id or "").strip()
    requested_reasoning_effort = str(reasoning_effort or "").strip().lower()
    model_overrides: dict[str, Any] = {}
    if requested_model_id and hasattr(base_model_cfg, "model"):
        model_overrides["model"] = requested_model_id
    if requested_reasoning_effort and hasattr(base_model_cfg, "reasoning_effort"):
        model_overrides["reasoning_effort"] = requested_reasoning_effort
    if model_overrides and model_policy is None:
        base_model_cfg = dataclasses.replace(base_model_cfg, **model_overrides)
    if model_policy is not None:
        base_model_cfg = model_policy.apply(
            base_model_cfg,
            model_id=requested_model_id,
            reasoning_effort=requested_reasoning_effort,
        )
    model_cfg = _embed_secrets(base_model_cfg, resolved_profile, secret_store)

    override = resolve_override(getattr(model_cfg, "provider", ""), getattr(model_cfg, "model", ""))
    if not requested_reasoning_effort and override.reasoning_effort and hasattr(model_cfg, "reasoning_effort"):
        # Set in place rather than dataclasses.replace(): model_cfg is already a
        # fresh copy from _embed_secrets, and replace() would silently drop the
        # dynamically-attached _openai_codex_token_ready attribute.
        try:
            model_cfg.reasoning_effort = override.reasoning_effort
        # A single attribute assignment: the field reads back but is not settable
        # (frozen dataclass raises FrozenInstanceError, a subclass of
        # AttributeError; __slots__ or a property raise AttributeError/TypeError;
        # a validating setter raises ValueError). The worker runs at the model's
        # own default effort instead.
        except (AttributeError, TypeError, ValueError):
            log.debug(
                "worker: reasoning_effort override not settable on %s",
                getattr(model_cfg, "provider", "?"),
                exc_info=True,
            )

    # Failover chain, with secrets embedded the same way (provider-blind).
    configured_fallbacks = list(cfg.failover_chain(resolved_profile))
    if model_policy is not None and model_policy.failover_profiles:
        configured_fallbacks = [
            cfg.get_model(name)
            for name in model_policy.failover_profiles
            if name != resolved_profile and name in cfg.models
        ]
    if bool(policy_payload.get("local_only", False)):
        configured_fallbacks = [item for item in configured_fallbacks if model_endpoint_is_local(item)]
    fallbacks = [
        _embed_secrets(fc, str(getattr(fc, "name", "") or resolved_profile), secret_store)
        for fc in configured_fallbacks
    ]

    # FULL tool surface confined to the per-task workspace (see docstring). The
    # file-access ladder defaults to the config level, but a per-request override
    # (from the chat payload / UI toggle) wins when provided — so the user can dial
    # "let Thomas write to my PC" per session without editing config.
    effective_file_access = cfg.tools.file_access if file_access is None else int(file_access)
    # A self-fix works in green, and green is its whole project (green_checkout).
    effective_file_access = green_checkout.file_access_for(effective_file_access, work_dir)
    run_cfg = dataclasses.replace(
        cfg,
        tools=dataclasses.replace(
            cfg.tools,
            sandbox_root=str(work_dir),
            allow_shell=bool(tool_policy.allow_shell) if tool_policy is not None else True,
            file_access=effective_file_access,
        ),
    )
    quality_payload = dict(policy_payload.get("quality") or {})
    if quality_payload:
        run_cfg = dataclasses.replace(
            run_cfg,
            max_agent_iterations=int(quality_payload.get("max_agent_iterations") or run_cfg.max_agent_iterations),
            quality=dataclasses.replace(
                run_cfg.quality,
                enforce=bool(quality_payload.get("enforce", run_cfg.quality.enforce)),
                require_verification_for_coding=bool(
                    quality_payload.get(
                        "require_verification_for_coding",
                        run_cfg.quality.require_verification_for_coding,
                    )
                ),
                require_tests_for_code_edits=bool(
                    quality_payload.get("require_tests_for_code_edits", run_cfg.quality.require_tests_for_code_edits)
                ),
                require_monolith_guard_for_coding=bool(
                    quality_payload.get(
                        "require_monolith_guard_for_coding",
                        run_cfg.quality.require_monolith_guard_for_coding,
                    )
                ),
            ),
        )
    tools = late.call(seams.TOOL_SET, run_cfg) if tools_enabled else ToolRegistry()
    if tools_enabled:
        from thomas.server.app_helpers import add_tools_rows_lent_the_server

        add_tools_rows_lent_the_server(tools, app.get(APP_TOOLS), run_cfg.tools.sandbox_path)
        tools = resolve_tools_for_turn(tools, allow_new=True)
    _apply_tool_deny(tools, override.tool_deny)

    if tools_enabled and can_spawn:
        # The lead can hand a self-contained piece to another agent. The child
        # runs this same worker with `can_spawn=False`, so the recursion is one
        # level by construction and not by a counter anyone has to check.
        from thomas.server.agent_spawn_tool import register_spawn_tool

        async def _run_child(title: str, brief: str) -> AsyncIterator[dict[str, Any]]:
            async for child_event in run_agent_worker_events(
                app,
                prompt=brief,
                instructions=instructions,
                work_dir=work_dir,
                profile=profile,
                model_id=model_id,
                reasoning_effort=reasoning_effort,
                role=title,
                effort=effort,
                session_id=session_id,
                execution_id=f"{execution_id or 'worker'}::{title}",
                autonomy_level=autonomy_level,
                file_access=file_access,
                guardrails=guardrails,
                guardrail_modes=guardrail_modes,
                job_type=job_type,
                memory_enabled=False,
                runtime_policy=runtime_policy,
                can_spawn=False,
            ):
                yield child_event

        register_spawn_tool(tools, execution_id=str(execution_id or ""), run_child=_run_child)

    # Guardrails: resolve the effective policy (payload modes -> preset -> saved),
    # then enforce the two runtime-meaningful groups. `reach` prunes external tools;
    # `gatekeeper` (applied to the loop below) sets the approval posture. The other
    # five groups are code-quality gates honored at commit time via the saved policy.
    from thomas.server.guardrails_state import (
        build_effective_guardrails,
        gatekeeper_no_human_mode,
        reach_deny_set,
    )

    guardrails_state_eff = build_effective_guardrails(guardrails, guardrail_modes)
    _apply_tool_deny(tools, reach_deny_set(guardrails_state_eff.mode_for("reach")))
    work_system_context = ""
    if work_context_id and tools_enabled:
        from thomas.server.work_connector_runtime import (
            request_work_tools,
            work_context_system_prompt,
        )

        tools = request_work_tools(app, tools, context_id=work_context_id)
        work_system_context = work_context_system_prompt(app, context_id=work_context_id)
    if tool_policy is not None:
        tools = PolicyToolRegistryView(tools, tool_policy, base_root=work_dir)

    system_prompt = f"{instructions}{override.prompt_suffix or ''}"
    if work_system_context:
        system_prompt = f"{system_prompt}\n\n{work_system_context}"
    system_instructions = str(policy_payload.get("system_instructions") or "").strip()
    if system_instructions:
        system_prompt = f"{system_prompt}\n\nUser-approved persistent instructions:\n{system_instructions}"

    budget_ctx = budget_context(policy_payload)
    budget_ledger = app.get(APP_CHAT_BUDGET_LEDGER)
    if budget_ledger is None and budget_ctx.get("ledger_path"):
        budget_ledger = get_chat_budget_ledger(str(budget_ctx["ledger_path"]))
    budget_scope = None
    if budget_ledger is not None and budget_ctx:
        try:
            budget_scope = scope_from_runtime_policy(
                budget_ledger,
                policy_payload,
                user_id=str(budget_ctx.get("user_id") or "default"),
                session_id=str(budget_ctx.get("session_id") or session_id or "default"),
            )
            await budget_scope.preflight()
        except ChatBudgetExceeded as exc:
            yield {"type": "error", "error": str(exc), "retryable": False}
            return
        except ChatBudgetError as exc:
            yield {"type": "error", "error": str(exc), "retryable": False}
            return

    from thomas.core.llm_request_admission import RoutedProviderAdmission

    worker_admission = RoutedProviderAdmission(team=f"chat-worker:{execution_id or uuid.uuid4().hex}")
    llm = models().open(
        model_cfg,
        default=LLMClient,
        fallback_configs=fallbacks,
        failover_enabled=bool(model_policy.failover_enabled if model_policy is not None else cfg.failover.enabled)
        and bool(fallbacks),
        failover_cooldown_s=(
            model_policy.failover_cooldown_s if model_policy is not None else cfg.failover.cooldown_seconds
        ),
        failover_on_auth_error=(
            model_policy.failover_on_auth_error if model_policy is not None else cfg.failover.fallback_on_auth_error
        ),
        max_retries=model_policy.max_retries if model_policy is not None else 3,
        base_retry_delay_s=model_policy.retry_backoff_s if model_policy is not None else 0.8,
        request_overrides=(
            model_policy.request_overrides if model_policy is not None else dict(override.request_overrides or {})
        ),
        request_admission=worker_admission,
    )
    llm_closed = False

    async def close_llm_once() -> None:
        nonlocal llm_closed
        if not llm_closed:
            llm_closed = True
            try:
                await llm.close()
            finally:
                worker_admission.close()

    try:
        set_budget_scope = getattr(llm, "set_budget_scope", None)
        if budget_scope is not None and callable(set_budget_scope):
            set_budget_scope(budget_scope)
        unscoped_usage_before = _session_usage_total(llm)
        llm.reset_runtime_trace()

        run_id = str(execution_id or f"worker:{uuid.uuid4().hex}")
        agent = build_agent_loop(
            run_cfg,
            llm,
            tools,
            system_prompt=system_prompt,
            memory=memory,
            thread_id=run_id,
            run_id=run_id,
            session_id=str(session_id or run_id),
            # Level 4 = full autonomy / no_human_mode: the worker runs unattended and
            # must not block waiting for tool approvals.
            autonomy_level=autonomy_level,
            max_parallel_tools=tool_policy.max_parallel_tools if tool_policy is not None else None,
            tool_timeout_s=tool_policy.tool_timeout_s if tool_policy is not None else None,
            memory_retrieval_scope="thread",
            # Background runs fired no plugin hooks at all until now: only the web
            # chat path supplied a runner, so a plugin's view of Thomas depended on
            # which surface happened to be executing (phase 3.2).
            hook_runner=make_plugin_hook_runner(),
            message_queue=steering_queue,
            default=AgentLoop,
            non_coder_profile=bool(policy_payload.get("profile_type") == "non_coder"),
            profile_type=str(policy_payload.get("profile_type") or "adaptive"),
            review_depth=str(policy_payload.get("review_depth") or "adaptive"),
        )
    except Exception:
        log.exception("worker: agent runtime initialization failed")
        await close_llm_once()
        raise
    try:
        if memory_policy_payload:
            agent._memory_include_thread_pref = bool(memory_policy_payload.get("include_thread", True))
            agent._memory_include_global_pref = bool(memory_policy_payload.get("include_global", False))
            agent._memory_include_profile_pref = bool(memory_policy_payload.get("include_profile", False))
            agent._memory_pins_only_pref = bool(memory_policy_payload.get("pins_only", False))
            agent._memory_max_pack_tokens_pref = int(memory_policy_payload.get("context_budget") or 1200)
            agent._memory_max_results_pref = int(memory_policy_payload.get("retrieval_top_k") or 5)
            agent._memory_decay_half_life_hours_pref = float(
                memory_policy_payload.get("decay_half_life_hours") or 168.0
            )

        # Guardrails `gatekeeper` pins the approval posture for this run (strict = deny
        # risky tools unattended; standard = autonomy-derived; permissive = escalate).
        if tool_policy is not None and tool_policy.require_command_approval:
            _base_nhm = "deny"
        elif int(autonomy_level or 0) >= 4:
            _base_nhm = "allow"
        else:
            _base_nhm = None
        agent._no_human_mode_override = gatekeeper_no_human_mode(guardrails_state_eff.mode_for("gatekeeper"), _base_nhm)
        # Check the contract where this worker's file tools write; never move the process working folder.
        agent.verify_in_tool_workspace = True
    except Exception:
        log.exception("worker: agent runtime policy application failed")
        await close_llm_once()
        raise

    entered_progress_resumed = False
    try:
        yield {"type": "progress", "text": "On it — starting the work now."}
        entered_progress_resumed = True
    finally:
        if not entered_progress_resumed:
            await close_llm_once()

    # Effort x Autonomy drives the pass budget; a per-model override can still cap it.
    try:
        applied_effort = effective_effort(effort, autonomy_level)
        effort_passes = compute_max_passes(applied_effort, run_cfg.max_agent_iterations)
        max_iters = effort_passes if override.max_iterations is None else min(effort_passes, override.max_iterations)
        # Ruling W (fix round 1, C1): the Autopilot multiplier applies AFTER the
        # per-model cap, not before. Multiplying compute_max_passes's own result
        # let the cap win every time for a capped model -- the openai_codex/
        # gpt-5.6-sol default (cap 30) measured min(3 * 400, 30) == 30, so the
        # tripling never reached the live worker. On Autopilot (autonomy 5), a
        # self-development worker's per-attempt budget is 3x whatever it would
        # otherwise get, capped or not (90 for that model); the attempt count
        # (_self_recovery_attempts) stays the runaway guard, untouched here.
        if int(autonomy_level or 0) >= 5 and str(job_type or "").strip().lower() == "self_development":
            max_iters *= 3
    except Exception:
        log.exception("worker: effort budget calculation failed")
        await close_llm_once()
        raise

    # The system prompt carries the file-tool rule, but models weight the user
    # turn more heavily (observed: gpt-5.x ignores the system rule and reaches for
    # Unix shell builtins like `printf`/`mkdir -p`, which fail on Windows cmd.exe).
    # Restating the hard rule at the top of the task prompt makes it stick.
    if tools_enabled:
        task_prompt = f"{_task_prompt_reminder()}\n\n{prompt}"
    else:
        task_prompt = (
            "This is an answer-only model pass. No tools are available or needed. "
            "Do not claim that a file, external action, or tool call was completed. "
            "Return the requested substantive text directly.\n\n"
            f"{prompt}"
        )

    streamed_text = False

    def _successful_runtime_receipt() -> dict[str, Any] | None:
        runtime = model_runtime_receipt(
            llm,
            requested_profile=resolved_profile,
            requested_model_id=requested_model_id or str(getattr(model_cfg, "model", "") or ""),
        )
        attempts = runtime.get("attempts") if isinstance(runtime.get("attempts"), list) else []
        return runtime if any(str(attempt.get("status") or "") == "success" for attempt in attempts) else None

    agent_events = None
    try:
        # The model reads the reminder; the contract, routing and memory read the task. Judged with the reminder,
        # `browser.open` and `browser.extract` became files the task "names as outputs", which no run could produce.
        agent_events = agent.run(
            task_prompt,
            intent_text=prompt,
            mode="auto",
            tools_policy="auto",
            token_economy=applied_effort,
            max_iterations=max_iters,
            job_type=job_type,
        )
        async for event in agent_events:
            etype = event.type
            if etype == EventType.TEXT_DELTA:
                text = str(event.data.get("text") or "")
                if text:
                    streamed_text = True
                    yield {"type": "text", "text": text}
            elif etype == EventType.TOOL_CALL_START:
                name = str(event.data.get("tool_name") or event.data.get("name") or "tool")
                yield {"type": "tool_start", "name": name, "call_id": str(event.data.get("tool_id") or "")}
            elif etype == EventType.TOOL_RESULT:
                name = str(event.data.get("tool_name") or "tool")
                # Preserve the tool's SUCCESS signal — previously dropped, so a tool
                # that errored looked identical to one that succeeded and a failed
                # action ("send the email") could still be reported as done. Default
                # to ok unless an explicit error/failure signal is present.
                err = event.data.get("error") or event.data.get("is_error")
                ok_field = event.data.get("ok")
                success_field = event.data.get("success")
                ok = True
                if err:
                    ok = False
                elif ok_field is not None:
                    ok = bool(ok_field)
                elif success_field is not None:
                    ok = bool(success_field)
                # Preserve a bounded result for downstream completion verification.
                # The worker model already received this content; the delegation
                # layer needs it too so a placeholder artifact cannot be certified
                # when a browser/read tool returned the real value.
                result_text = str(event.data.get("result_text") or event.data.get("result") or "")
                yield {
                    "type": "tool_output",
                    "name": name,
                    "call_id": str(event.data.get("tool_id") or ""),
                    "action_id": tool_action_id(name, event.data.get("arguments"), workspace=work_dir),
                    "ok": ok,
                    "error": str(err or ""),
                    "result_text": result_text[:8000],
                }
            elif etype == EventType.AGENT_ERROR:
                # Keep provider status and reset hints structured. Raw response
                # headers and API credentials must never enter the Build stream.
                status = int(event.data.get("status") or 0)
                error_event = {
                    "type": "error",
                    "error": str(event.data.get("error") or "worker failed"),
                    "retryable": status != 401,
                }
                code = str(event.data.get("error_code") or "")
                if status == 401:
                    error_event["provider_status"] = status
                if status == 429 or (code and status != 401):
                    from thomas.core.llm_request_admission import admission_key

                    credential = admission_key(llm.config)
                    decision = _QUOTA_CLASSIFIER.observe(
                        credential,
                        status=status,
                        error={"code": code},
                        headers=event.data.get("response_headers") or {},
                    )
                    error_event.update(
                        provider_status=status,
                        provider_credential=credential,
                        provider=str(getattr(llm.config, "provider", "") or ""),
                        quota={"kind": decision.kind, "retry_at": decision.retry_at, "reason": decision.reason},
                    )
                # The chat is told only that the worker failed -- provider errors
                # can carry detail that must not reach it -- so the real cause is
                # kept in the local issue log. Three self-fix runs on 2026-09-22
                # failed with nothing on record but "reported a retryable error".
                record_issue(
                    surface="chat-worker",
                    kind="worker_error",
                    message=error_event["error"],
                    context={"execution_id": str(execution_id or ""), "status": status, "code": code},
                )
                yield error_event
                return
            elif etype == EventType.AGENT_END:
                # Abnormal terminal state (user interruption, or a denied /
                # suspicious prompt) — the loop did NOT complete the task and does
                # NOT set state.error, so without this it would masquerade as a
                # successful "done". Report failure: failing honestly beats
                # succeeding falsely.
                reason = str(
                    event.data.get("message") or event.data.get("reason") or "worker ended before completing the task"
                )
                # Deterministic terminal state (interruption / suspicious-prompt denial):
                # NOT retryable — replaying the same prompt would just hit it again, so
                # the delegation layer should fail immediately instead of burning the
                # self-recovery budget.
                yield {"type": "error", "error": reason, "retryable": False}
                return
            elif etype == EventType.AGENT_DONE:
                final = str(event.data.get("text") or "").strip()
                # Some providers only deliver the answer in AGENT_DONE (no deltas).
                # Surface it as a text chunk so the result summary is real.
                if final and not streamed_text:
                    yield {"type": "text", "text": final}
                runtime = _successful_runtime_receipt()
                if runtime is not None:
                    yield {"type": "model_runtime", "runtime": runtime}
                yield {"type": "done"}
                return
            elif etype == EventType.STATUS:
                # The loop's own plain-language status lines — "Received your
                # update. Continuing this task.", "The provider asked Thomas to
                # pause for 20.0s; work will resume automatically." — were
                # dropped here with the diagnostic events below. So a steer that
                # the loop genuinely accepted at its next safe boundary produced
                # nothing the surface could show: the Work row stayed on "Update
                # queued for this task" for the rest of the run, and a provider
                # pause read as silence. Both are cases of "what's going on"
                # being known and not said.
                #
                # Carried as `progress`, which the delegation layer already
                # records on the execution and emits to the card, so this
                # replaces the one status line rather than appending a row.
                #
                # Not every STATUS is addressed to a person. Two carry a
                # structured diagnostic payload and a message written for the
                # model or the log -- the envelope checkpoint ("Checkpoint 3:
                # 12000 tokens used of 50000 - summarize progress so far and
                # confirm remaining work.") and the mid-run check-in ("Check-in
                # #2: 4 tool step(s), ~12,000 tokens, 90s since last check-in
                # ..."). Promoting those would replace a meaningful line like
                # "Using file.write..." with counters, which is the ugliness
                # this change exists to remove. They stay in the log.
                message = str(event.data.get("message") or "").strip()
                if "constraint_checkpoint" in event.data:
                    message = ""
                checkin = event.data.get("checkin")
                if isinstance(checkin, dict):
                    # One exception: an acknowledgement gate stops the run dead.
                    # Counters are noise, but a silent pause is worse.
                    message = (
                        "Thomas paused this task for a check-in and needs your acknowledgement to continue."
                        if checkin.get("ack_required")
                        else ""
                    )
                if message:
                    yield {"type": "progress", "text": message}
            else:
                # Lifecycle/diagnostic events (AGENT_START, AGENT_ITERATION,
                # THINKING, SECURITY_FLAG, TOOL_CALL_*_DELTA, ...) have no
                # consumer-facing payload here; log for debugging and continue.
                log.debug("worker: ignoring unmapped agent event %s", getattr(etype, "name", etype))
        # A few AgentLoop early-return paths finish immediately after the provider
        # stream closes without yielding a terminal AgentEvent. The provider trace
        # is complete by this point, so emit its receipt before the error below
        # rather than losing valid per-pass attribution.
        runtime = _successful_runtime_receipt()
        if runtime is not None:
            yield {"type": "model_runtime", "runtime": runtime}
        # A closed stream is not proof that the task completed. The parent may
        # retry this child, but it must never count as accepted work.
        log.error("worker: agent event stream ended without a terminal event")
        yield {"type": "error", "error": "agent stream ended without a terminal result", "retryable": True}
    finally:
        try:
            if budget_scope is not None:
                await budget_scope.reconcile_unscoped_usage(max(0, _session_usage_total(llm) - unscoped_usage_before))
        finally:
            try:
                if callable(getattr(agent_events, "aclose", None)):
                    await agent_events.aclose()
            finally:
                await close_llm_once()
