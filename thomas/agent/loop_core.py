"""Core agent loop initialization and message building.

Provides:
- LoopState: state tracking across iterations
- AgentLoop class initialization and constructor
- System prompt and message building
- Message history management
- Routing and intent detection helpers
- Basic query classification
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from thomas.agent.guidance import load_cached_purpose_brief
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
    trim_messages_to_budget,
)
from thomas.library import ResearchLibrary, default_library_root
from thomas.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from thomas.agent.guarded_tools import GuardedToolRunner
    from thomas.core.llm import LLMClient
    from thomas.memory import MemoryEngine
    from thomas.policy.policy import PolicyEngine

log = logging.getLogger(__name__)

_TPM_WINDOW_SECONDS = 60.0
_TPM_HEADROOM_DEFAULT = 0.90
_TPM_MAX_AUTO_WAIT_S = 20.0
_PROVIDER_DEFAULT_TPM_LIMITS: dict[str, int] = {
    "anthropic": 30_000,
}


@lru_cache(maxsize=1)
def _load_purpose_text() -> str:
    """Load cached startup guidance brief (best effort)."""
    try:
        return load_cached_purpose_brief()
    except Exception:  # REVIEWED: swallow — optional feature, fallback to empty string
        return ""


@dataclass
class LoopState:
    """Tracks state across agent loop iterations."""

    iteration: int = 0
    total_tool_calls: int = 0
    text_response: str = ""
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
        memory_retrieval_scope: str = "thread",
        automation_policy: PolicyEngine | None = None,
        autonomy_level: int = 3,
        max_parallel_tools: int | None = None,
        tool_timeout_s: int | None = None,
        message_queue: Any | None = None,
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
        self._max_parallel_tools: int | None = None
        if max_parallel_tools is not None:
            try:
                self._max_parallel_tools = max(1, int(max_parallel_tools))
            except (ValueError, TypeError):
                self._max_parallel_tools = None
        self._tool_timeout_s: int | None = None
        if tool_timeout_s is not None:
            try:
                self._tool_timeout_s = max(1, int(tool_timeout_s))
            except (ValueError, TypeError):
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

    def _build_system_message(
        self,
        memory_text: str = "",
        include_purpose: bool = True,
        route_path: str = "",
        skills_context: str = "",
    ) -> dict[str, Any]:
        """Build the system prompt for an LLM call."""
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
            prompt = prompt.rstrip() + "\n\n--- Purpose Brief ---\n" + purpose + "\n--- End Purpose Brief ---\n"

        # Only inject the autonomy directive for action-oriented routes.
        # For casual/low-intent routes, the autonomy directive ("execute tasks
        # autonomously…") confuses the LLM into agent-speak instead of
        # natural conversation.
        _low_intent_paths = {"casual_chat", "personal_context", "assistant_meta", "general"}
        if str(route_path or "") not in _low_intent_paths:
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
        tool_specs: list[dict[str, Any]] | None = None,
        include_purpose: bool = True,
        preserve_first: int = 1,
        preserve_last: int = 4,
        history_token_cap: int | None = None,
        route_path: str = "",
        skills_context: str = "",
    ) -> list[dict[str, Any]]:
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
            if self._context_preserve_mode in {"continuous", "persistent", "high_context", "chatty"}:
                return 0, 12
            return 0, 10
        if path in ("planning", "research"):
            return 0, 8
        return 0, 8

    def _history_token_cap(self, route: RouteDecision) -> int:
        """Route-specific soft cap for conversation history tokens."""
        path = str(getattr(route, "path", "") or "")
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
            except ValueError:
                continue
        provider = str(getattr(cfg, "provider", "") or "").strip().lower()
        return int(_PROVIDER_DEFAULT_TPM_LIMITS.get(provider, 0))

    def _provider_tpm_headroom(self) -> float:
        """Get TPM headroom multiplier from env or default."""
        raw = str(os.environ.get("THOMAS_PROVIDER_TPM_HEADROOM", "")).strip()
        if raw:
            try:
                parsed = float(raw)
                return max(0.5, min(parsed, 1.0))
            except ValueError:
                pass
        return float(_TPM_HEADROOM_DEFAULT)

    @staticmethod
    def _has_explicit_action_intent(prompt: str) -> bool:
        """Check if prompt contains explicit action words."""
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
        """Check if route is low-intent (casual chat, etc)."""
        return str(path or "") in ("casual_chat", "assistant_meta", "personal_context", "general")

    @staticmethod
    def _is_tool_usage_question(prompt: str) -> bool:
        """Detect meta-questions about tool usage."""
        src = str(prompt or "").strip().lower()
        if not src:
            return False
        if "tool" not in src:
            return False
        if not any(k in src for k in ("use", "used", "using", "call", "called", "try", "tried")):
            return False
        return any(k in src for k in ("what", "which", "did you", "tell me", "list", "show"))

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
        """Check if text is a simple acknowledgment."""
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
        """Check if text looks like a response to a request for input."""
        s = str(text or "").strip()
        if not s:
            return False
        token_like = bool(re.search(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b", s))
        numeric_id_like = bool(re.fullmatch(r"\s*-?\d{5,}\s*", s))
        return token_like or numeric_id_like

    def _is_blocked_response(self, text: str) -> bool:
        """Check if response indicates the model is blocked."""
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

    def _is_project_related_prompt(self, prompt: str) -> bool:
        """Heuristic for whether a prompt likely needs repo/project context."""
        if not prompt:
            return False

        # Obvious coding/project signals
        keywords = (
            "code",
            "bug",
            "error",
            "traceback",
            "stack",
            "exception",
            "repo",
            "project",
            "file",
            "folder",
            "directory",
            "path",
            "function",
            "class",
            "refactor",
            "test",
            "build",
            "run",
            "compile",
            "install",
            "package",
            "pip",
            "npm",
            "yarn",
            "pnpm",
            "git",
            "diff",
            "patch",
            "fix",
            "crash",
            "log",
            "debug",
            "setup",
            "set up",
            "configure",
            "integration",
            "integrate",
            "deploy",
            "telegram",
            "discord",
            "slack",
            "bot",
            "token",
        )
        prompt_l = prompt.lower()
        if any(k in prompt_l for k in keywords):
            return True

        # File-ish patterns (paths, extensions)
        if re.search(r"[A-Za-z]:\\\\|/|\\\\|\\.py\\b|\\.js\\b|\\.ts\\b|\\.json\\b|\\.toml\\b|\\.md\\b", prompt):
            return True
        return False
