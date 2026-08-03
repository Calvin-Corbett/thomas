"""Core agent loop initialization and message building.

Provides core state, initialization, system-message construction, and history management.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas.agent.guidance import load_cached_purpose_brief
from thomas.agent.project_instructions import (
    discover_project_instructions,
    format_project_instructions,
)
from thomas.agent.prompt_templates import (
    build_route_system_prompt,
    format_memory_context,
)
from thomas.agent.routing import IntentRouter, RouteDecision
from thomas.core.autonomy import (
    autonomy_level_name,
    autonomy_system_directive,
    clamp_autonomy_level,
)
from thomas.core.config import AppConfig
from thomas.core.tokens import (
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tools_tokens,
    fit_messages_to_hard_cap,
    trim_messages_to_budget,
)
from thomas.library import ResearchLibrary, default_library_root
from thomas.tools.registry import ToolRegistry

try:
    from thomas.agent.context_compaction import (
        ContextCompactor,
    )
    from thomas.agent.context_compaction import (
        estimate_conversation_tokens as _compact_estimate_tokens,
    )

    _HAS_CONTEXT_COMPACTOR = True
except ImportError:
    _HAS_CONTEXT_COMPACTOR = False

if TYPE_CHECKING:
    from thomas.agent.guarded_tools import GuardedToolRunner
    from thomas.core.llm import LLMClient
    from thomas.marketplace.policy.policy import PolicyEngine
    from thomas.memory import MemoryEngine

log = logging.getLogger(__name__)

_TPM_HEADROOM_DEFAULT = 0.90


@lru_cache(maxsize=1)
def _load_purpose_text() -> str:
    """Load cached startup guidance brief (best effort)."""
    try:
        return load_cached_purpose_brief()
    except Exception:  # REVIEWED: swallow — optional feature, fallback to empty string
        # Broad catch: purpose brief is decorative context; any load failure must not break agent startup.
        log.debug("Purpose brief load failed; continuing without it.", exc_info=True)
        return ""


@dataclass
class LoopState:
    """Tracks state across agent loop iterations."""

    iteration: int = 0
    total_tool_calls: int = 0
    text_response: str = ""
    aggregate_response: str = ""
    finished: bool = False
    error: str | None = None
    token_estimate: int = 0
    user_interrupted: bool = False


class AgentLoop:
    """Async agent loop that streams events to the caller.

    Features:
    - Streaming text + tool call events
    - Parallel tool execution
    - Context window tracking with automatic trimming
    - Error recovery for failed tool calls
    - Memory context injection

    Usage:
        loop = AgentLoop(config, llm_client, tool_registry)
        async for event in loop.run("fix the bug in main.py"):
            if event.type == EventType.TEXT_DELTA:
                print(event.data["text"], end="", flush=True)
            elif event.type == EventType.TOOL_RESULT:
                print(f"[{event.data['tool_name']} -> ok={event.data['ok']}]")
    """

    def __init__(
        self,
        config: AppConfig,
        llm: LLMClient,
        tools: ToolRegistry,
        system_prompt: str | None = None,
        conversation: list[dict[str, Any]] | None = None,
        memory: MemoryEngine | None = None,
        thread_id: str | None = None,
        guarded_tool_runner: GuardedToolRunner | None = None,
        action_audit: Any | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        guardrails_event_cb: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        hook_runner: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        memory_retrieval_scope: str = "thread",
        automation_policy: PolicyEngine | None = None,
        autonomy_level: int = 3,
        max_parallel_tools: int | None = None,
        tool_timeout_s: int | None = None,
        message_queue: Any | None = None,
        non_coder_profile: bool = False,
        profile_type: str | None = None,
        review_depth: str | None = None,
    ):
        self.config = config
        self.llm = llm
        self.tools = tools
        self._system_prompt = system_prompt
        # Preserve the caller-provided list object even if it's empty.
        self._conversation = conversation if conversation is not None else []
        self._memory = memory
        resolved_thread_id = str(thread_id or "").strip()
        if not resolved_thread_id:
            resolved_thread_id = f"thread:{uuid.uuid4().hex}"
        self._thread_id = resolved_thread_id
        resolved_session_id = str(session_id or "").strip()
        self._session_id = resolved_session_id or self._thread_id
        resolved_run_id = str(run_id or "").strip()
        self._run_id = resolved_run_id or f"run:{uuid.uuid4().hex}"
        self._guarded_tool_runner = guarded_tool_runner
        self._action_audit = action_audit
        self._guardrails_event_cb = guardrails_event_cb
        # Optional caller-supplied plugin hook runner. Kept as an opaque
        # awaitable callable so thomas/agent stays decoupled from thomas/plugins
        # (the agent tier does not depend on the plugins tier). When None, all
        # hook invocation sites are no-ops. See thomas.plugins.runtime +
        # thomas.plugins.p108_plugin_hook_runner_core for the wiring.
        self._plugin_hook_runner = hook_runner
        self._automation_policy = automation_policy
        self._autonomy_level = clamp_autonomy_level(autonomy_level, default=3)
        # Bound tool execution by default so a hung tool (or a huge fan-out)
        # can't stall a turn indefinitely. The streaming chat path passes
        # explicit values; plan-mode/CLI/integrations historically passed None,
        # which the executor treated as "no timeout" + unbounded parallelism.
        # 600s is a generous backstop above any single tool's own timeout
        # (shell caps at 300s), and 6 matches the main chat path.
        default_tool_timeout_s = 600
        default_max_parallel_tools = 6
        self._max_parallel_tools: int = default_max_parallel_tools
        if max_parallel_tools is not None:
            try:
                self._max_parallel_tools = max(1, int(max_parallel_tools))
            except (ValueError, TypeError):
                self._max_parallel_tools = default_max_parallel_tools
        self._tool_timeout_s: int = default_tool_timeout_s
        if tool_timeout_s is not None:
            try:
                self._tool_timeout_s = max(1, int(tool_timeout_s))
            except (ValueError, TypeError):
                self._tool_timeout_s = default_tool_timeout_s
        raw_profile_type = str(profile_type or "").strip().lower()
        if not raw_profile_type:
            raw_profile_type = "non_coder" if bool(non_coder_profile) else "adaptive"
        self._non_coder_profile = bool(non_coder_profile)
        self._profile_type = raw_profile_type
        self._review_depth = str(review_depth or "adaptive").strip().lower() or "adaptive"
        # Respect provider/profile-declared context windows directly.
        # Use a fallback only when config is invalid (<= 0).
        context_window = int(getattr(llm.config, "context_window", 0) or 0)
        if context_window <= 0:
            fallback_window = max(int(getattr(llm.config, "max_tokens", 0) or 0) * 4, 4096)
            log.warning(
                "Invalid context window %d in model config; using fallback %d.",
                context_window,
                fallback_window,
            )
            self._context_window = fallback_window
        else:
            self._context_window = context_window
        self._router = IntentRouter()
        self._library_enabled = str(os.environ.get("THOMAS_LIBRARY_ENABLED", "1")).strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        self._library_auto_capture = str(
            os.environ.get("THOMAS_LIBRARY_AUTO_CAPTURE_RESEARCH", "1")
        ).strip().lower() not in ("0", "false", "no", "off")
        self._library: ResearchLibrary | None = None
        if self._library_enabled:
            try:
                self._library = ResearchLibrary(default_library_root(config))
            except Exception as e:  # REVIEWED: log-and-continue — optional feature, fallback gracefully
                log.warning("Library init failed: %s", e)
        scope = str(memory_retrieval_scope or "thread").strip().lower()
        self._memory_retrieval_scope = scope if scope in ("thread", "all") else "thread"
        self._message_queue = message_queue
        self._last_sanitize_flags: dict[str, bool] = {}
        self._context_preserve_mode = str(os.environ.get("THOMAS_CONTEXT_PRESERVE_MODE", "default")).strip().lower()
        # Intelligent context compaction (ContextCompactor)
        self._context_compactor: ContextCompactor | None = None
        self._last_compaction_result: Any = None
        if _HAS_CONTEXT_COMPACTOR:
            try:
                self._context_compactor = ContextCompactor(
                    llm=llm,
                    max_summary_tokens=400,
                    segment_size=8,
                )
            except Exception as e:  # REVIEWED: log-and-continue — compaction is optional
                log.debug("ContextCompactor init failed: %s", e)

    async def _run_plugin_hook(self, hook: str, payload: dict[str, Any]) -> None:
        """Invoke the optional plugin hook runner, never breaking the turn.

        Observational-only this release: any return value is ignored, and any
        exception is swallowed at debug level so a misbehaving plugin can never
        abort an agent turn. No-op when no hook runner was supplied.
        """
        runner = self._plugin_hook_runner
        if runner is None:
            return
        try:
            await runner(hook, payload)
        except Exception as e:  # REVIEWED: plugin hooks must never break a turn
            log.debug("Plugin hook %r failed (non-fatal): %s", hook, e)

    def _build_system_message(
        self,
        memory_text: str = "",
        include_purpose: bool = True,
        route_path: str = "",
        skills_context: str = "",
        include_autonomy_profile: bool = True,
        include_editing_policy: bool = True,
        include_project_instructions: bool = True,
    ) -> dict[str, Any]:
        """Build the system prompt for an LLM call."""
        import sys

        model_cfg = self.llm.config
        route = str(route_path or "")
        _low_intent_paths = {"casual_chat", "personal_context", "assistant_meta", "general"}
        _editing_policy_paths = {"coding_task", "debug_audit"}
        _project_instruction_paths = {"coding_task", "debug_audit", "research", "planning"}
        base_prompt = build_route_system_prompt(
            route_path=route,
            cwd=os.getcwd(),
            platform=sys.platform,
            model_name=getattr(model_cfg, "name", "unknown"),
            model_id=getattr(model_cfg, "model", "unknown"),
        )
        if self._system_prompt:
            # Custom personality is *prepended* to the base agent prompt so
            # execution capabilities (tools, file ops, etc.) are never lost.
            prompt = self._system_prompt.rstrip() + "\n\n" + base_prompt
        else:
            prompt = base_prompt

        purpose = _load_purpose_text() if include_purpose else ""
        if purpose:
            prompt = prompt.rstrip() + "\n\n--- Purpose Brief ---\n" + purpose + "\n--- End Purpose Brief ---\n"

        # Only inject the autonomy directive for action-oriented routes.
        # For casual/low-intent routes, the autonomy directive ("execute tasks
        # autonomously…") confuses the LLM into agent-speak instead of
        # natural conversation.
        if include_autonomy_profile and route not in _low_intent_paths:
            autonomy_lv = self._autonomy_level
            autonomy_name = autonomy_level_name(autonomy_lv)
            autonomy_directive = autonomy_system_directive(autonomy_lv)
            prompt = (
                prompt.rstrip()
                + "\n\n--- Autonomy Profile ---\n"
                + f"Level {autonomy_lv}: {autonomy_name}\n"
                + autonomy_directive
                + "\n--- End Autonomy Profile ---\n"
            )

        # Editing policy is only needed on routes that are likely to mutate files.
        if include_editing_policy and route in _editing_policy_paths:
            prompt = (
                prompt.rstrip() + "\n\n--- Editing Policy ---\n"
                "When editing existing files, prefer diff.create (find-and-replace) over fs.write_file.\n"
                "diff.create is safer: it only changes what's needed and shows exact before/after.\n"
                "Only use fs.write_file for creating entirely new files.\n"
                "--- End Editing Policy ---\n"
            )

        # Per-project instructions (THOMAS.md) are only injected for execution routes.
        if include_project_instructions and route in _project_instruction_paths:
            try:
                sandbox_root = Path(os.getcwd())
                # Bound merged instructions by the model window so small-context
                # models never lose required prompt text to project files.
                instruction_budget = max(1_200, min(24_000, int(self._context_window) // 2))
                project_content = discover_project_instructions(sandbox_root, max_chars=instruction_budget)
                if project_content:
                    prompt = prompt.rstrip() + "\n\n" + format_project_instructions(project_content)
            except Exception:
                # Broad catch: project instruction discovery is best-effort and must not block a turn.
                log.debug("Project instructions discovery failed; skipping.", exc_info=True)

        if skills_context:
            prompt = prompt.rstrip() + "\n\n" + str(skills_context).strip()

        if memory_text:
            prompt += format_memory_context(memory_text)
        return {"role": "system", "content": prompt}

    def _build_messages(
        self,
        state: LoopState,
        memory_text: str = "",
        tool_specs: list[dict[str, Any]] | None = None,
        include_purpose: bool = True,
        preserve_first: int = 1,
        preserve_last: int = 4,
        history_token_cap: int | None = None,
        route_path: str = "",
        skills_context: str = "",
        include_autonomy_profile: bool = True,
        include_editing_policy: bool = True,
        include_project_instructions: bool = True,
    ) -> list[dict[str, Any]]:
        """Build the message list for an LLM call, with context window management."""
        system_msg = self._build_system_message(
            memory_text,
            include_purpose=include_purpose,
            route_path=route_path,
            skills_context=skills_context,
            include_autonomy_profile=include_autonomy_profile,
            include_editing_policy=include_editing_policy,
            include_project_instructions=include_project_instructions,
        )
        system_tokens = estimate_message_tokens(system_msg)

        # Estimate tool spec tokens
        tools_tokens = estimate_tools_tokens(tool_specs or [])

        # Conversation history already contains the current run's messages because
        # we append them as we go.
        all_messages: list[dict[str, Any]] = list(self._conversation)
        preserve_first_i = max(0, int(preserve_first))
        preserve_last_i = max(1, int(preserve_last))

        # Route-level soft cap. This keeps casual/meta turns lightweight even when
        # the model has a huge context window and conversation history is long.
        if history_token_cap is not None and int(history_token_cap) > 0:
            soft_budget = int(history_token_cap) + system_tokens + tools_tokens + 100
            all_messages = trim_messages_to_budget(
                all_messages,
                budget=soft_budget,
                system_tokens=system_tokens,
                tools_tokens=tools_tokens,
                preserve_first=preserve_first_i,
                preserve_last=preserve_last_i,
            )

        # Trim to fit context window, preserving recent messages
        # Reserve tokens for the model's response
        response_reserve = min(self.llm.config.max_tokens, self._context_window // 4)
        budget = self._context_window - response_reserve

        trimmed = trim_messages_to_budget(
            all_messages,
            budget=budget,
            system_tokens=system_tokens,
            tools_tokens=tools_tokens,
            preserve_first=preserve_first_i,
            preserve_last=preserve_last_i,
        )

        messages = [system_msg] + trimmed
        state.token_estimate = estimate_messages_tokens(messages) + tools_tokens
        # Final context firewall. Tool schemas and the response allowance share
        # the same provider window as messages, so reserve both before trimming.
        message_hard_cap = int(self._context_window) - tools_tokens - response_reserve
        try:
            try:
                messages = fit_messages_to_hard_cap(
                    messages,
                    hard_cap=message_hard_cap,
                    anchor_source=all_messages,
                )
            except ValueError:
                # Optional context is dropped in stages, each as one complete,
                # well-formed section: merged project instructions first (bulk
                # ambient files), then retrieved memory — memory_text carries
                # deliberately injected steering (e.g. the best-practice hint),
                # so it must outlive ambient instruction files — then both.
                # Required prompt text is never cut.
                stages: list[tuple[str, bool]] = []
                if include_project_instructions:
                    stages.append((memory_text, False))
                if memory_text:
                    stages.append(("", include_project_instructions))
                if memory_text and include_project_instructions:
                    stages.append(("", False))
                if not stages:
                    raise
                for stage_index, (stage_memory, stage_instructions) in enumerate(stages):
                    messages[0] = self._build_system_message(
                        stage_memory,
                        include_purpose=include_purpose,
                        route_path=route_path,
                        skills_context=skills_context,
                        include_autonomy_profile=include_autonomy_profile,
                        include_editing_policy=include_editing_policy,
                        include_project_instructions=stage_instructions,
                    )
                    try:
                        messages = fit_messages_to_hard_cap(
                            messages,
                            hard_cap=message_hard_cap,
                            anchor_source=all_messages,
                        )
                        break
                    except ValueError:
                        if stage_index == len(stages) - 1:
                            raise
        except ValueError as exc:
            raise ValueError(
                "Model context window cannot fit the required instructions and latest request after reserving "
                f"{tools_tokens} tool-schema tokens and {response_reserve} response tokens: {exc}"
            ) from exc
        state.token_estimate = estimate_messages_tokens(messages) + tools_tokens

        return messages

    async def _auto_compact_if_needed(
        self,
        *,
        hard_cap: int | None = None,
        threshold: float = 0.75,
        preserve_recent: int = 6,
    ) -> dict[str, Any] | None:
        """Auto-compact the conversation if approaching the token budget.

        This should be called before _build_messages() in the agent loop.
        Operates on self._conversation in-place.

        Returns compaction result dict if compaction occurred, else None.
        """
        if not _HAS_CONTEXT_COMPACTOR or self._context_compactor is None:
            return None

        compact_cap = int(self._context_window) if (hard_cap is None or int(hard_cap) <= 0) else int(hard_cap)
        conv_tokens = _compact_estimate_tokens(self._conversation)
        if conv_tokens < int(compact_cap * threshold):
            return None

        log.info(
            "Auto-compaction triggered: conversation at %d tokens (%.0f%% of %d cap)",
            conv_tokens,
            (conv_tokens / compact_cap) * 100,
            compact_cap,
        )

        try:
            target = int(compact_cap * 0.55)  # Compact to ~55% to give headroom
            result = await self._context_compactor.compact(
                self._conversation,
                target_budget=target,
                preserve_recent=preserve_recent,
                use_llm=True,
            )
            self._last_compaction_result = result
            return {
                "original_tokens": result.original_tokens,
                "compacted_tokens": result.compacted_tokens,
                "tokens_saved": result.tokens_saved,
                "original_messages": result.original_message_count,
                "compacted_messages": result.compacted_message_count,
                "segments_summarized": result.segments_summarized,
                "elapsed_ms": result.elapsed_ms,
            }
        except Exception as e:
            log.warning("Auto-compaction failed: %s", e)
            return None

    def get_token_usage_info(self) -> dict[str, Any]:
        """Return current token usage info for the conversation.

        Used by the REPL to display token budget in the toolbar and
        by the /compact command.
        """
        if not _HAS_CONTEXT_COMPACTOR:
            conv_tokens = estimate_messages_tokens(self._conversation) if self._conversation else 0
            hard_cap = max(1000, int(self._context_window))
            usage_ratio = conv_tokens / max(1, hard_cap)
            return {
                "current_tokens": conv_tokens,
                "context_window": hard_cap,
                "usage_ratio": usage_ratio,
                "usage_pct": int(usage_ratio * 100),
                "message_count": len(self._conversation),
                "should_compact": usage_ratio > 0.75,
                "display": f"{conv_tokens / 1000:.1f}k" if conv_tokens >= 1000 else str(conv_tokens),
                "display_budget": f"{hard_cap / 1000:.1f}k",
            }
        return self._context_compactor.token_usage_info(
            self._conversation,
            context_window=self._context_window,
        )

    def _history_preserve_counts(self, route: RouteDecision) -> tuple[int, int]:
        """Choose how much conversation history to preserve per route."""
        path = str(getattr(route, "path", "") or "")
        # `model_owned` is not one route among several -- IntentRouter.decide() returns
        # it unconditionally (`del text, prior_route`, no branching), so it is EVERY
        # turn. When the prompt-word classifier was retired it was pasted into the
        # casual-chat branch below, which meant every real conversation ran on the
        # small-talk allowance and the coding/research branches became dead code.
        # It gets the most generous values in this function instead; the numbers are
        # the ones already here, not new ones.
        if path == "model_owned":
            return 0, 12
        if path in ("casual_chat", "personal_context", "assistant_meta", "general"):
            if self._context_preserve_mode in {"continuous", "persistent", "high_context", "chatty"}:
                return 0, 12
            return 0, 10
        if path in ("planning", "research"):
            return 0, 8
        return 0, 8

    def _history_token_cap(self, route: RouteDecision) -> int:
        """Route-specific soft cap for conversation history tokens."""
        path = str(getattr(route, "path", "") or "")
        # See _history_preserve_counts: this is every turn, not a casual one. On the
        # old grouping a coding conversation was cut to 2200 tokens of history --
        # roughly ten short messages -- so Thomas forgot a constraint set earlier in
        # the same session and the 5200 written for coding_task was never reached by
        # anything. 5200 is that same existing value, now actually reachable.
        if path == "model_owned":
            return 5200
        if path in ("casual_chat", "personal_context", "assistant_meta", "general"):
            if self._context_preserve_mode in {"continuous", "persistent", "high_context", "chatty"}:
                return 5200
            return 2200
        if path in ("planning", "research"):
            return 3200
        if path in ("coding_task", "debug_audit"):
            return 5200
        return 3000

    def _provider_tpm_limit(self) -> int:
        """Return only an explicitly configured local provider TPM policy."""
        cfg = self.llm.config
        profile_key = re.sub(r"[^A-Za-z0-9_]", "_", str(getattr(cfg, "name", "") or "").upper())
        for env_key in (
            f"THOMAS_PROVIDER_TPM_LIMIT_{profile_key}" if profile_key else "",
            "THOMAS_PROVIDER_TPM_LIMIT",
        ):
            if not env_key:
                continue
            raw = str(os.environ.get(env_key, "")).strip()
            if not raw:
                continue
            try:
                parsed = int(raw)
                if parsed > 0:
                    return parsed
            except ValueError:
                continue
        return 0

    def _provider_tpm_headroom(self) -> float:
        """Get TPM headroom multiplier from env or default."""
        raw = str(os.environ.get("THOMAS_PROVIDER_TPM_HEADROOM", "")).strip()
        if raw:
            try:
                parsed = float(raw)
                return max(0.5, min(parsed, 1.0))
            except ValueError:
                pass
        try:
            parsed_default = float(_TPM_HEADROOM_DEFAULT or 0.90)
        except (TypeError, ValueError):
            parsed_default = 0.90
        return max(0.5, min(parsed_default, 1.0))

    def _recent_tool_names(self, limit: int = 80) -> list[str]:
        """Extract recently used tool names from conversation history."""
        names: list[str] = []
        seen: set[str] = set()
        for msg in list(self._conversation or [])[-max(1, int(limit)) :]:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip().lower()
            if role == "assistant":
                tool_calls = msg.get("tool_calls")
                if isinstance(tool_calls, list):
                    for tc in tool_calls:
                        if not isinstance(tc, dict):
                            continue
                        func = tc.get("function")
                        if not isinstance(func, dict):
                            continue
                        name = str(func.get("name") or "").strip()
                        if name and name not in seen:
                            seen.add(name)
                            names.append(name)
            elif role == "tool":
                name = str(msg.get("name") or msg.get("tool_name") or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
        return names

    def _tool_usage_response(self) -> str:
        """Generate response for tool usage meta-questions."""
        names = self._recent_tool_names()
        if not names:
            return (
                "I don't see any recorded tool calls in this conversation context. "
                "So the reliable answer is: no tools were executed."
            )
        lines = [f"{idx}. `{name}`" for idx, name in enumerate(names[:20], start=1)]
        return "Based on recorded conversation events, these tools were used:\n" + "\n".join(lines)
