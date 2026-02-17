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
import json
import logging
import os
import re
import time
from functools import lru_cache
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from thomas.core.config import AppConfig
from thomas.core.events import AgentEvent, EventType
from thomas.core.llm import LLMClient, LLMError, StreamEvent
from thomas.core.tokens import (
    estimate_tokens,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tools_tokens,
    trim_messages_to_budget,
)
from thomas.agent.routing import IntentRouter, RouteDecision
from thomas.agent.guidance import load_cached_purpose_brief
from thomas.library import ResearchLibrary, default_library_root
from thomas.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from thomas.memory import MemoryEngine
    from thomas.agent.guarded_tools import GuardedToolRunner

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt (the most important thing in the entire project)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are Thomas, a high-agency, deeply helpful AI assistant. You are not just \
a coding bot: you can have natural conversation, help plan and execute work, \
and handle general life/admin/learning tasks in addition to engineering work. \
You have direct access to the user's filesystem and may be able to run shell \
commands (if enabled).

## Core Principles

1. **Use tools when needed, not by default.** Use tools for external facts \
(files, commands, network, repo state). For general questions about your \
purpose, capabilities, or current model, answer directly and do not call tools. \
Never fabricate file contents or command output.

1b. **Operator-first execution.** When the user asks to set up, fix, integrate, \
or run something, do it yourself with tools when available. Do not default to \
handing the user command blocks.

2. **Read before writing.** Always read a file with `fs.read_file` before \
editing it with `diff.create`. You need the exact text to make precise edits.

3. **Be surgical with edits.** Use `diff.create` for targeted changes. \
Provide enough context in `old_str` to match exactly one location. Never \
rewrite entire files when a small edit will do.

4. **Chain tools when needed.** Complex tasks require multiple tool calls. \
For example: search for a function -> read the file -> make the edit -> \
verify with another read. Do this naturally without asking permission.

5. **Verify your work.** After making changes, read the file back or run \
tests to confirm the edit was applied correctly.

6. **Recover from errors.** If a tool call fails, read the error message, \
understand why, and try a different approach. Don't repeat the same failing \
call.

7. **Stay personally aware.** Use memory context to keep continuity about user \
preferences, goals, and ongoing threads. Keep responses human and contextual, \
not robotic.

## Tool Usage Guide

### File Operations
- `fs.read_file` - Read a file. Use `start_line`/`end_line` for large files. \
Always read before editing.
- `fs.write_file` - Write a complete new file. Only use for creating new \
files, NOT for editing existing ones.
- `fs.list_dir` - List directory contents. Use glob patterns like `**/*.py`.
- `fs.search` - Search file contents with regex. Good for finding specific \
text across a project.

### Code Search
- `code.search` - Regex search across code files. Prefers ripgrep for speed. \
Use for finding patterns, TODOs, imports.
- `code.find_definition` - Find where a function/class is defined. Specify \
language for better accuracy.
- `code.find_references` - Find all usages of a symbol. Uses word boundaries \
to avoid false positives.
- `code.project_structure` - Show directory tree. Good first step for \
understanding unfamiliar codebases.

### Code Editing
- `diff.create` - **Primary edit tool.** Replaces exact text in a file. \
The `old_str` must match exactly one location including whitespace.
- `diff.preview` - Preview an edit without applying it. Use when unsure.
- `diff.apply_patch` - Apply unified diff patches. For complex multi-hunk \
changes, consider `shell.exec` with `git apply` instead.

### Shell
- `shell.exec` - Run any shell command. Use for: running tests, installing \
packages, git operations, build commands, checking tool versions.

### Git
- `git.status` - Check working tree state before commits.
- `git.diff` - See what changed. Use `staged=true` for staged changes.
- `git.log` - Recent commit history. Use `path` to filter by file.
- `git.commit` - Stage files and commit. Always check `git.status` first.
- `git.blame` - See who wrote each line and when.

## Response Style

- Be concise. Lead with the answer or action, not preamble.
- When showing code changes, explain *what* changed and *why*.
- For errors: explain the root cause, then fix it.
- If a task is ambiguous, make the most reasonable interpretation and \
proceed. If truly unclear, ask ONE clarifying question.
- For setup/integration requests: run the steps directly and report progress. \
Only ask for the minimum missing input (for example a token/secret) if required.
- Do not start by giving a shell command checklist unless the user explicitly \
asks for manual instructions.
- If you asked for a token/ID and the user provides it next, accept it and continue; \
do not repeat generic safety lectures or re-ask the same field.
- Use markdown formatting for code blocks and structure.
- Avoid filler responses like "Understood. How can I assist you further?" \
when the user asked a direct question.
- Never open with canned helper phrases like "Let's work on Thomas" or \
"I'm here to help". Start directly with the answer/action.
- For general questions about your purpose, capabilities, or the current model, \
answer directly without calling tools.
- For casual conversation, respond naturally like a smart human assistant.
- Do not repeatedly mention "Thomas", internal protocols, or the current repo \
unless the user asked about them or the task is explicitly project-related.
- If the user asks whether you can code, answer clearly that you can help with coding.
- Default to a natural, human-feeling tone and avoid repetitive helper clichÃ©s.
- Do not ask "what next?" or "anything else?" while a requested task is still in progress.
- Give next-step suggestions only after completing the current request or when blocked.

## Current Context
Current working directory: {cwd}
Platform: {platform}
Model profile: {model_name}
Model id: {model_id}
"""

MEMORY_CONTEXT_TEMPLATE = """
--- Memory Context ---
{memory_text}
--- End Memory Context ---
"""

INPUT_CONTINUITY_TEMPLATE = """
--- Input Continuity Hint ---
{hint_text}
--- End Input Continuity Hint ---
"""

LIBRARY_CONTEXT_TEMPLATE = """
--- Library Context ---
{library_text}
--- End Library Context ---
"""

# Maximum chars for tool results in message history (generous for
# LLMs to have enough context but prevents single results from
# dominating the context window)
_MAX_TOOL_RESULT_CHARS = 30_000


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
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        guardrails_event_cb: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
        memory_retrieval_scope: str = "thread",
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
        self._guardrails_event_cb = guardrails_event_cb
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

    def _build_system_message(self, memory_text: str = "", include_purpose: bool = True) -> Dict[str, Any]:
        import sys

        model_cfg = self.llm.config
        prompt = self._system_prompt or SYSTEM_PROMPT.format(
            cwd=os.getcwd(),
            platform=sys.platform,
            model_name=getattr(model_cfg, "name", "unknown"),
            model_id=getattr(model_cfg, "model", "unknown"),
        )

        purpose = _load_purpose_text() if include_purpose else ""
        if purpose:
            prompt = (
                prompt.rstrip()
                + "\n\n--- Purpose Brief ---\n"
                + purpose
                + "\n--- End Purpose Brief ---\n"
            )

        if memory_text:
            prompt += MEMORY_CONTEXT_TEMPLATE.format(memory_text=memory_text)
        return {"role": "system", "content": prompt}

    def _build_messages(
        self,
        state: LoopState,
        memory_text: str = "",
        tool_specs: Optional[List[Dict[str, Any]]] = None,
        include_purpose: bool = True,
        preserve_first: int = 0,
        preserve_last: int = 8,
    ) -> List[Dict[str, Any]]:
        """Build the message list for an LLM call, with context window management."""
        system_msg = self._build_system_message(memory_text, include_purpose=include_purpose)
        system_tokens = estimate_message_tokens(system_msg)

        # Estimate tool spec tokens
        tools_tokens = estimate_tools_tokens(tool_specs or [])

        # Conversation history already contains the current run's messages because
        # we append them as we go.
        all_messages: List[Dict[str, Any]] = list(self._conversation)

        # Trim to fit context window, preserving recent messages
        # Reserve tokens for the model's response
        response_reserve = min(self.llm.config.max_tokens, self._context_window // 4)
        budget = self._context_window - response_reserve

        trimmed = trim_messages_to_budget(
            all_messages,
            budget=budget,
            system_tokens=system_tokens,
            tools_tokens=tools_tokens,
            preserve_first=max(0, int(preserve_first)),
            preserve_last=max(1, int(preserve_last)),
        )

        messages = [system_msg] + trimmed
        state.token_estimate = estimate_messages_tokens(messages) + tools_tokens
        return messages

    def _history_preserve_counts(self, route: RouteDecision) -> tuple[int, int]:
        """Choose how much conversation history to preserve per route."""
        path = str(getattr(route, "path", "") or "")
        if path in ("casual_chat", "personal_context", "assistant_meta", "general"):
            return 0, 12
        if path in ("planning", "research"):
            return 0, 10
        return 0, 8

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
        return bool(
            re.match(r"^(ok|okay|sure|yes|yep|yeah|continue|go ahead|proceed|do it)\b", s)
        )

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
        markers = (
            "need ",
            "please provide",
            "cannot proceed",
            "can't proceed",
            "unable to continue",
            "to continue,",
            "before i can",
            "missing",
            "i require",
        )
        return any(m in s for m in markers)

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
            r"(?:\s*(?:anything else\??|what(?:'s| is)? next\??|what would you like (?:me )?to do next\??|what do you want(?: me)? to do next\??|how can i help(?: you)?(?: further)?\??|what can i help with\??)\s*)+$",
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
        """Prevent premature generic follow-up prompts during in-progress tasks."""
        src = str(text or "")
        if not src.strip():
            return src, False
        if pending_tool_calls > 0:
            return src, False
        if self._is_blocked_response(src):
            return src, False

        path = str(getattr(route, "path", "") or "")
        action_path = path in ("coding_task", "debug_audit", "planning", "research")
        continuation_turn = route_input_source == "history_augmented" or self._is_ack_turn(prompt_text)
        if not (action_path or continuation_turn):
            return src, False

        cleaned, removed = self._strip_premature_followup(src)
        if not removed:
            return src, False
        return cleaned, True

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
            or "?" in prev_assistant
            or "do you want me" in prev_l
            or "want me to" in prev_l
            or "shall i" in prev_l
            or "can i" in prev_l
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
        return INPUT_CONTINUITY_TEMPLATE.format(
            hint_text="\n".join(f"- {h}" for h in hints),
        ).strip()

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
            return LIBRARY_CONTEXT_TEMPLATE.format(library_text=text)
        except Exception as e:
            log.debug("Library retrieval failed: %s", e)
            return ""

    def _auto_capture_research(self, *, route: RouteDecision, query: str, answer: str) -> None:
        """Persist research-heavy answers into the external library."""
        if not self._library_auto_capture:
            return
        if route.path != "research":
            return
        lib = self._library
        if lib is None:
            return
        q = str(query or "").strip()
        a = str(answer or "").strip()
        if len(q) < 5 or len(a) < 80:
            return
        try:
            lib.add_research_note(
                query=q,
                answer=a,
                source=f"thomas:{getattr(self.llm.config, 'name', 'unknown')}",
                tags=["research", "auto", "route:research"],
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
        mode: str,
        iterations: int,
        peak_context_tokens: int,
        avg_context_tokens: int,
        memory_tokens: int,
        tool_chars_total: int,
        tool_chars_kept: int,
    ) -> Dict[str, Any]:
        usage = getattr(self.llm, "session_usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0)

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

    def _select_tools(
        self,
        prompt: str,
        policy: str = "auto",
        route: Optional[RouteDecision] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Select tool exposure policy for this run.

        policy:
          - "never": never expose tools
          - "always": always expose tools
          - "auto": heuristic based on prompt content
        """
        if len(self.tools) == 0:
            return None

        if policy == "never":
            return None
        if policy == "always":
            return self.tools.get_openai_specs()

        if route is not None and str(route.path) in ("coding_task", "debug_audit", "planning", "research"):
            return self.tools.get_openai_specs()

        if self._is_project_related_prompt(prompt):
            return self.tools.get_openai_specs()

        # Otherwise, keep tools hidden to avoid unnecessary calls.
        return None

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
        max_iterations: Optional[int] = None,
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

        route_input, route_input_source = self._routing_input_text(prompt_text)
        route = self._router.decide(
            route_input,
            requested_mode=mode,
            requested_tools_policy=tools_policy,
        )
        effective_mode = route.mode

        # Mode presets (the caller can still override with max_iterations).
        if max_iterations is not None:
            max_iter = max_iterations
        elif effective_mode == "fast":
            max_iter = 1
        elif effective_mode == "thinking":
            max_iter = min(self.config.max_agent_iterations * 2, 25)
        else:
            max_iter = self.config.max_agent_iterations

        effective_tools_policy = route.tools_policy
        if tools_policy == "auto" and route.tools_policy == "auto":
            if effective_mode == "fast":
                effective_tools_policy = "never"
            elif effective_mode == "thinking":
                effective_tools_policy = "always"

        tool_specs = self._select_tools(prompt_text, policy=effective_tools_policy, route=route)
        preserve_first, preserve_last = self._history_preserve_counts(route)
        state = LoopState()
        iter_token_estimates: List[int] = []
        peak_context_tokens = 0
        tool_chars_total = 0
        tool_chars_kept = 0
        followup_suppressed_count = 0
        memory_text = ""
        continuity_hint = ""
        library_text = ""
        memory_tokens = 0

        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "prompt": prompt_text,
                "route": route.to_dict(),
                "route_input_source": route_input_source,
                "mode": effective_mode,
                "tools_policy": effective_tools_policy,
                "library_enabled": bool(self._library is not None),
                "history_policy": {
                    "preserve_first": int(preserve_first),
                    "preserve_last": int(preserve_last),
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
            library_text = self._retrieve_library(prompt_text, route)
            memory_tokens = (
                estimate_tokens(memory_text)
                + estimate_tokens(continuity_hint)
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
                if library_text:
                    mem = (mem + "\n\n" + library_text).strip() if mem else library_text
            messages = self._build_messages(
                state,
                memory_text=mem,
                tool_specs=tool_specs,
                include_purpose=route.include_purpose,
                preserve_first=preserve_first,
                preserve_last=preserve_last,
            )
            iter_token_estimates.append(int(state.token_estimate))
            peak_context_tokens = max(peak_context_tokens, int(state.token_estimate))

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

            try:
                llm_stream_error: Optional[str] = None
                async for event in self.llm.stream_chat(messages, tool_specs):
                    if event.type == "token":
                        text = event.data["text"]
                        text_chunks.append(text)
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
            if iter_text.strip() == "Understood. How can I assist you further?":
                iter_text = "I didn't answer that. Please ask a specific question."
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

            # Execute tool calls (parallel when multiple)
            tool_results = await self._execute_tools(pending_tool_calls, iteration)
            state.total_tool_calls += len(pending_tool_calls)

            # Yield tool results and add to messages
            for tc, result_event in zip(pending_tool_calls, tool_results):
                yield result_event

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

        usage = getattr(self.llm, "session_usage", None)
        usage_obj = {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }
        avg_context = int(sum(iter_token_estimates) / len(iter_token_estimates)) if iter_token_estimates else 0
        token_report = self._build_token_report(
            prompt_text=prompt_text,
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
        token_report["continuity"] = {
            "route_input_source": route_input_source,
            "followup_suppressed_count": int(followup_suppressed_count),
        }

        # Done
        yield AgentEvent.agent_done(
            text=state.text_response,
            iterations=state.iteration + 1,
            tool_calls=state.total_tool_calls,
            usage=usage_obj,
            token_report=token_report,
        )

    async def _execute_tools(
        self,
        tool_calls: List[Dict[str, Any]],
        iteration: int,
    ) -> List[AgentEvent]:
        """Execute tool calls, running independent calls in parallel."""

        async def _run_one(tc: Dict[str, Any]) -> AgentEvent:
            name = tc["name"]
            tc_id = tc["id"]
            raw_args = tc["arguments"]

            # Parse arguments
            try:
                args = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                return AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={
                        "tool_id": tc_id,
                        "tool_name": name,
                        "result": f"Invalid JSON arguments: {raw_args[:200]}",
                        "result_text": (
                            f"Error: Could not parse tool arguments as JSON.\n"
                            f"Raw arguments: {raw_args[:500]}\n"
                            f"Hint: Make sure the arguments are valid JSON."
                        ),
                        "ok": False,
                        "duration_ms": 0,
                    },
                    iteration=iteration,
                )

            # Execute tool
            start = time.monotonic()
            if self._guarded_tool_runner is not None:
                async def _guarded_executor(call: Dict[str, Any]) -> Dict[str, Any]:
                    tr = await self.tools.execute(str(call.get("name") or ""), call.get("args") or {})
                    return {
                        "ok": bool(tr.ok),
                        "error": tr.error,
                        "data": tr.data,
                        "result_text": tr.to_content(),
                    }

                async def _emit_guardrails_event(evt_type: str, payload: Dict[str, Any]) -> None:
                    cb = self._guardrails_event_cb
                    if cb is None:
                        return
                    try:
                        await cb(evt_type, payload)
                    except Exception as e:
                        log.debug("Guardrails callback failed: %s", e)

                summary_lines: List[str] = []
                for m in self._conversation[-8:]:
                    if not isinstance(m, dict):
                        continue
                    role = str(m.get("role") or "?")
                    content = m.get("content")
                    if isinstance(content, str) and content.strip():
                        summary_lines.append(f"{role}: {content[:220]}")
                conversation_summary = "\n".join(summary_lines)

                guarded = await self._guarded_tool_runner.run(
                    executor=_guarded_executor,
                    tool_call={"id": tc_id, "name": name, "args": args},
                    run_id=self._run_id,
                    session_id=self._session_id,
                    iteration=iteration,
                    cwd=os.getcwd(),
                    sandbox_root=str(self.config.tools.sandbox_path),
                    runtime_root=str(self.config.memory.root_path),
                    conversation_summary=conversation_summary,
                    emit_event=_emit_guardrails_event,
                )

                duration = (time.monotonic() - start) * 1000
                ok = bool(guarded.get("ok", False)) if isinstance(guarded, dict) else True
                if isinstance(guarded, dict):
                    if isinstance(guarded.get("result_text"), str):
                        result_text = guarded.get("result_text", "")
                    elif isinstance(guarded.get("result"), str):
                        result_text = guarded.get("result", "")
                    elif guarded.get("data") is not None:
                        try:
                            result_text = json.dumps(guarded.get("data"), ensure_ascii=False, default=str)
                        except Exception:
                            result_text = str(guarded.get("data"))
                    elif guarded.get("error"):
                        result_text = json.dumps(
                            {"ok": False, "error": str(guarded.get("error"))},
                            ensure_ascii=False,
                        )
                    else:
                        result_text = json.dumps(guarded, ensure_ascii=False, default=str)
                else:
                    result_text = str(guarded)
            else:
                result = await self.tools.execute(name, args)
                duration = (time.monotonic() - start) * 1000
                ok = bool(result.ok)
                result_text = result.to_content()

            return AgentEvent(
                type=EventType.TOOL_RESULT,
                data={
                    "tool_id": tc_id,
                    "tool_name": name,
                    "result": result_text[:4000],  # Summary for event consumers
                    "result_text": result_text,     # Full text for LLM message
                    "ok": ok,
                    "duration_ms": duration,
                },
                iteration=iteration,
            )

        # Run all tool calls in parallel
        if len(tool_calls) > 1:
            results = await asyncio.gather(*[_run_one(tc) for tc in tool_calls])
            return list(results)
        elif tool_calls:
            return [await _run_one(tool_calls[0])]
        return []


# Sentinel for catching connection errors without importing httpx at module level
try:
    import httpx as _httpx
    httpx_ConnectError = _httpx.ConnectError
except ImportError:
    httpx_ConnectError = OSError  # type: ignore[misc,assignment]

