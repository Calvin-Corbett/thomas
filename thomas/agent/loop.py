"""Async ReAct agent loop with streaming, parallel tools, and context management.

The core execution engine for Thomas. Handles:
- Streaming LLM responses to the caller in real-time
- Parallel tool execution when tools are independent
- Context window tracking and overflow prevention via token counting
- Automatic conversation trimming when approaching context limits
- Configurable iteration limits with stop conditions
- Error recovery with retries and graceful degradation
- Memory context injection
"""

from __future__ import annotations

import asyncio
import ast
import json
import logging
import os
import re
import time
from functools import lru_cache
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from pathlib import Path

from thomas.core.config import AppConfig, load_config
from thomas.core.autonomy import (
    autonomy_level_name,
    autonomy_spec,
    autonomy_system_directive,
    clamp_autonomy_level,
)
from thomas.core.rules_of_road import evaluate_rules, build_remediation_prompt
from thomas.core.events import AgentEvent, EventType
from thomas.core.llm import LLMClient, LLMError, StreamEvent
from thomas.core.token_economy import (
    build_token_economy_meta,
    loop_context_budgets,
    loop_iteration_prompt_caps,
    loop_tool_spec_budgets,
    normalize_token_economy_level,
)
from thomas.core.tokens import (
    estimate_tokens,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tools_tokens,
    trim_messages_to_budget,
)
from thomas.agent.routing import IntentRouter, RouteDecision
from thomas.agent.guidance import load_cached_purpose_brief
from thomas.agent.prompt_templates import (
    build_route_system_prompt,
    format_input_continuity_hint,
    format_library_context,
    format_memory_context,
)
from thomas.agent.loop_tool_exec import (
    execute_tools as _execute_tools_impl,
    parse_tool_args as _parse_tool_args_impl,
)
from thomas.agent.skills_runtime import (
    format_runtime_skills_context,
    resolve_runtime_skills,
)
from thomas.agent.response_tone import (
    apply_directness_constraints,
    apply_social_tone_adjustments,
    live_test_default_hint,
    prompt_has_frustration_signal,
    prompt_requests_directness_constraints,
    strip_internal_reasoning_narration,
    strip_tool_call_artifacts,
    strip_unprompted_workspace_references,
)
from thomas.library import ResearchLibrary, default_library_root
from thomas.models.protocol import profile_prefers_always_tools
from thomas.observability import file_audit as _file_audit
from thomas.policy.types import PolicyContext, PolicyDecisionType
from thomas.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from thomas.memory import MemoryEngine
    from thomas.agent.guarded_tools import GuardedToolRunner
    from thomas.policy.policy import PolicyEngine

log = logging.getLogger(__name__)

# Maximum chars for tool results in message history (generous for
# LLMs to have enough context but prevents single results from
# dominating the context window)
_MAX_TOOL_RESULT_CHARS = 5_000
_TPM_WINDOW_SECONDS = 60.0
_TPM_HEADROOM_DEFAULT = 0.90
_TPM_MAX_AUTO_WAIT_S = 20.0
_PROVIDER_DEFAULT_TPM_LIMITS: Dict[str, int] = {
    # Common org limit seen in runtime logs for Claude API usage.
    "anthropic": 30_000,
}


@lru_cache(maxsize=1)
def _load_purpose_text() -> str:
    """Load cached startup guidance brief (best effort)."""
    try:
        return load_cached_purpose_brief()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Loop state
# ---------------------------------------------------------------------------


@dataclass
class LoopState:
    """Tracks state across agent loop iterations."""

    iteration: int = 0
    total_tool_calls: int = 0
    text_response: str = ""
    finished: bool = False
    error: Optional[str] = None
    token_estimate: int = 0
    user_interrupted: bool = False


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


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
        system_prompt: Optional[str] = None,
        conversation: Optional[List[Dict[str, Any]]] = None,
        memory: Optional[MemoryEngine] = None,
        thread_id: Optional[str] = None,
        guarded_tool_runner: Optional["GuardedToolRunner"] = None,
        action_audit: Optional[Any] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        guardrails_event_cb: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
        memory_retrieval_scope: str = "thread",
        automation_policy: Optional["PolicyEngine"] = None,
        autonomy_level: int = 3,
        max_parallel_tools: Optional[int] = None,
        tool_timeout_s: Optional[int] = None,
        message_queue: Optional["asyncio.Queue[Optional[str]]"] = None,
    ):
        self.config = config
        self.llm = llm
        self.tools = tools
        self._system_prompt = system_prompt
        # Preserve the caller-provided list object even if it's empty.
        self._conversation = conversation if conversation is not None else []
        self._memory = memory
        self._thread_id = thread_id or "default"
        self._run_id = run_id or self._thread_id
        self._session_id = session_id or self._thread_id
        self._guarded_tool_runner = guarded_tool_runner
        self._action_audit = action_audit
        self._guardrails_event_cb = guardrails_event_cb
        self._automation_policy = automation_policy
        self._autonomy_level = clamp_autonomy_level(autonomy_level, default=3)
        self._max_parallel_tools: Optional[int] = None
        if max_parallel_tools is not None:
            try:
                self._max_parallel_tools = max(1, int(max_parallel_tools))
            except Exception:
                self._max_parallel_tools = None
        self._tool_timeout_s: Optional[int] = None
        if tool_timeout_s is not None:
            try:
                self._tool_timeout_s = max(1, int(tool_timeout_s))
            except Exception:
                self._tool_timeout_s = None
        self._context_window = llm.config.context_window
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
        self._memory_curator_enabled = str(
            os.environ.get("THOMAS_MEMORY_CURATOR_ENABLED", "1")
        ).strip().lower() not in ("0", "false", "no", "off")
        self._library: Optional[ResearchLibrary] = None
        if self._library_enabled:
            try:
                self._library = ResearchLibrary(default_library_root(config))
            except Exception as e:
                log.warning("Library init failed: %s", e)
        scope = str(memory_retrieval_scope or "thread").strip().lower()
        self._memory_retrieval_scope = scope if scope in ("thread", "all") else "thread"
        self._message_queue = message_queue
        self._last_sanitize_flags: Dict[str, bool] = {}

    def _build_system_message(
        self,
        memory_text: str = "",
        include_purpose: bool = True,
        route_path: str = "",
        skills_context: str = "",
    ) -> Dict[str, Any]:
        import sys

        model_cfg = self.llm.config
        base_prompt = build_route_system_prompt(
            route_path=str(route_path or ""),
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
            prompt = (
                prompt.rstrip()
                + "\n\n--- Purpose Brief ---\n"
                + purpose
                + "\n--- End Purpose Brief ---\n"
            )

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

        if skills_context:
            prompt = prompt.rstrip() + "\n\n" + str(skills_context).strip()

        if memory_text:
            prompt += format_memory_context(memory_text)
        return {"role": "system", "content": prompt}

    def _build_messages(
        self,
        state: LoopState,
        memory_text: str = "",
        tool_specs: Optional[List[Dict[str, Any]]] = None,
        include_purpose: bool = True,
        preserve_first: int = 1,
        preserve_last: int = 4,
        history_token_cap: Optional[int] = None,
        route_path: str = "",
        skills_context: str = "",
    ) -> List[Dict[str, Any]]:
        """Build the message list for an LLM call, with context window management."""
        system_msg = self._build_system_message(
            memory_text,
            include_purpose=include_purpose,
            route_path=route_path,
            skills_context=skills_context,
        )
        system_tokens = estimate_message_tokens(system_msg)

        # Estimate tool spec tokens
        tools_tokens = estimate_tools_tokens(tool_specs or [])

        # Conversation history already contains the current run's messages because
        # we append them as we go.
        all_messages: List[Dict[str, Any]] = list(self._conversation)
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
        # HARD SAFETY CAP: 28k tokens (for Tier 1 30k limit)
        # This is the final firewall. If we are over this, we MUST trim,
        # regardless of what the config or memory says.
        HARD_CAP = 28000
        while estimate_messages_tokens(messages) > HARD_CAP and len(messages) > 2:
            # Drop the oldest message (after system prompt)
            # We keep index 0 (system) and index -1 (latest user query/tool result) ideally,
            # but here we just pop from index 1 (oldest conversation history)
            messages.pop(1)
        state.token_estimate = estimate_messages_tokens(messages) + tools_tokens
            
        return messages

    def _history_preserve_counts(self, route: RouteDecision) -> tuple[int, int]:
        """Choose how much conversation history to preserve per route."""
        path = str(getattr(route, "path", "") or "")
        if path in ("casual_chat", "personal_context", "assistant_meta", "general"):
            return 0, 10
        if path in ("planning", "research"):
            return 0, 8
        return 0, 8

    def _history_token_cap(self, route: RouteDecision) -> int:
        """Route-specific soft cap for conversation history tokens."""
        path = str(getattr(route, "path", "") or "")
        if path in ("casual_chat", "personal_context", "assistant_meta", "general"):
            return 2200
        if path in ("planning", "research"):
            return 3200
        if path in ("coding_task", "debug_audit"):
            return 5200
        return 3000

    def _provider_tpm_limit(self) -> int:
        """Best-effort provider prompt-token per-minute limit."""
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
            except Exception:
                continue
        provider = str(getattr(cfg, "provider", "") or "").strip().lower()
        return int(_PROVIDER_DEFAULT_TPM_LIMITS.get(provider, 0))

    def _provider_tpm_headroom(self) -> float:
        raw = str(os.environ.get("THOMAS_PROVIDER_TPM_HEADROOM", "")).strip()
        if raw:
            try:
                parsed = float(raw)
                return max(0.5, min(parsed, 1.0))
            except Exception:
                pass
        return float(_TPM_HEADROOM_DEFAULT)

    @staticmethod
    def _has_explicit_action_intent(prompt: str) -> bool:
        return bool(
            re.search(
                r"\b("
                r"run|execute|edit|write|create|delete|remove|install|apply|patch|commit"
                r"|open|search|find|read|fix|debug|build|deploy"
                r"|make|change|update|modify|add|set|adjust|move|resize|implement"
                r"|refactor|rename|replace|merge|revert|undo|redo|configure|setup"
                r"|check|look|show|list|scan|analyze|locate|explore|inspect|test"
                r"|start|stop|restart|enable|disable|toggle|switch|connect|send"
                r"|download|upload|fetch|pull|push|sync|copy|paste|duplicate|clone"
                r"|convert|transform|generate|scaffold|migrate|optimize|clean|format"
                r"|put|do|help|handle|process|use|try|give|tell|explain"
                r")\b",
                str(prompt or "").lower(),
            )
        )

    @staticmethod
    def _is_low_intent_route(path: str) -> bool:
        return str(path or "") in ("casual_chat", "assistant_meta", "personal_context", "general")

    @staticmethod
    def _is_tool_usage_question(prompt: str) -> bool:
        src = str(prompt or "").strip().lower()
        if not src:
            return False
        if "tool" not in src:
            return False
        if not any(k in src for k in ("use", "used", "using", "call", "called", "try", "tried")):
            return False
        return any(k in src for k in ("what", "which", "did you", "tell me", "list", "show"))

    def _recent_tool_names(self, limit: int = 80) -> List[str]:
        names: List[str] = []
        seen: set[str] = set()
        for msg in list(self._conversation or [])[-max(1, int(limit)):]:
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
        names = self._recent_tool_names()
        if not names:
            return (
                "I don’t see any recorded tool calls in this conversation context. "
                "So the reliable answer is: no tools were executed."
            )
        lines = [f"{idx}. `{name}`" for idx, name in enumerate(names[:20], start=1)]
        return "Based on recorded conversation events, these tools were used:\n" + "\n".join(lines)

    def _latest_assistant_message(self) -> str:
        """Return most recent assistant text message from conversation history."""
        for msg in reversed(list(self._conversation or [])):
            if not isinstance(msg, dict):
                continue
            if str(msg.get("role") or "").strip().lower() != "assistant":
                continue
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        return ""

    def _is_ack_turn(self, text: str) -> bool:
        s = str(text or "").strip().lower()
        if not s:
            return False
        words = re.findall(r"[a-z0-9']+", s)
        if len(s) <= 20 and s in {
            "ok",
            "okay",
            "sure",
            "yes",
            "yep",
            "yeah",
            "continue",
            "go",
            "go ahead",
            "proceed",
            "do it",
            "sounds good",
            "works",
        }:
            return True
        if len(words) > 4:
            return False
        return bool(re.fullmatch(r"(ok|okay|sure|yes|yep|yeah|continue|go ahead|proceed|do it)", s))
    def _looks_like_requested_input(self, text: str) -> bool:
        s = str(text or "").strip()
        if not s:
            return False
        token_like = bool(re.search(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b", s))
        numeric_id_like = bool(re.fullmatch(r"\s*-?\d{5,}\s*", s))
        return token_like or numeric_id_like

    def _is_blocked_response(self, text: str) -> bool:
        s = str(text or "").strip().lower()
        if not s:
            return False
        return bool(
            re.search(
                r"\b("
                r"i(?: still)? need|"
                r"please provide|"
                r"cannot proceed|"
                r"can't proceed|"
                r"unable to continue|"
                r"to continue,?|"
                r"before i can|"
                r"missing|"
                r"i require"
                r")\b",
                s,
            )
        )
    def _strip_premature_followup(self, text: str) -> tuple[str, bool]:
        src = str(text or "")
        if not src.strip():
            return src, False

        # Remove standalone follow-up lines that frequently derail in-progress tasks.
        line_patterns = (
            r"^\s*anything else\??\s*$",
            r"^\s*what(?:'s| is)? next\??\s*$",
            r"^\s*what would you like (?:me )?to do next\??\s*$",
            r"^\s*what do you want(?: me)? to do next\??\s*$",
            r"^\s*how can i help(?: you)?(?: further)?\??\s*$",
            r"^\s*how can i assist(?: you)?(?: [a-z]+){0,4}\??\s*$",
            r"^\s*what can i help with\??\s*$",
        )
        removed = False
        lines: List[str] = []
        for line in src.splitlines():
            if any(re.search(p, line, re.I) for p in line_patterns):
                removed = True
                continue
            lines.append(line)
        out = "\n".join(lines)

        # Remove trailing generic follow-up question at end of a sentence.
        trailing = re.compile(
            r"(?:\s*(?:anything else\??|what(?:'s| is)? next\??|what would you like (?:me )?to do next\??|what do you want(?: me)? to do next\??|how can i help(?: you)?(?: further)?\??|how can i assist(?: you)?(?: [a-z]+){0,4}\??|what can i help with\??)\s*)+$",
            re.I,
        )
        new_out = trailing.sub("", out).rstrip()
        if new_out != out:
            removed = True
            out = new_out
        return (out if out.strip() else src), removed
    def _sanitize_assistant_text(
        self,
        text: str,
        *,
        prompt_text: str,
        route: RouteDecision,
        route_input_source: str,
        pending_tool_calls: int,
    ) -> tuple[str, bool]:
        """Apply response hygiene: remove thought leakage + premature follow-ups."""
        src = str(text or "")
        if not src.strip():
            return src, False
        self._last_sanitize_flags = {}
        if pending_tool_calls > 0:
            return src, False
        blocked_response = self._is_blocked_response(src)
        path = str(getattr(route, "path", "") or "")
        action_path = path in ("coding_task", "debug_audit", "planning", "research")
        continuation_turn = route_input_source == "history_augmented" or self._is_ack_turn(prompt_text)
        frustrated_turn = prompt_has_frustration_signal(prompt_text)
        changed = False
        out = src
        flags = {
            "followup": False,
            "thought_leak": False,
            "tool_artifact": False,
            "directness": False,
            "social": False,
            "workspace": False,
        }

        if (action_path or continuation_turn or frustrated_turn) and not blocked_response:
            out, removed = self._strip_premature_followup(out)
            if removed:
                flags["followup"] = True
                changed = True

        out, thought_changed = strip_internal_reasoning_narration(out, prompt_text=prompt_text)
        if thought_changed:
            flags["thought_leak"] = True
            changed = True

        out, artifact_changed = strip_tool_call_artifacts(out, prompt_text=prompt_text)
        if artifact_changed:
            flags["tool_artifact"] = True
            changed = True

        if not blocked_response:
            out, directness_changed = apply_directness_constraints(out, prompt_text=prompt_text)
            if directness_changed:
                flags["directness"] = True
                changed = True

        out, social_changed = apply_social_tone_adjustments(out, prompt_text=prompt_text)
        if social_changed:
            flags["social"] = True
            changed = True
        if self._is_low_intent_route(path):
            out, path_changed = strip_unprompted_workspace_references(out, prompt_text=prompt_text)
            if path_changed:
                flags["workspace"] = True
                changed = True
        self._last_sanitize_flags = flags
        return out, changed
    @staticmethod
    def _looks_like_clarifying_question(text: str) -> bool:
        src = str(text or "").strip()
        if not src:
            return False
        low = src.lower()

        # Strong signals that the model is asking the user to clarify.
        has_question_shape = "?" in src or bool(
            re.search(
                r"\b(which|what|where|when|who|can you|could you|would you|do you want|should i|please provide)\b",
                low,
            )
        )
        if not has_question_shape:
            return False

        # If the model is explicitly blocked by credentials/permissions/secrets,
        # this can be a legitimate question and should not be force-suppressed.
        if re.search(
            r"\b(api key|token|password|credential|auth|permission|access|secret|login|otp|code)\b",
            low,
        ):
            return False
        if re.search(r"\b(cannot|can't|unable|impossible|missing|not available)\b", low):
            return False
        return True
    @staticmethod
    def _full_auto_nudge(prompt_text: str, retry_index: int) -> str:
        return (
            "Autonomy level 4 is enabled. Do not ask clarifying questions for this task unless "
            "it is genuinely impossible or unsafe. Inspect available context, choose sensible defaults, "
            "execute now, and report concrete actions taken. "
            f"(full_auto_retry={int(retry_index)}; original_request={prompt_text[:220]})"
        )
    @staticmethod
    def _assume_and_proceed_nudge(
        prompt_text: str,
        *,
        retry_index: int,
        question_cap: int,
        questions_seen: int,
        route_input_source: str,
    ) -> str:
        return (
            "Continue execution now. Do not ask another clarifying question unless it is truly blocked by "
            "missing credentials, access, or unsafe constraints. Assume sensible defaults, state assumptions "
            "briefly, and proceed with concrete actions. "
            f"(clarification_retry={int(retry_index)}; clarification_cap={int(question_cap)}; "
            f"clarification_seen={int(questions_seen)}; route_input_source={str(route_input_source or 'prompt_only')}; "
            f"original_request={prompt_text[:220]})"
        )

    def _routing_input_text(self, prompt_text: str) -> tuple[str, str]:
        """Optionally augment routing input with prior assistant context on follow-ups."""
        src = str(prompt_text or "").strip()
        if not src:
            return src, "prompt_only"
        prev_assistant = self._latest_assistant_message()
        if not prev_assistant:
            return src, "prompt_only"
        prev_l = prev_assistant.lower()
        is_follow_up = self._is_ack_turn(src) or self._looks_like_requested_input(src)
        if not is_follow_up:
            return src, "prompt_only"
        action_context = bool(
            re.search(
                r"\b(set ?up|setup|install|configure|connect|integrat|deploy|fix|implement|run|audit|test|refactor|token|chat id|user id|bot id)\b",
                prev_l,
            )
            or re.search(
                r"\b(please provide|send|share|which|what|where)\b",
                prev_l,
            )
        )
        if not action_context:
            return src, "prompt_only"
        routed = f"{prev_assistant}\nUser reply: {src}"
        return routed, "history_augmented"

    def _input_continuity_hint(self, prompt_text: str) -> str:
        """Infer whether the user just supplied data requested in the prior turn."""
        src = str(prompt_text or "").strip()
        if not src:
            return ""
        prev_assistant = self._latest_assistant_message()
        if not prev_assistant:
            return ""

        prev_l = prev_assistant.lower()
        src_l = src.lower()
        hints: List[str] = []

        # If the assistant asked for Telegram token and the user sent a token-like payload,
        # force continuity so the model treats this as the requested answer.
        token_like = bool(re.search(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b", src))
        if ("telegram" in prev_l or "botfather" in prev_l) and "token" in prev_l and token_like:
            hints.append("User likely provided the Telegram bot token you requested.")

        id_requested = any(k in prev_l for k in ("chat id", "user id", "bot id", "allowed chat", "which id"))
        numeric_id_like = bool(re.fullmatch(r"\s*-?\d{5,}\s*", src))
        if id_requested and numeric_id_like:
            hints.append("User likely provided the numeric ID you requested.")

        if "you asked me" in src_l and ("id" in src_l or "token" in src_l):
            hints.append("Do not re-ask the same field; acknowledge prior request and continue.")

        if not hints:
            return ""
        return format_input_continuity_hint("\n".join(f"- {h}" for h in hints)).strip()

    def _retrieve_memory(
        self,
        prompt: str,
        mode: str = "auto",
        *,
        budget_override: Optional[int] = None,
    ) -> str:
        """Retrieve memory context for the prompt (if memory engine available)."""
        if self._memory is None or not self._memory.started:
            return ""
        try:
            budget = max(300, int(budget_override or self.config.memory.context_budget))
            query_thread: Optional[str] = None if self._memory_retrieval_scope == "all" else self._thread_id
            ctx = self._memory.retrieve(
                query=prompt,
                thread=query_thread,
                budget=budget,
                mode=mode,
            )
            return ctx.text
        except Exception as e:
            log.warning("Memory retrieval failed: %s", e)
            return ""

    def _apply_memory_policy(self, route: RouteDecision) -> None:
        """Apply per-turn memory policy to backends that support it."""
        if self._memory is None or not self._memory.started:
            return

        setter = getattr(self._memory, "set_thread_memory_policy", None)
        if not callable(setter):
            return

        include_global = bool(route.memory_include_global)
        include_profile = bool(route.memory_include_profile)
        budget_tokens = max(300, int(route.memory_budget_tokens))

        getter = getattr(self._memory, "thread_memory_policy", None)
        if callable(getter):
            try:
                current = getter(self._thread_id)
                if isinstance(current, dict):
                    include_global = include_global and bool(current.get("include_global", True))
                    include_profile = include_profile and bool(current.get("include_profile", True))
                    current_budget = current.get("max_pack_tokens")
                    if isinstance(current_budget, int) and current_budget > 0:
                        budget_tokens = min(budget_tokens, int(current_budget))
            except Exception as e:
                log.debug("Unable to inspect existing memory policy for %s: %s", self._thread_id, e)

        try:
            setter(
                self._thread_id,
                enabled=True,
                include_global=include_global,
                include_profile=include_profile,
                pins_only=False,
                max_pack_tokens=budget_tokens,
            )
        except Exception as e:
            log.warning("Memory policy apply failed: %s", e)

    def _retrieve_library(self, prompt: str, route: RouteDecision) -> str:
        """Retrieve context from the long-form research library."""
        lib = self._library
        if lib is None:
            return ""
        if route.path not in ("research", "planning", "debug_audit", "coding_task"):
            return ""
        q = str(prompt or "").strip()
        if not q:
            return ""
        try:
            budget = max(250, int(route.memory_budget_tokens // 2))
            text = lib.build_context(query=q, max_tokens=budget, limit=4)
            if not text:
                return ""
            return format_library_context(text)
        except Exception as e:
            log.debug("Library retrieval failed: %s", e)
            return ""

    # Routes whose answers are worth auto-capturing into the library.
    _LIBRARY_CAPTURE_ROUTES = frozenset({"research", "planning", "debug_audit", "coding_task"})
    # Non-research routes need a longer answer to be worth persisting.
    _LIBRARY_CAPTURE_MIN_CHARS = {"research": 80, "planning": 200, "debug_audit": 200, "coding_task": 300}

    def _auto_capture_research(self, *, route: RouteDecision, query: str, answer: str) -> None:
        """Persist research-heavy answers into the external library."""
        if not self._library_auto_capture:
            return
        rpath = str(route.path or "")
        if rpath not in self._LIBRARY_CAPTURE_ROUTES:
            return
        lib = self._library
        if lib is None:
            return
        q = str(query or "").strip()
        a = str(answer or "").strip()
        min_chars = self._LIBRARY_CAPTURE_MIN_CHARS.get(rpath, 200)
        if len(q) < 5 or len(a) < min_chars:
            return
        try:
            lib.add_research_note(
                query=q,
                answer=a,
                source=f"thomas:{getattr(self.llm.config, 'name', 'unknown')}",
                tags=["research", "auto", f"route:{rpath}"],
            )
        except Exception as e:
            log.debug("Library auto-capture skipped: %s", e)

    def _record_event(self, etype: str, text: str) -> None:
        """Record an event in memory (if memory engine available)."""
        if self._memory is None or not self._memory.started:
            return
        try:
            self._memory.add_event(self._thread_id, etype, text)
        except Exception as e:
            log.warning("Memory record failed: %s", e)

    async def _audit_action(
        self,
        *,
        kind: str,
        tool_call_id: str = "",
        tool_name: str = "",
        decision: str = "",
        reason: str = "",
        payload: Any = None,
    ) -> None:
        """Best-effort action audit event for tool lifecycle tracing."""
        audit = self._action_audit
        if audit is None:
            return
        try:
            await audit.log_async(
                kind=kind,
                run_id=self._run_id,
                session_id=self._session_id,
                tool_call_id=str(tool_call_id or ""),
                tool_name=str(tool_name or ""),
                decision=str(decision or ""),
                reason=str(reason or ""),
                payload=payload if payload is not None else {},
            )
        except Exception as e:
            log.debug("action audit failed (%s/%s): %s", kind, tool_name, e)

    def _capture_profile_hints(self, text: str) -> None:
        """Promote stable user hints into global pins for cross-session continuity."""
        if self._memory is None or not self._memory.started:
            return
        if not text:
            return

        def _norm(v: str, max_len: int = 200) -> str:
            cleaned = " ".join(v.strip().split())
            return cleaned[:max_len].strip()

        updates: Dict[str, str] = {}

        m_name = re.search(r"\b(?:my name is|i am|i'm)\s+([A-Za-z][A-Za-z0-9_\-]{1,32})\b", text, re.I)
        if m_name:
            updates["user.name"] = _norm(m_name.group(1), max_len=40)

        m_call = re.search(r"\bcall me\s+([A-Za-z][A-Za-z0-9_\-]{1,32})\b", text, re.I)
        if m_call:
            updates["user.preferred_name"] = _norm(m_call.group(1), max_len=40)

        m_pref = re.search(r"\bi (?:prefer|like|want)\s+(.+?)(?:[.!?]|$)", text, re.I)
        if m_pref:
            updates["user.preference"] = _norm(m_pref.group(1))

        m_goal = re.search(r"\b(?:my goal is|i need to|i want to)\s+(.+?)(?:[.!?]|$)", text, re.I)
        if m_goal:
            updates["user.current_goal"] = _norm(m_goal.group(1))

        if not updates:
            return

        try:
            for key, value in updates.items():
                if value:
                    self._memory.pin(key, value)
        except Exception as e:
            log.warning("Profile hint capture failed: %s", e)

    def _build_token_report(
        self,
        *,
        prompt_text: str,
        usage_obj: Dict[str, int],
        mode: str,
        iterations: int,
        peak_context_tokens: int,
        avg_context_tokens: int,
        memory_tokens: int,
        tool_chars_total: int,
        tool_chars_kept: int,
    ) -> Dict[str, Any]:
        prompt_tokens = int(usage_obj.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage_obj.get("completion_tokens", 0) or 0)
        total_tokens = int(usage_obj.get("total_tokens", 0) or 0)

        tool_chars_dropped = max(0, int(tool_chars_total) - int(tool_chars_kept))
        tool_drop_ratio = (tool_chars_dropped / tool_chars_total) if tool_chars_total > 0 else 0.0
        prompt_to_completion = (prompt_tokens / max(1, completion_tokens))
        memory_share = (memory_tokens / max(1, peak_context_tokens))

        flags: List[Dict[str, str]] = []
        suggestions: List[str] = []

        if prompt_to_completion >= 3.0 and prompt_tokens >= 1_200:
            flags.append({
                "kind": "prompt_overhead",
                "severity": "high",
                "detail": "Prompt tokens are much higher than completion tokens.",
            })
            suggestions.append("Trim conversation aggressively or reduce memory context budget.")

        if memory_share >= 0.35 and memory_tokens >= 600:
            flags.append({
                "kind": "memory_overhead",
                "severity": "medium",
                "detail": "Memory context is consuming a large fraction of prompt context.",
            })
            suggestions.append("Lower memory context budget or tighten memory retrieval mode.")

        if tool_drop_ratio >= 0.30 and tool_chars_total >= 8_000:
            flags.append({
                "kind": "tool_output_waste",
                "severity": "medium",
                "detail": "Large tool outputs were generated but heavily truncated.",
            })
            suggestions.append("Request narrower file ranges and more targeted tool outputs.")

        if peak_context_tokens >= int(self._context_window * 0.85):
            flags.append({
                "kind": "context_pressure",
                "severity": "high",
                "detail": "Context window was near capacity.",
            })
            suggestions.append("Use fast mode for simple turns and avoid oversized attachments.")

        if not suggestions:
            suggestions.append("Token usage is healthy for this turn.")

        return {
            "mode": mode,
            "iterations": int(iterations),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "peak_context_tokens": int(peak_context_tokens),
            "avg_context_tokens": int(avg_context_tokens),
            "memory_context_tokens": int(memory_tokens),
            "tool_output_chars_total": int(tool_chars_total),
            "tool_output_chars_kept": int(tool_chars_kept),
            "tool_output_chars_dropped": int(tool_chars_dropped),
            "prompt_to_completion_ratio": round(prompt_to_completion, 3),
            "memory_share_of_context": round(memory_share, 3),
            "tool_drop_ratio": round(tool_drop_ratio, 3),
            "flags": flags,
            "suggestions": suggestions,
            "prompt_chars": len(prompt_text or ""),
        }

    @staticmethod
    def _normalize_usage(prompt_tokens: Any, completion_tokens: Any, total_tokens: Any) -> Dict[str, int]:
        try:
            prompt = max(0, int(prompt_tokens or 0))
        except (TypeError, ValueError):
            prompt = 0
        try:
            completion = max(0, int(completion_tokens or 0))
        except (TypeError, ValueError):
            completion = 0
        try:
            total = max(0, int(total_tokens or 0))
        except (TypeError, ValueError):
            total = 0
        total = max(total, prompt + completion)
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        }

    def _session_usage_snapshot(self) -> Dict[str, int]:
        usage = getattr(self.llm, "session_usage", None)
        return self._normalize_usage(
            getattr(usage, "prompt_tokens", 0),
            getattr(usage, "completion_tokens", 0),
            getattr(usage, "total_tokens", 0),
        )

    def _usage_from_event_payload(self, payload: Any) -> Dict[str, int]:
        if isinstance(payload, dict):
            return self._normalize_usage(
                payload.get("prompt_tokens", 0),
                payload.get("completion_tokens", 0),
                payload.get("total_tokens", 0),
            )
        return self._normalize_usage(
            getattr(payload, "prompt_tokens", 0),
            getattr(payload, "completion_tokens", 0),
            getattr(payload, "total_tokens", 0),
        )

    def _usage_delta(self, before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
        return self._normalize_usage(
            int(after.get("prompt_tokens", 0) or 0) - int(before.get("prompt_tokens", 0) or 0),
            int(after.get("completion_tokens", 0) or 0) - int(before.get("completion_tokens", 0) or 0),
            int(after.get("total_tokens", 0) or 0) - int(before.get("total_tokens", 0) or 0),
        )

    def _select_tools(
        self,
        prompt: str,
        policy: str = "auto",
        route: Optional[RouteDecision] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Select tool exposure policy with Smart Lazy Loading.
        
        To prevent token bloat (30k/turn), we only load:
        1. Core tools (always useful)
        2. Contextually relevant tools (via semantic search)
        
        policy:
          - "never": never expose tools
          - "always": use broader selection, but still cap to prevent overflow
          - "auto": heuristic based on prompt content
        """
        if len(self.tools) == 0:
            return None

        if policy == "never":
            return None

        remote_profile = profile_prefers_always_tools(self.llm.config)
        explicit_action = self._has_explicit_action_intent(prompt)
        project_related = self._is_project_related_prompt(prompt)
        if policy == "auto" and route is not None:
            low_intent_route = self._is_low_intent_route(route.path)
            if low_intent_route and not explicit_action and not project_related and not remote_profile:
                # Keep casual/meta turns lightweight for LOCAL models only.
                # Remote/API models can handle tool definitions cheaply, and
                # suppressing tools when the user wants action is far worse than
                # the token cost of including them.
                return None

        # 1. Identify Core Tools (Always included in Auto/Always)
        # These are essential for basic agent function.
        core_patterns = {
            "fs.read", "fs.write", "fs.list", "fs.search", # Filesystem
            "memory.", # Memory
            "proc.run", # Terminals
            "code.search", "code.view", # Codebase
            "obs.screenshot", # Vision (lightweight)
        }
        
        all_tools = self.tools.list_tools()
        core_tools = []
        other_tools = []
        
        for t in all_tools:
            # Check if matching core pattern
            is_core = False
            t_name = t.name.lower()
            for p in core_patterns:
                if p in t_name:
                    is_core = True
                    break
            if is_core:
                core_tools.append(t)
            else:
                other_tools.append(t)

        # 2. Determine Budget for "Extra" Tools
        # REMOVED: fast-pass for < 40 tools. We now ALWAYS filter to be safe.
        # The user reported "tried using all tools again" which suggests 39 tools
        # might still be 15k tokens if they are large ones.
        
        # 3. Smart Selection (Semantic Search)
        # If we have too many tools, we MUST select relevant ones.
        
        # In 'Always' mode or specific routes, we are generous.
        # In 'Casual' or irrelevant prompts, we are strict.
        
        target_extra_count = 12
        if policy == "always":
            target_extra_count = 24
        elif route and route.path in ("coding_task", "debug_audit"):
            target_extra_count = 18
        
        # Search for relevance
        # Use a generous limit for search to get candidates
        relevant_candidates = self.tools.search(prompt, limit=target_extra_count)
        
        # Combine Core + Relevant
        # Use a dictionary to dedup by name
        final_selection = {t.name: t for t in core_tools}
        for t in relevant_candidates:
            final_selection[t.name] = t
            
        # 4. Fallback for "Project Related" prompts
        # If the prompt mentions specific domains not caught by search, add them?
        # The search() method handles keyword overlap, so it should catch "browser" or "database".
        
        # 5. Guarded Mode (Autonomy 2) check
        # If in guarded mode and policy is auto, only return if explicit intent is impactful.
        # (Preserving original logic)
        if (
            not final_selection
            and route is not None
            and route.path in ("coding_task", "debug_audit", "planning", "research")
            and policy in ("auto", "always")
            and not (self._is_low_intent_route(route.path) and not explicit_action)
        ):
            fallback_count = min(len(all_tools), max(1, target_extra_count))
            for t in all_tools[:fallback_count]:
                final_selection[t.name] = t

        if self._autonomy_level == 2 and policy == "auto":
            if not explicit_action and not project_related:
                # In guarded mode, if no clear intent, hide tools (except maybe read-only?)
                # For now preserving strictness: return None
                return None

        if (
            not final_selection
            and remote_profile
            and policy in ("auto", "always")
            and (explicit_action or project_related or (route and route.path in ("coding_task", "debug_audit", "planning", "research")))
            and not (route is not None and self._is_low_intent_route(route.path) and not explicit_action)
        ):
            # Remote/API profiles should still have tool access when the task is action-oriented.
            fallback_count = min(len(all_tools), max(1, target_extra_count))
            for t in all_tools[:fallback_count]:
                final_selection[t.name] = t

        if not final_selection:
            return None

        # Convert to OpenAI specs
        return [t.get_spec().to_openai() for t in final_selection.values()]

    def _is_project_related_prompt(self, prompt: str) -> bool:
        """Heuristic for whether a prompt likely needs repo/project context."""
        if not prompt:
            return False

        # Obvious coding/project signals
        keywords = (
            "code", "bug", "error", "traceback", "stack", "exception",
            "repo", "project", "file", "folder", "directory", "path",
            "function", "class", "refactor", "test", "build", "run",
            "compile", "install", "package", "pip", "npm", "yarn", "pnpm",
            "git", "diff", "patch", "fix", "crash", "log", "debug",
            "setup", "set up", "configure", "integration", "integrate",
            "deploy", "telegram", "discord", "slack", "bot", "token",
        )
        prompt_l = prompt.lower()
        if any(k in prompt_l for k in keywords):
            return True

        # File-ish patterns (paths, extensions)
        if re.search(r"[A-Za-z]:\\\\|/|\\\\|\\.py\\b|\\.js\\b|\\.ts\\b|\\.json\\b|\\.toml\\b|\\.md\\b", prompt):
            return True
        return False

    async def run(
        self,
        prompt: Any,
        *,
        mode: str = "auto",
        tools_policy: str = "auto",
        token_economy: str = "optimal",
        max_iterations: Optional[int] = None,
        job_type: Optional[str] = None,
        _quality_retry_count: int = 0,
        _quality_carry_forward_events: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent loop, yielding events as they occur.

        The loop:
        1. Build messages with context window management
        2. Stream LLM response, yielding tokens to caller in real-time
        3. If tool calls detected, execute them (parallel when independent)
        4. Append tool results, loop back to LLM
        5. Stop on: no tool calls, max iterations, context overflow, or error
        """
        # Extract plain text for heuristics/memory even if prompt is multimodal.
        prompt_text = prompt if isinstance(prompt, str) else ""
        if isinstance(prompt, list):
            for part in prompt:
                if isinstance(part, dict) and part.get("type") == "text":
                    prompt_text += str(part.get("text", "")) + "\n"
            prompt_text = prompt_text.strip()

        # Suspicious prompt gate: if the prompt matches jailbreak/extraction patterns,
        # require Windows PIN before continuing. Abort if denied.
        try:
            from thomas.tools.windows_auth import gate_suspicious_prompt, check_prompt_suspicious
            is_suspicious, matched_pattern = check_prompt_suspicious(prompt_text)
            if is_suspicious:
                log.warning("Suspicious prompt detected (matched: %r). Requiring PIN.", matched_pattern)
                yield AgentEvent(
                    type=EventType.SECURITY_FLAG,
                    data={
                        "flag": "suspicious_prompt",
                        "matched_pattern": matched_pattern[:100],
                        "message": "This request matched a suspicious pattern. Windows PIN required to proceed.",
                    },
                )
                # Pass precomputed result — avoids running the regex a second time
                authorized = gate_suspicious_prompt(
                    prompt_text,
                    action_description="Proceed with flagged request",
                    precomputed=(is_suspicious, matched_pattern),
                )
                if not authorized:
                    yield AgentEvent(
                        type=EventType.AGENT_END,
                        data={
                            "reason": "suspicious_prompt_denied",
                            "message": "Request blocked: Windows PIN not entered or incorrect.",
                        },
                    )
                    return
                log.info("Suspicious prompt authorized via Windows PIN.")
        except Exception as e:
            log.debug("Suspicious prompt gate check failed (non-fatal): %s", e)

        route_input, route_input_source = self._routing_input_text(prompt_text)
        route = self._router.decide(
            route_input,
            requested_mode=mode,
            requested_tools_policy=tools_policy,
        )
        autonomy = autonomy_spec(self._autonomy_level)
        autonomy_name = str(autonomy.name)
        effective_mode = route.mode
        applied_token_economy = normalize_token_economy_level(token_economy)
        token_economy_meta = build_token_economy_meta(token_economy, applied_token_economy)
        runtime_skills_context = ""
        runtime_skills_payload: Dict[str, Any] = {
            "enabled": False,
            "discovered_count": 0,
            "selected_count": 0,
            "explicit_mentions": [],
            "pinned_matches": [],
            "roots": [],
            "selected": [],
        }
        try:
            runtime_skills = resolve_runtime_skills(
                self.config,
                prompt_text=prompt_text,
                relevance_text=route_input,
                route_path=str(route.path or ""),
                cwd=Path.cwd(),
            )
            runtime_skills_context = format_runtime_skills_context(runtime_skills)
            runtime_skills_payload = runtime_skills.to_event_payload()
        except Exception as e:
            log.warning("Runtime skills resolution failed: %s", e)
            runtime_skills_payload["error"] = f"{type(e).__name__}: {e}"
        usage_before = self._session_usage_snapshot()
        stream_usage = self._normalize_usage(0, 0, 0)

        if self._is_tool_usage_question(prompt_text):
            preserve_first, preserve_last = self._history_preserve_counts(route)
            history_token_cap = self._history_token_cap(route)
            answer = self._tool_usage_response()

            yield AgentEvent(
                type=EventType.AGENT_START,
                data={
                    "prompt": prompt_text,
                    "route": route.to_dict(),
                    "route_input_source": route_input_source,
                    "mode": effective_mode,
                    "tools_policy": "never",
                    "autonomy_level": int(self._autonomy_level),
                    "autonomy_name": autonomy_name,
                    "token_economy": token_economy_meta,
                    "library_enabled": bool(self._library is not None),
                    "skills": dict(runtime_skills_payload),
                    "history_policy": {
                        "preserve_first": int(preserve_first),
                        "preserve_last": int(preserve_last),
                        "history_token_cap": int(history_token_cap),
                    },
                },
            )

            if prompt_text:
                self._record_event("user_message", prompt_text)
                self._capture_profile_hints(prompt_text)
            self._conversation.append({"role": "user", "content": prompt})
            self._conversation.append({"role": "assistant", "content": answer})
            yield AgentEvent.text_delta(answer, iteration=0)

            usage_obj = {
                "prompt_tokens": estimate_tokens(prompt_text),
                "completion_tokens": estimate_tokens(answer),
                "total_tokens": estimate_tokens(prompt_text) + estimate_tokens(answer),
            }
            token_report = self._build_token_report(
                prompt_text=prompt_text,
                usage_obj=usage_obj,
                mode=effective_mode,
                iterations=1,
                peak_context_tokens=usage_obj["total_tokens"],
                avg_context_tokens=usage_obj["total_tokens"],
                memory_tokens=0,
                tool_chars_total=0,
                tool_chars_kept=0,
            )
            token_report["route"] = route.to_dict()
            token_report["effective_tools_policy"] = "never"
            token_report["autonomy_level"] = int(self._autonomy_level)
            token_report["autonomy_name"] = autonomy_name
            token_report["continuity"] = {
                "route_input_source": route_input_source,
                "followup_suppressed_count": 0,
                "thought_leak_suppressed_count": 0,
                "full_auto_reprompt_count": 0,
                "clarification_question_cap": 0,
                "clarification_questions_asked": 0,
                "clarification_reprompt_count": 0,
            }
            token_report["token_economy"] = dict(token_economy_meta)
            token_report["skills"] = dict(runtime_skills_payload)
            cfg_errors: List[str] = []
            cfg_unknown: List[str] = []
            try:
                cfg_path = Path(os.environ.get("THOMAS_CONFIG") or "thomas.toml")
                loaded_cfg = load_config(cfg_path)
                cfg_errors = loaded_cfg.validate()
                cfg_unknown = list(loaded_cfg.unknown_core_keys)
            except Exception as e:
                cfg_errors = [f"config_audit_failed: {type(e).__name__}: {e}"]

            quality_cfg = getattr(self.config, "quality", None)
            combined_quality_events = list(_quality_carry_forward_events or [])
            rules_report = evaluate_rules(
                route_path=str(route.path or ""),
                prompt_text=prompt_text,
                response_text=answer,
                tool_events=combined_quality_events,
                requested_job_type=job_type,
                config_errors=cfg_errors,
                unknown_core_keys=cfg_unknown,
                require_verification_for_coding=bool(
                    getattr(quality_cfg, "require_verification_for_coding", True)
                ),
                require_tests_for_code_edits=bool(
                    getattr(quality_cfg, "require_tests_for_code_edits", False)
                ),
                require_monolith_guard_for_coding=bool(
                    getattr(quality_cfg, "require_monolith_guard_for_coding", True)
                ),
                attempt=int(_quality_retry_count),
            )
            token_report["rules_of_road"] = rules_report

            quality_enabled = bool(getattr(quality_cfg, "enabled", True))
            quality_enforce = bool(getattr(quality_cfg, "enforce", True))
            quality_max_retries = max(
                0,
                min(3, int(getattr(quality_cfg, "max_auto_retries", 1) or 0)),
            )
            if (
                quality_enabled
                and quality_enforce
                and not bool(rules_report.get("passed", False))
                and _quality_retry_count < quality_max_retries
            ):
                remediation_prompt = build_remediation_prompt(rules_report)
                if remediation_prompt:
                    retry_job_type = (
                        str(job_type or rules_report.get("job_type") or "").strip().lower() or None
                    )
                    async for retry_event in self.run(
                        remediation_prompt,
                        mode=mode,
                        tools_policy=tools_policy,
                        token_economy=applied_token_economy,
                        max_iterations=max_iterations,
                        job_type=retry_job_type,
                        _quality_retry_count=_quality_retry_count + 1,
                        _quality_carry_forward_events=combined_quality_events,
                    ):
                        yield retry_event
                    return

            yield AgentEvent.agent_done(
                text=answer,
                iterations=1,
                tool_calls=0,
                usage=usage_obj,
                token_report=token_report,
            )
            return

        # Mode presets (the caller can still override with max_iterations).
        if max_iterations is not None:
            max_iter = max_iterations
        elif effective_mode == "fast":
            # Fast mode should not truncate task completion. Keep the same loop
            # budget as normal mode; "fast" is handled by lighter behavior/budgets.
            max_iter = self.config.max_agent_iterations
        elif effective_mode == "thinking":
            max_iter = min(self.config.max_agent_iterations * 2, 25)
        else:
            max_iter = self.config.max_agent_iterations
        if max_iterations is None and autonomy.prefers_extended_iterations:
            if effective_mode == "fast":
                # Fast mode still needs enough room for at least one tool turn + follow-up,
                # but should not inherit very long full-auto iteration budgets.
                max_iter = max(max_iter, min(max(self.config.max_agent_iterations, 2), 6))
            else:
                max_iter = max(max_iter, min(self.config.max_agent_iterations * 3, 32))

        project_related = self._is_project_related_prompt(prompt_text)
        explicit_action = self._has_explicit_action_intent(prompt_text)
        low_intent_route = self._is_low_intent_route(route.path)
        action_route = str(route.path or "") in ("coding_task", "debug_audit", "planning", "research")
        full_auto_action_turn = bool(
            int(self._autonomy_level) == 4 and (project_related or explicit_action or action_route)
        )
        clarification_budget_active = bool(project_related or explicit_action or action_route)
        continuation_turn = bool(route_input_source == "history_augmented")
        clarification_question_cap = 2
        if clarification_budget_active:
            clarification_question_cap = 1
        if clarification_budget_active and explicit_action and int(self._autonomy_level) >= 3:
            clarification_question_cap = 0
        if continuation_turn:
            clarification_question_cap = 0 if clarification_budget_active else 1
        if full_auto_action_turn:
            clarification_question_cap = 0
        clarification_question_cap = max(0, int(clarification_question_cap))
        full_auto_reprompt_count = 0
        clarification_questions_asked = 0
        clarification_reprompt_count = 0
        effective_tools_policy = route.tools_policy
        if tools_policy == "auto" and route.tools_policy == "auto":
            if effective_mode == "fast":
                effective_tools_policy = "never"
            elif effective_mode == "thinking":
                effective_tools_policy = "always"

        # API/cloud providers should always have tools available unless the
        # user explicitly disabled them. The routing heuristic was originally
        # tuned for local models where hiding tools saves context.
        if (tools_policy == "auto"
                and effective_tools_policy == "never"
                and profile_prefers_always_tools(self.llm.config)
                and (project_related or explicit_action)):
            effective_tools_policy = "auto"
        if (
            tools_policy == "auto"
            and effective_tools_policy == "never"
            and project_related
        ):
            effective_tools_policy = "auto"
        if self._autonomy_level == 2 and effective_tools_policy == "always":
            effective_tools_policy = "auto"
        if autonomy.force_tools_policy in ("never", "auto", "always"):
            forced = str(autonomy.force_tools_policy)
            if forced == "always" and low_intent_route and not explicit_action and not project_related:
                # Only downgrade "always" to "never" when truly conversational
                # (no action verbs AND no project signals).
                effective_tools_policy = "never"
            else:
                effective_tools_policy = forced

        tool_specs = self._select_tools(prompt_text, policy=effective_tools_policy, route=route)

        # EMERGENCY BRAKE: Tool definition bloat.
        if tool_specs:
            hard_tool_count_cap, max_tool_spec_tokens = loop_tool_spec_budgets(
                applied_token_economy,
                effective_mode,
            )
            if len(tool_specs) > hard_tool_count_cap:
                tool_specs = tool_specs[:hard_tool_count_cap]

            while len(tool_specs) > 1 and estimate_tools_tokens(tool_specs) > max_tool_spec_tokens:
                tool_specs = tool_specs[:-1]

        preserve_first, preserve_last = self._history_preserve_counts(route)
        history_token_cap = self._history_token_cap(route)
        state = LoopState()
        iter_token_estimates: List[int] = []
        cumulative_context_tokens = 0
        peak_context_tokens = 0
        tool_chars_total = 0
        tool_chars_kept = 0
        iter_prompt_spends: List[int] = []
        high_prompt_spend_fail_iters = 0
        followup_suppressed_count = 0
        thought_leak_suppressed_count = 0
        quality_tool_events: List[Dict[str, Any]] = []
        consecutive_failed_tool_iters = 0
        repeated_failure_signature = ""
        repeated_failure_count = 0
        runaway_guard_reason: Optional[str] = None
        memory_text = ""
        continuity_hint = ""
        test_visibility_hint = ""
        library_text = ""
        memory_tokens = 0
        mode_context_budget, hard_context_budget, emergency_context_budget = loop_context_budgets(
            applied_token_economy,
            effective_mode,
        )
        iter_prompt_warn_cap, iter_prompt_hard_cap = loop_iteration_prompt_caps(
            applied_token_economy,
            effective_mode,
        )
        provider_tpm_limit = self._provider_tpm_limit()
        provider_tpm_budget = 0
        if provider_tpm_limit > 0:
            provider_tpm_budget = max(1, int(provider_tpm_limit * self._provider_tpm_headroom()))
        provider_prompt_window: List[tuple[float, int]] = []
        provider_tpm_wait_events = 0
        provider_tpm_wait_seconds = 0.0
        provider_prompt_tokens_last_minute = 0
        stream_prompt_prev = 0

        def _prune_prompt_window(now_ts: float) -> None:
            cutoff = now_ts - _TPM_WINDOW_SECONDS
            if not provider_prompt_window:
                return
            provider_prompt_window[:] = [
                (ts, tok) for (ts, tok) in provider_prompt_window if ts >= cutoff
            ]

        def _projected_wait_seconds(next_prompt_tokens: int) -> tuple[float, int, int]:
            if provider_tpm_budget <= 0:
                return 0.0, 0, 0
            now_ts = time.monotonic()
            _prune_prompt_window(now_ts)
            current_prompt = int(sum(max(0, int(tok)) for _, tok in provider_prompt_window))
            projected_prompt = current_prompt + max(0, int(next_prompt_tokens))
            if projected_prompt <= provider_tpm_budget:
                return 0.0, projected_prompt, current_prompt

            running_prompt = current_prompt
            wait_s = _TPM_WINDOW_SECONDS
            for ts, tok in provider_prompt_window:
                running_prompt -= max(0, int(tok))
                if running_prompt + max(0, int(next_prompt_tokens)) <= provider_tpm_budget:
                    wait_s = max(0.25, _TPM_WINDOW_SECONDS - (now_ts - ts))
                    break
            return wait_s, projected_prompt, current_prompt

        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "prompt": prompt_text,
                "route": route.to_dict(),
                "route_input_source": route_input_source,
                "mode": effective_mode,
                "tools_policy": effective_tools_policy,
                "autonomy_level": int(self._autonomy_level),
                "autonomy_name": autonomy_name,
                "token_economy": token_economy_meta,
                "library_enabled": bool(self._library is not None),
                "skills": dict(runtime_skills_payload),
                "history_policy": {
                    "preserve_first": int(preserve_first),
                    "preserve_last": int(preserve_last),
                    "history_token_cap": int(history_token_cap),
                },
            },
        )

        self._apply_memory_policy(route)

        # Record user message in memory
        if prompt_text:
            self._record_event("user_message", prompt_text)
            self._capture_profile_hints(prompt_text)

        # Always retrieve memory context for continuity.
        if prompt_text:
            memory_mode = self.config.memory.mode or "auto"
            if effective_mode == "fast":
                memory_mode = "fast"
            if effective_mode == "thinking":
                memory_mode = "thorough"
            memory_text = self._retrieve_memory(
                prompt_text,
                mode=memory_mode,
                budget_override=route.memory_budget_tokens,
            )
            continuity_hint = self._input_continuity_hint(prompt_text)
            test_visibility_hint = live_test_default_hint(prompt_text)
            library_text = self._retrieve_library(prompt_text, route)
            memory_tokens = (
                estimate_tokens(memory_text)
                + estimate_tokens(continuity_hint)
                + estimate_tokens(test_visibility_hint)
                + estimate_tokens(library_text)
            )

        # Add user message to conversation for history
        self._conversation.append({"role": "user", "content": prompt})

        for iteration in range(max_iter):
            state.iteration = iteration

            # Build messages with context window management
            # Only inject memory on first iteration
            mem = ""
            if iteration == 0:
                mem = memory_text
                if continuity_hint:
                    mem = (mem + "\n\n" + continuity_hint).strip() if mem else continuity_hint
                if test_visibility_hint:
                    mem = (mem + "\n\n" + test_visibility_hint).strip() if mem else test_visibility_hint
                if library_text:
                    mem = (mem + "\n\n" + library_text).strip() if mem else library_text
            messages = self._build_messages(
                state,
                memory_text=mem,
                tool_specs=tool_specs,
                include_purpose=route.include_purpose,
                preserve_first=preserve_first,
                preserve_last=preserve_last,
                history_token_cap=history_token_cap,
                route_path=str(route.path or ""),
                skills_context=runtime_skills_context,
            )
            iter_token_estimates.append(int(state.token_estimate))
            cumulative_context_tokens += int(state.token_estimate)
            peak_context_tokens = max(peak_context_tokens, int(state.token_estimate))

            if provider_tpm_budget > 0:
                while True:
                    next_prompt_estimate = int(state.token_estimate)
                    if provider_prompt_window:
                        observed_avg = int(
                            sum(max(0, int(tok)) for _, tok in provider_prompt_window)
                            / max(1, len(provider_prompt_window))
                        )
                        next_prompt_estimate = max(next_prompt_estimate, observed_avg)
                    wait_s, projected_prompt, current_prompt = _projected_wait_seconds(
                        next_prompt_estimate
                    )
                    provider_prompt_tokens_last_minute = int(current_prompt)
                    if wait_s <= 0:
                        break
                    if wait_s <= _TPM_MAX_AUTO_WAIT_S:
                        provider_tpm_wait_events += 1
                        provider_tpm_wait_seconds += float(wait_s)
                        yield AgentEvent.status(
                            (
                                f"Throttling {wait_s:.1f}s to avoid provider rate limit "
                                f"({projected_prompt:,}/{provider_tpm_budget:,} estimated prompt tokens/min)."
                            ),
                            iteration=iteration,
                        )
                        await asyncio.sleep(wait_s)
                        continue

                    profile_name = str(getattr(self.llm.config, "name", "") or "active-model")
                    runaway_guard_reason = (
                        "Stopped automatically to prevent provider rate-limit failure: "
                        f"projected prompt load {projected_prompt:,}/{provider_tpm_budget:,} "
                        f"tokens/min for profile '{profile_name}'. Retry in about {int(wait_s)}s."
                    )
                    yield AgentEvent.agent_error(runaway_guard_reason, iteration=iteration)
                    state.error = runaway_guard_reason
                    state.finished = True
                    break
                if state.finished:
                    break

            yield AgentEvent(
                type=EventType.AGENT_ITERATION,
                data={
                    "iteration": iteration,
                    "message_count": len(messages),
                    "token_estimate": state.token_estimate,
                    "context_window": self._context_window,
                },
                iteration=iteration,
            )

            # Collect this iteration's response
            text_chunks: list[str] = []
            pending_tool_calls: list[Dict[str, Any]] = []
            # Buffer outputs when sanitation is likely needed so user-visible text
            # is post-processed (prevents thought/tool artifact leakage in stream).
            buffer_text_tokens = bool(
                full_auto_action_turn
                or self._is_low_intent_route(str(getattr(route, "path", "") or ""))
                or prompt_requests_directness_constraints(prompt_text)
                or str(getattr(route, "path", "") or "") in ("coding_task", "debug_audit", "planning", "research")
            )
            iter_prompt_start_total = int(stream_usage.get("prompt_tokens", 0) or 0)

            try:
                llm_stream_error: Optional[str] = None
                async for event in self.llm.stream_chat(messages, tool_specs):
                    if event.type == "thinking":
                        # Forward thinking/reasoning tokens to the stream
                        yield AgentEvent(
                            type=EventType.THINKING,
                            data={"text": event.data.get("text", "")},
                            iteration=iteration,
                        )

                    elif event.type == "token":
                        text = event.data["text"]
                        text_chunks.append(text)
                        if not buffer_text_tokens:
                            yield AgentEvent.text_delta(text, iteration=iteration)

                    elif event.type == "tool_call_start":
                        tc_id = event.data["id"]
                        tc_name = event.data["name"]
                        yield AgentEvent.tool_call_start(tc_id, tc_name, iteration=iteration)

                    elif event.type == "tool_call_delta":
                        tc_id = event.data.get("id", "")
                        delta = event.data.get("delta", "")
                        if tc_id and delta:
                            yield AgentEvent.tool_call_args_delta(
                                tc_id, delta, iteration=iteration
                            )

                    elif event.type == "tool_call_end":
                        # Codex app-server executes tools itself; treat tool_call_end as a tool result
                        # passthrough (do not execute via Thomas's tool registry).
                        if self.llm.config.provider == "codex" and "output" in event.data:
                            tc_id = str(event.data.get("id", ""))
                            tc_name = str(event.data.get("name", ""))
                            output = str(event.data.get("output", ""))
                            exit_code = event.data.get("exit_code")
                            tool_chars_total += len(output)
                            tool_chars_kept += len(output)

                            ok = True
                            if exit_code is not None:
                                try:
                                    ok = int(exit_code) == 0
                                except Exception:
                                    ok = False

                            await self._audit_action(
                                kind="tool_action_result",
                                tool_call_id=tc_id,
                                tool_name=tc_name,
                                decision="EXECUTED" if ok else "FAILED",
                                payload={
                                    "provider": "codex",
                                    "ok": ok,
                                    "exit_code": exit_code,
                                    "output_preview": output[:1000],
                                },
                            )

                            yield AgentEvent.tool_call_end(tc_id, iteration=iteration)
                            yield AgentEvent(
                                type=EventType.TOOL_RESULT,
                                data={
                                    "tool_id": tc_id,
                                    "tool_name": tc_name,
                                    "result": output[:4000],   # summary for event consumers
                                    "result_text": output,     # full text (not fed back to LLM)
                                    "ok": ok,
                                    "duration_ms": 0,
                                },
                                iteration=iteration,
                            )
                            quality_tool_events.append(
                                {
                                    "name": tc_name,
                                    "ok": ok,
                                    "command": "",
                                    "path": "",
                                }
                            )
                            continue

                        tc_data = {
                            "id": event.data["id"],
                            "name": event.data["name"],
                            "arguments": event.data["arguments"],
                        }
                        pending_tool_calls.append(tc_data)
                        yield AgentEvent.tool_call_end(tc_data["id"], iteration=iteration)

                    elif event.type == "error":
                        # Some providers (e.g. Codex bridge) surface errors as events.
                        err = str(event.data.get("error", "")).strip() or "LLM error"
                        llm_stream_error = err
                        yield AgentEvent.agent_error(err, iteration=iteration)

                    elif event.type == "done":
                        # Don't `break` here: exiting an `async for` early triggers an
                        # `aclose()` on the underlying async generator while it's still
                        # unwinding network I/O, which can produce noisy asyncio/httpx
                        # shutdown errors. Let it terminate naturally on StopAsyncIteration.
                        continue

                    elif event.type == "usage":
                        usage_part = self._usage_from_event_payload(event.data.get("usage"))
                        stream_usage = self._normalize_usage(
                            stream_usage["prompt_tokens"] + usage_part["prompt_tokens"],
                            stream_usage["completion_tokens"] + usage_part["completion_tokens"],
                            stream_usage["total_tokens"] + usage_part["total_tokens"],
                        )

                if llm_stream_error:
                    state.error = llm_stream_error
                    state.finished = True
                    break

            except LLMError as e:
                error_msg = str(e)
                # Detect connection errors and give a helpful message
                if "connect" in error_msg.lower() or "refused" in error_msg.lower():
                    base_url = self.llm.config.base_url
                    error_msg = (
                        f"Cannot connect to LLM at {base_url}. "
                        f"Is Ollama running? Try: ollama serve"
                    )
                yield AgentEvent.agent_error(error_msg, iteration=iteration)
                state.error = error_msg
                state.finished = True
                break

            except (httpx_ConnectError, ConnectionError, OSError) as e:
                base_url = self.llm.config.base_url
                error_msg = (
                    f"Cannot connect to LLM at {base_url}. "
                    f"Is Ollama running? Try: ollama serve"
                )
                yield AgentEvent.agent_error(error_msg, iteration=iteration)
                state.error = error_msg
                state.finished = True
                break

            # Accumulate text response
            iter_text = "".join(text_chunks)
            iter_text, suppressed = self._sanitize_assistant_text(
                iter_text,
                prompt_text=prompt_text,
                route=route,
                route_input_source=route_input_source,
                pending_tool_calls=len(pending_tool_calls),
            )
            if suppressed:
                followup_suppressed_count += 1
            if self._last_sanitize_flags.get("thought_leak"):
                thought_leak_suppressed_count += 1
            if iter_text.strip() == "Understood. How can I assist you further?":
                iter_text = "I didn't answer that. Please ask a specific question."

            # Clarification budget guardrail for action turns: avoid repeated
            # ask-back loops when the model can proceed with sensible defaults.
            is_clarifying_question = bool(
                not pending_tool_calls and self._looks_like_clarifying_question(iter_text)
            )
            if is_clarifying_question:
                clarification_questions_asked += 1
            if (
                clarification_budget_active
                and is_clarifying_question
                and clarification_questions_asked > clarification_question_cap
                and clarification_reprompt_count < 2
                and (iteration + 1) < max_iter
            ):
                clarification_reprompt_count += 1
                if full_auto_action_turn:
                    full_auto_reprompt_count += 1
                    nudge = self._full_auto_nudge(prompt_text, full_auto_reprompt_count)
                else:
                    nudge = self._assume_and_proceed_nudge(
                        prompt_text,
                        retry_index=clarification_reprompt_count,
                        question_cap=clarification_question_cap,
                        questions_seen=clarification_questions_asked,
                        route_input_source=route_input_source,
                    )
                self._conversation.append({"role": "user", "content": nudge})
                continue

            if buffer_text_tokens and iter_text:
                # Flush buffered text after full-auto guardrails accept it.
                yield AgentEvent.text_delta(iter_text, iteration=iteration)

            if provider_tpm_budget > 0:
                stream_prompt_now = int(stream_usage.get("prompt_tokens", 0) or 0)
                stream_prompt_delta = max(0, stream_prompt_now - stream_prompt_prev)
                if stream_prompt_delta > 0:
                    provider_prompt_window.append((time.monotonic(), int(stream_prompt_delta)))
                    stream_prompt_prev = stream_prompt_now
                    _prune_prompt_window(time.monotonic())
                    provider_prompt_tokens_last_minute = int(
                        sum(max(0, int(tok)) for _, tok in provider_prompt_window)
                    )
                elif stream_prompt_now > stream_prompt_prev:
                    stream_prompt_prev = stream_prompt_now

            iter_prompt_now = int(stream_usage.get("prompt_tokens", 0) or 0)
            iter_prompt_spend = max(0, iter_prompt_now - int(iter_prompt_start_total))
            iter_prompt_spends.append(int(iter_prompt_spend))

            state.text_response += iter_text

            # If no tool calls, we're done
            if not pending_tool_calls:
                if iter_text:
                    self._conversation.append({"role": "assistant", "content": iter_text})
                    self._record_event("assistant_response", iter_text)
                state.finished = True
                break

            # Build assistant message with tool calls for the message history
            assistant_msg: Dict[str, Any] = {"role": "assistant"}
            if iter_text:
                assistant_msg["content"] = iter_text
            else:
                assistant_msg["content"] = ""
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                }
                for tc in pending_tool_calls
            ]
            self._conversation.append(assistant_msg)

            # Execute tool calls (parallel when multiple), streaming each completion.
            tool_results: List[AgentEvent] = []
            tool_results_by_id: Dict[str, AgentEvent] = {}
            async for result_event in self._execute_tools(pending_tool_calls, iteration):
                tc_id = str(result_event.data.get("tool_id", ""))
                tc: Dict[str, Any] = {}
                for maybe_tc in pending_tool_calls:
                    if str(maybe_tc.get("id", "")) == tc_id:
                        tc = maybe_tc
                        break
                if not tc:
                    tc = {"id": tc_id, "name": result_event.data.get("tool_name", "tool"), "arguments": "{}"}

                parsed_args, _parse_err = self._parse_tool_args(tc.get("arguments"))

                yield result_event
                tool_results.append(result_event)
                tool_results_by_id[tc_id] = result_event

                args_meta = parsed_args if isinstance(parsed_args, dict) else {}
                quality_tool_events.append(
                    {
                        "name": str(tc.get("name") or ""),
                        "ok": bool(result_event.data.get("ok", False)),
                        "command": str(
                            args_meta.get("command")
                            or args_meta.get("cmd")
                            or args_meta.get("shell")
                            or ""
                        )[:500],
                        "path": str(
                            args_meta.get("path")
                            or args_meta.get("file")
                            or args_meta.get("filename")
                            or ""
                        )[:500],
                    }
                )

                # Truncate tool results that would dominate context
                result_text = result_event.data.get("result_text", "")
                original_len = len(result_text)
                if len(result_text) > _MAX_TOOL_RESULT_CHARS:
                    result_text = (
                        result_text[:_MAX_TOOL_RESULT_CHARS - 100]
                        + f"\n\n... (truncated, {len(result_text):,} chars total. "
                        f"Use start_line/end_line for large files.)"
                    )
                tool_chars_total += original_len
                tool_chars_kept += len(result_text)

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_text,
                }
                self._conversation.append(tool_msg)

                # ── message interruption check ──
                # Between tool completions, check if the user sent a new message.
                # If so, inject it and cancel remaining un-completed tool calls.
                if self._message_queue is not None:
                    try:
                        queued_msg = self._message_queue.get_nowait()
                        if queued_msg is not None:
                            completed_tc_ids = set(tool_results_by_id.keys())
                            for remaining_tc in pending_tool_calls:
                                rtc_id = str(remaining_tc.get("id", ""))
                                if rtc_id and rtc_id not in completed_tc_ids:
                                    self._conversation.append({
                                        "role": "tool",
                                        "tool_call_id": rtc_id,
                                        "content": "Cancelled: user interrupted.",
                                    })
                            self._conversation.append({"role": "user", "content": str(queued_msg)})
                            yield AgentEvent.status(
                                "User message received mid-execution. Deferring remaining tools.",
                                iteration=iteration,
                            )
                            # Signal outer loop to re-enter LLM turn with the new user message
                            state.user_interrupted = True
                            break
                    except asyncio.QueueEmpty:
                        pass

            state.total_tool_calls += len(pending_tool_calls)

            tool_results = [
                tool_results_by_id.get(str(tc.get("id", ""))) for tc in pending_tool_calls
            ]
            tool_results = [ev for ev in tool_results if isinstance(ev, AgentEvent)]
            failed_results = [ev for ev in tool_results if not bool(ev.data.get("ok", False))]
            if failed_results:
                if len(failed_results) == len(tool_results):
                    consecutive_failed_tool_iters += 1
                else:
                    consecutive_failed_tool_iters = 0

                sig_items: List[str] = []
                for ev in failed_results:
                    name = str(ev.data.get("tool_name") or "").strip().lower()
                    err_text = str(
                        ev.data.get("result_text")
                        or ev.data.get("result")
                        or ev.data.get("error")
                        or ""
                    )
                    err_text = re.sub(r"\s+", " ", err_text).strip().lower()
                    err_text = re.sub(r"\b\d+\b", "#", err_text)
                    sig_items.append(f"{name}:{err_text[:180]}")
                sig = "|".join(sorted(sig_items))
                if sig and sig == repeated_failure_signature:
                    repeated_failure_count += 1
                else:
                    repeated_failure_signature = sig
                    repeated_failure_count = 1
            else:
                consecutive_failed_tool_iters = 0
                repeated_failure_signature = ""
                repeated_failure_count = 0

            if failed_results and iter_prompt_hard_cap is not None and int(iter_prompt_spend) >= int(iter_prompt_hard_cap):
                high_prompt_spend_fail_iters += 1
            else:
                high_prompt_spend_fail_iters = 0

            runaway_detected = False
            if consecutive_failed_tool_iters >= 3 or repeated_failure_count >= 3:
                runaway_detected = True
                runaway_guard_reason = (
                    "Stopped automatically to prevent token waste: repeated tool failures with no forward progress."
                )
            elif high_prompt_spend_fail_iters >= 2:
                runaway_detected = True
                runaway_guard_reason = (
                    "Stopped automatically to prevent token waste: repeated high prompt-token spend per iteration "
                    "during failing tool calls."
                )
            elif hard_context_budget is not None and cumulative_context_tokens >= hard_context_budget:
                runaway_detected = True
                runaway_guard_reason = (
                    "Stopped automatically to prevent token waste: cumulative context budget exceeded."
                )
            elif cumulative_context_tokens >= emergency_context_budget:
                runaway_detected = True
                runaway_guard_reason = (
                    "Stopped automatically to prevent token waste: emergency safety budget exceeded."
                )
            elif failed_results and cumulative_context_tokens >= mode_context_budget and repeated_failure_count >= 2:
                runaway_detected = True
                runaway_guard_reason = (
                    "Stopped automatically to prevent token waste: failing-tool loop crossed the run token budget."
                )

            if runaway_detected and runaway_guard_reason:
                yield AgentEvent.agent_error(runaway_guard_reason, iteration=iteration)
                state.error = runaway_guard_reason
                state.finished = True
                break

            # If the user interrupted mid-tool-execution, skip to next
            # iteration so the LLM sees the injected user message.
            if state.user_interrupted:
                state.user_interrupted = False
                continue

        # Ingest new events into memory index (best-effort in background).
        if self._memory and self._memory.started:
            async def _ingest_bg() -> None:
                try:
                    await asyncio.to_thread(self._memory.ingest_pending)
                except Exception as e:
                    log.warning("Memory ingestion failed: %s", e)

                if not self._memory_curator_enabled:
                    return
                run_curator = getattr(self._memory, "run_curator", None)
                if not callable(run_curator):
                    return
                try:
                    await asyncio.to_thread(run_curator, force=False)
                except Exception as e:
                    log.debug("Memory curator background run skipped: %s", e)

            try:
                asyncio.create_task(_ingest_bg())
            except Exception as e:
                log.warning("Memory ingestion scheduling failed: %s", e)

        # Persist useful research responses into the external library (best effort).
        if prompt_text and state.text_response:
            try:
                self._auto_capture_research(
                    route=route,
                    query=prompt_text,
                    answer=state.text_response,
                )
            except Exception as e:
                log.debug("Research auto-capture failed: %s", e)

        usage_after = self._session_usage_snapshot()
        usage_obj = self._usage_delta(usage_before, usage_after)
        if usage_obj["total_tokens"] <= 0 and stream_usage["total_tokens"] > 0:
            usage_obj = dict(stream_usage)
        avg_context = int(sum(iter_token_estimates) / len(iter_token_estimates)) if iter_token_estimates else 0
        token_report = self._build_token_report(
            prompt_text=prompt_text,
            usage_obj=usage_obj,
            mode=effective_mode,
            iterations=state.iteration + 1,
            peak_context_tokens=peak_context_tokens,
            avg_context_tokens=avg_context,
            memory_tokens=memory_tokens,
            tool_chars_total=tool_chars_total,
            tool_chars_kept=tool_chars_kept,
        )
        token_report["route"] = route.to_dict()
        token_report["effective_tools_policy"] = effective_tools_policy
        token_report["autonomy_level"] = int(self._autonomy_level)
        token_report["autonomy_name"] = autonomy_name
        token_report["continuity"] = {
            "route_input_source": route_input_source,
            "followup_suppressed_count": int(followup_suppressed_count),
            "thought_leak_suppressed_count": int(thought_leak_suppressed_count),
            "full_auto_reprompt_count": int(full_auto_reprompt_count),
            "clarification_question_cap": int(clarification_question_cap),
            "clarification_questions_asked": int(clarification_questions_asked),
            "clarification_reprompt_count": int(clarification_reprompt_count),
        }
        token_report["token_economy"] = dict(token_economy_meta)
        token_report["skills"] = dict(runtime_skills_payload)
        if provider_tpm_budget > 0:
            _prune_prompt_window(time.monotonic())
            provider_prompt_tokens_last_minute = int(
                sum(max(0, int(tok)) for _, tok in provider_prompt_window)
            )
        token_report["run_budget"] = {
            "token_economy": str(applied_token_economy),
            "mode_context_budget": int(mode_context_budget),
            "hard_context_budget": int(hard_context_budget) if hard_context_budget is not None else None,
            "emergency_context_budget": int(emergency_context_budget),
            "iteration_prompt_warn_cap": int(iter_prompt_warn_cap),
            "iteration_prompt_hard_cap": int(iter_prompt_hard_cap) if iter_prompt_hard_cap is not None else None,
            "max_iteration_prompt_spend": int(max(iter_prompt_spends) if iter_prompt_spends else 0),
            "high_prompt_spend_fail_iters": int(high_prompt_spend_fail_iters),
            "cumulative_context_tokens": int(cumulative_context_tokens),
            "runaway_guard_triggered": bool(runaway_guard_reason),
            "runaway_guard_reason": str(runaway_guard_reason or ""),
            "provider_tpm_limit": int(provider_tpm_limit) if provider_tpm_limit > 0 else None,
            "provider_tpm_budget": int(provider_tpm_budget) if provider_tpm_budget > 0 else None,
            "provider_prompt_tokens_last_minute": int(provider_prompt_tokens_last_minute),
            "provider_tpm_wait_events": int(provider_tpm_wait_events),
            "provider_tpm_wait_seconds": round(float(provider_tpm_wait_seconds), 3),
        }
        if runaway_guard_reason:
            token_report.setdefault("flags", []).append(
                {
                    "kind": "runaway_guard",
                    "severity": "high",
                    "detail": "Run was stopped by automatic token waste protection.",
                }
            )
            token_report.setdefault("suggestions", []).append(
                "Retry in a fresh chat or with tighter scope to reduce context growth."
            )
        if iter_prompt_spends and max(iter_prompt_spends) >= int(iter_prompt_warn_cap):
            token_report.setdefault("flags", []).append(
                {
                    "kind": "iteration_prompt_spend",
                    "severity": "medium",
                    "detail": (
                        "One or more iterations used unusually high prompt tokens; "
                        "review tool loops, memory scope, and mode/economy settings."
                    ),
                }
            )
            token_report.setdefault("suggestions", []).append(
                "If this repeats, narrow scope or lower memory/tool breadth to avoid oversized prompt rebuilds."
            )
        cfg_errors: List[str] = []
        cfg_unknown: List[str] = []
        try:
            cfg_path = Path(os.environ.get("THOMAS_CONFIG") or "thomas.toml")
            loaded_cfg = load_config(cfg_path)
            cfg_errors = loaded_cfg.validate()
            cfg_unknown = list(loaded_cfg.unknown_core_keys)
        except Exception as e:
            cfg_errors = [f"config_audit_failed: {type(e).__name__}: {e}"]

        quality_cfg = getattr(self.config, "quality", None)
        quality_enabled = bool(getattr(quality_cfg, "enabled", True))
        quality_enforce = bool(getattr(quality_cfg, "enforce", True))
        quality_max_retries = max(0, min(3, int(getattr(quality_cfg, "max_auto_retries", 1) or 0)))
        require_verify = bool(
            getattr(quality_cfg, "require_verification_for_coding", True)
        )
        require_tests = bool(
            getattr(quality_cfg, "require_tests_for_code_edits", False)
        )

        combined_quality_events = list(_quality_carry_forward_events or []) + quality_tool_events
        rules_report = evaluate_rules(
            route_path=str(route.path or ""),
            prompt_text=prompt_text,
            response_text=state.text_response,
            tool_events=combined_quality_events,
            requested_job_type=job_type,
            config_errors=cfg_errors,
            unknown_core_keys=cfg_unknown,
            require_verification_for_coding=require_verify,
            require_tests_for_code_edits=require_tests,
            require_monolith_guard_for_coding=bool(
                getattr(quality_cfg, "require_monolith_guard_for_coding", True)
            ),
            attempt=int(_quality_retry_count),
        )
        token_report["rules_of_road"] = rules_report

        if (
            quality_enabled
            and quality_enforce
            and not bool(rules_report.get("passed", False))
            and not bool(state.error)
            and _quality_retry_count < quality_max_retries
        ):
            remediation_prompt = build_remediation_prompt(rules_report)
            if remediation_prompt:
                retry_job_type = (
                    str(job_type or rules_report.get("job_type") or "").strip().lower() or None
                )
                async for retry_event in self.run(
                    remediation_prompt,
                    mode=mode,
                    tools_policy=tools_policy,
                    token_economy=applied_token_economy,
                    max_iterations=max_iterations,
                    job_type=retry_job_type,
                    _quality_retry_count=_quality_retry_count + 1,
                    _quality_carry_forward_events=combined_quality_events,
                ):
                    yield retry_event
                return

        # Done
        yield AgentEvent.agent_done(
            text=state.text_response,
            iterations=state.iteration + 1,
            tool_calls=state.total_tool_calls,
            usage=usage_obj,
            token_report=token_report,
        )

        # Auto-generate reusable tool from completed task
        if state.text_response and state.total_tool_calls > 0:
            try:
                from thomas.core.tool_factory import get_tool_factory
                factory = get_tool_factory()
                tool_schema = factory.create_tool_from_task(
                    task_description=prompt_text,
                    steps_taken=self._conversation[-10:],  # recent context
                    code_written=None,  # could extract from tool results
                    outcome="success" if not state.error else "error",
                )
                if tool_schema:
                    factory.register(tool_schema)
                    log.debug("ToolFactory: registered tool '%s' from task", tool_schema.name)
            except Exception as e:
                log.debug("ToolFactory: failed to create tool from task: %s", e)

    def _parse_tool_args(self, raw_args: Any) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Parse tool arguments with repair heuristics for weak model outputs."""
        return _parse_tool_args_impl(raw_args)

    async def _execute_tools(
        self,
        tool_calls: List[Dict[str, Any]],
        iteration: int,
    ) -> AsyncIterator[AgentEvent]:
        """Execute tool calls, running independent calls in parallel."""
        async for event in _execute_tools_impl(
            self,
            tool_calls,
            iteration,
            file_audit_module=_file_audit,
        ):
            yield event


# Sentinel for catching connection errors without importing httpx at module level
try:
    import httpx as _httpx
    httpx_ConnectError = _httpx.ConnectError
except ImportError:
    httpx_ConnectError = OSError  # type: ignore[misc,assignment]
