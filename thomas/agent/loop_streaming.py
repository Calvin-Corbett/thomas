"""Streaming, token management, memory, and library functions for agent loop.

Provides:
- TPM (tokens per minute) rate limiting
- Memory context retrieval and policy application
- Research library integration
- Event recording
- Token budgeting and usage reporting
"""

from __future__ import annotations

import inspect
import logging
import os
import threading
import time
from typing import TYPE_CHECKING, Any

from thomas.agent.prompt_templates import format_library_context

if TYPE_CHECKING:
    from thomas.agent.loop_core import AgentLoop
    from thomas.agent.routing import RouteDecision

log = logging.getLogger(__name__)

_MEMORY_RETRIEVAL_TIMEOUT_S = 10.0
_MEMORY_INTERRUPT_JOIN_S = 0.5

_MEMORY_POLICY_WARNED_SET: set[int] = set()
def _context_preserve_mode(agent: AgentLoop) -> str:
    """Read the current context-preserve behavior for memory policy."""
    if agent is None:
        return "default"
    return str(os.environ.get("THOMAS_CONTEXT_PRESERVE_MODE", "default")).strip().lower()


def _should_preserve_context(agent: AgentLoop) -> bool:
    """Return true when low-intent routes should keep broader memory state."""
    mode = _context_preserve_mode(agent)
    return mode in {"continuous", "persistent", "high_context", "chatty"}


def retrieve_memory(
    agent: AgentLoop,
    prompt: str,
    mode: str = "auto",
    *,
    budget_override: int | None = None,
) -> str:
    """Retrieve memory context for the prompt (if memory engine available).

    Returns the memory context text, or a warning message if retrieval fails or memory is empty/irrelevant.
    Includes timing information to detect slow memory operations.
    """
    if agent._memory is None or not agent._memory.started:
        return ""
    if bool(getattr(agent, "_memory_retrieval_policy_blocked", False)):
        log.warning("Memory retrieval skipped because the requested policy was not applied")
        return ""

    start_time = time.time()
    try:
        budget = max(300, int(budget_override or agent.config.memory.context_budget))
        query_thread: str | None = None if agent._memory_retrieval_scope == "all" else agent._thread_id

        # Retrieve memory with timeout protection
        result_container = [None]
        exception_container = [None]

        def _do_retrieve():
            try:
                result_container[0] = agent._memory.retrieve(
                    query=prompt,
                    thread=query_thread,
                    budget=budget,
                    mode=mode,
                )
            except Exception as e:
                exception_container[0] = e

        retrieval_thread = threading.Thread(target=_do_retrieve, daemon=True)
        retrieval_thread.start()
        retrieval_thread.join(timeout=_MEMORY_RETRIEVAL_TIMEOUT_S)

        if retrieval_thread.is_alive():
            log.warning("Memory retrieval timed out after %.1fs", _MEMORY_RETRIEVAL_TIMEOUT_S)
            interrupt = getattr(agent._memory, "interrupt_retrieval", None)
            if callable(interrupt):
                try:
                    interrupt()
                except (OSError, RuntimeError) as exc:
                    log.debug("Memory retrieval interrupt failed: %s", exc)
                retrieval_thread.join(timeout=_MEMORY_INTERRUPT_JOIN_S)
            # FIX (2026-03-18): Return empty instead of a message that gets
            # injected into the prompt and confuses the model.
            return ""

        if exception_container[0]:
            raise exception_container[0]

        ctx = result_container[0]
        retrieved_text = ctx.text if ctx else ""
        elapsed_ms = (time.time() - start_time) * 1000

        # Check if memory was actually retrieved
        if not retrieved_text or not retrieved_text.strip():
            log.debug("Memory retrieval returned empty text (%.1f ms)", elapsed_ms)
            # FIX (2026-03-18): Return empty string instead of a misleading
            # "[Memory unavailable]" message. That message was getting injected
            # into the system prompt and confusing the model. Empty string = no
            # memory context, which is the honest state.
            return ""

        # FIX (2026-03-18): Removed the strict relevance threshold (was 0.1).
        # The old check used simple token overlap, which failed badly for
        # topic-switch scenarios (user talking about donuts but memory has
        # code context). The LLM is far better at deciding what's relevant
        # from memory than a token-overlap heuristic. Always include
        # retrieved memory and let the model sort it out.
        log.debug("Memory retrieved (%.1f ms); frontier model owns relevance", elapsed_ms)
        return retrieved_text

    except Exception as e:  # REVIEWED: log-and-continue — optional feature, fallback to empty
        elapsed_ms = (time.time() - start_time) * 1000
        log.warning("Memory retrieval failed after %.1f ms: %s", elapsed_ms, e)
        # FIX (2026-03-18): Return empty, not a confusing message.
        return ""


def apply_memory_policy(agent: AgentLoop, route: RouteDecision) -> None:
    """Apply per-turn memory policy to backends that support it."""
    agent._memory_retrieval_policy_blocked = False
    if agent._memory is None or not agent._memory.started:
        return

    pref_pins_only = getattr(agent, "_memory_pins_only_pref", None)
    pins_only = bool(pref_pins_only) if pref_pins_only is not None else False
    setter = getattr(agent._memory, "set_thread_memory_policy", None)
    if not callable(setter):
        agent._memory_retrieval_policy_blocked = pins_only
        return

    include_thread = True
    include_global = bool(route.memory_include_global)
    include_profile = bool(route.memory_include_profile)

    pref_include_thread = getattr(agent, "_memory_include_thread_pref", None)
    if pref_include_thread is not None:
        include_thread = bool(pref_include_thread)
    pref_include_global = getattr(agent, "_memory_include_global_pref", None)
    if pref_include_global is not None:
        include_global = bool(pref_include_global)
    pref_include_profile = getattr(agent, "_memory_include_profile_pref", None)
    if pref_include_profile is not None:
        include_profile = bool(pref_include_profile)
    economy_include_profile_cap = getattr(agent, "_memory_include_profile_economy_cap", None)
    if economy_include_profile_cap is not None:
        include_profile = bool(include_profile) and bool(economy_include_profile_cap)

    pref_max_pack_tokens = getattr(agent, "_memory_max_pack_tokens_pref", None)
    pref_max_results = getattr(agent, "_memory_max_results_pref", None)
    pref_decay_half_life_hours = getattr(agent, "_memory_decay_half_life_hours_pref", None)
    pref_auto_compact_enabled = getattr(agent, "_memory_auto_compact_enabled_pref", None)
    pref_auto_compact_episode_threshold = getattr(agent, "_memory_auto_compact_episode_threshold_pref", None)
    pref_auto_compact_min_interval_hours = getattr(agent, "_memory_auto_compact_min_interval_hours_pref", None)
    pref_auto_optimize_enabled = getattr(agent, "_memory_auto_optimize_enabled_pref", None)
    pref_auto_optimize_waste_threshold = getattr(agent, "_memory_auto_optimize_waste_threshold_pref", None)
    pref_auto_optimize_min_interval_hours = getattr(agent, "_memory_auto_optimize_min_interval_hours_pref", None)

    budget_tokens = max(300, int(pref_max_pack_tokens or route.memory_budget_tokens))
    path = str(getattr(route, "path", "") or "")
    if (
        pref_include_global is None
        and _should_preserve_context(agent)
        and path in {"casual_chat", "personal_context", "assistant_meta", "general"}
    ):
        include_global = True
        budget_tokens = max(budget_tokens, 1500)

    desired_policy: dict[str, Any] = {
        "enabled": True,
        "include_thread": include_thread,
        "include_global": include_global,
        "include_profile": include_profile,
        "pins_only": pins_only,
        "max_pack_tokens": budget_tokens,
    }
    if pref_max_results is not None:
        desired_policy["max_results"] = int(pref_max_results)
    if pref_decay_half_life_hours is not None:
        desired_policy["decay_half_life_hours"] = float(pref_decay_half_life_hours)
    if pref_auto_compact_enabled is not None:
        desired_policy["auto_compact_enabled"] = bool(pref_auto_compact_enabled)
    if pref_auto_compact_episode_threshold is not None:
        desired_policy["auto_compact_episode_threshold"] = int(pref_auto_compact_episode_threshold)
    if pref_auto_compact_min_interval_hours is not None:
        desired_policy["auto_compact_min_interval_hours"] = float(pref_auto_compact_min_interval_hours)
    if pref_auto_optimize_enabled is not None:
        desired_policy["auto_optimize_enabled"] = bool(pref_auto_optimize_enabled)
    if pref_auto_optimize_waste_threshold is not None:
        desired_policy["auto_optimize_waste_threshold"] = float(pref_auto_optimize_waste_threshold)
    if pref_auto_optimize_min_interval_hours is not None:
        desired_policy["auto_optimize_min_interval_hours"] = float(pref_auto_optimize_min_interval_hours)

    getter = getattr(agent._memory, "thread_memory_policy", None)
    if callable(getter):
        try:
            current = getter(agent._thread_id)
            if isinstance(current, dict) and all(current.get(key) == value for key, value in desired_policy.items()):
                return
        except Exception:
            pass

    warning_issued = bool(getattr(agent, "_memory_policy_warning_issued", False))
    warning_key = id(setter)
    try:
        signature = inspect.signature(setter)
    except (TypeError, ValueError):
        signature = None

    def _accepts_kwarg(name: str, signature: inspect.Signature | None) -> bool:
        if signature is None:
            return False
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()):
            return True
        return name in signature.parameters

    policy_kwargs: dict[str, Any] = {}
    for key, value in desired_policy.items():
        target_key = key
        if (
            key == "max_pack_tokens"
            and not _accepts_kwarg("max_pack_tokens", signature)
            and _accepts_kwarg("budget_tokens", signature)
        ):
            target_key = "budget_tokens"
        if _accepts_kwarg(target_key, signature):
            policy_kwargs[target_key] = value
    if pins_only and "pins_only" not in policy_kwargs:
        agent._memory_retrieval_policy_blocked = True
        return

    try:
        setter(agent._thread_id, **policy_kwargs)
        return
    except Exception as e:
        if isinstance(e, TypeError) and "budget_tokens" in str(e) and "budget_tokens" in policy_kwargs:
            fallback_kwargs = dict(policy_kwargs)
            fallback_kwargs.pop("budget_tokens", None)
            fallback_kwargs["max_pack_tokens"] = budget_tokens
            try:
                setter(agent._thread_id, **fallback_kwargs)
                return
            except Exception as fallback_err:
                agent._memory_retrieval_policy_blocked = pins_only
                if not warning_issued and warning_key not in _MEMORY_POLICY_WARNED_SET:
                    _MEMORY_POLICY_WARNED_SET.add(warning_key)
                    warning_issued = True
                    agent._memory_policy_warning_issued = True
                    log.warning("Memory policy set failed: %s", fallback_err)
                return

        if not warning_issued and warning_key not in _MEMORY_POLICY_WARNED_SET:
            _MEMORY_POLICY_WARNED_SET.add(warning_key)
            warning_issued = True
            agent._memory_policy_warning_issued = True
            log.warning("Memory policy set failed: %s", e)
        agent._memory_retrieval_policy_blocked = pins_only


# Route paths whose turns may draw on the library.
#
# ``model_owned`` is the ONLY path IntentRouter produces for a natural-language
# turn since 69bbbab0 landed model-owned routing; the classifier-era paths below
# survive only for callers that build a RouteDecision explicitly. Leaving
# ``model_owned`` out made this whole function dead code for every real chat turn
# -- 69bbbab0 added ``model_owned`` to the sibling route allowlists in
# loop_core.py (_history_preserve_counts / _history_token_cap) and missed these
# two. Whether the context is affordable stays a dial decision
# (RuntimeOverheadPolicy.include_library_context, plus the benchmark_mode check
# at the call site); Thomas still does not read the user's prose to decide.
_LIBRARY_CONTEXT_ROUTES = frozenset({"model_owned", "research", "planning", "debug_audit", "coding_task"})


def retrieve_library(agent: AgentLoop, prompt: str, route: RouteDecision) -> str:
    """Retrieve context from the long-form research library.

    Returns formatted library context, empty string when the route does not
    qualify or nothing relevant is stored, or a warning message on failure.
    """
    lib = agent._library
    if lib is None:
        return ""
    if route.path not in _LIBRARY_CONTEXT_ROUTES:
        return ""
    q = str(prompt or "").strip()
    if not q:
        return ""

    start_time = time.time()
    try:
        budget = max(250, int(route.memory_budget_tokens // 2))
        text = lib.build_context(query=q, max_tokens=budget, limit=4)
        elapsed_ms = (time.time() - start_time) * 1000

        if not text:
            # An empty result is the normal case for a fresh or small library,
            # not a failure. It must not put "[Library context unavailable]" in
            # the system prompt of every turn -- which is what would happen now
            # that ordinary model-owned turns reach this code, since a fresh
            # install's library is empty by definition.
            #
            # retrieve_memory above had exactly this bug and it was fixed on
            # 2026-03-18 ("Return empty string instead of a misleading
            # '[Memory unavailable]' message ... Empty string = no memory
            # context, which is the honest state"). That fix never reached this
            # function because the route allowlist kept it unreachable.
            log.debug("Library had no matching entry (%.1f ms)", elapsed_ms)
            return ""

        log.debug("Library context retrieved successfully (%.1f ms)", elapsed_ms)
        return format_library_context(text)

    except Exception as e:  # REVIEWED: log-and-continue — optional library retrieval, fallback to warning message
        elapsed_ms = (time.time() - start_time) * 1000
        log.warning("Library retrieval failed after %.1f ms: %s", elapsed_ms, e)
        return "[Library context unavailable]"


# Routes whose answers are worth auto-capturing into the library. Same staleness
# as _LIBRARY_CONTEXT_ROUTES above: without ``model_owned`` the
# THOMAS_LIBRARY_AUTO_CAPTURE_RESEARCH dial (default on) could never capture
# anything from a real turn.
_LIBRARY_CAPTURE_ROUTES = frozenset({"model_owned", "research", "planning", "debug_audit", "coding_task"})
# Non-research routes need a longer answer to be worth persisting.
#
# ``model_owned`` takes the general 200 floor, not research's 80. The 80 floor was
# earned by the router having already established the turn WAS research; a
# model-owned turn carries no such evidence, and it now covers every chat turn,
# so granting it a lower bar than a classified planning or debug turn would
# invert the design.
_LIBRARY_CAPTURE_MIN_CHARS = {
    "model_owned": 200,
    "research": 80,
    "planning": 200,
    "debug_audit": 200,
    "coding_task": 300,
}


def auto_capture_research(
    agent: AgentLoop,
    *,
    route: RouteDecision,
    query: str,
    answer: str,
    job_type: str | None = None,
) -> None:
    """Persist research-heavy answers into the external library."""
    if not agent._library_auto_capture:
        return
    if str(job_type or "").strip().lower() == "benchmark":
        return
    rpath = str(route.path or "")
    if rpath not in _LIBRARY_CAPTURE_ROUTES:
        return
    lib = agent._library
    if lib is None:
        return
    q = str(query or "").strip()
    a = str(answer or "").strip()
    min_chars = _LIBRARY_CAPTURE_MIN_CHARS.get(rpath, 200)
    if len(q) < 5 or len(a) < min_chars:
        return
    try:
        lib.add_research_note(
            query=q,
            answer=a,
            source=f"thomas:{getattr(agent.llm.config, 'name', 'unknown')}",
            tags=["research", "auto", f"route:{rpath}"],
        )
    except Exception as e:  # REVIEWED: log-and-continue — optional library auto-capture
        log.debug("Library auto-capture skipped: %s", e)


def record_event(agent: AgentLoop, etype: str, text: str) -> None:
    """Record an event in memory (if memory engine available)."""
    if agent._memory is None or not agent._memory.started:
        return
    try:
        agent._memory.add_event(agent._thread_id, etype, text)
    except Exception as e:  # REVIEWED: log-and-continue — optional memory event recording
        log.warning("Memory record failed: %s", e)


def build_token_report(
    agent: AgentLoop,
    *,
    prompt_text: str,
    usage_obj: dict[str, int],
    mode: str,
    iterations: int,
    peak_context_tokens: int,
    avg_context_tokens: int,
    memory_tokens: int,
    tool_chars_total: int,
    tool_chars_kept: int,
) -> dict[str, Any]:
    """Build a comprehensive token usage report."""
    prompt_tokens = int(usage_obj.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage_obj.get("completion_tokens", 0) or 0)
    total_tokens = int(usage_obj.get("total_tokens", 0) or 0)

    tool_chars_dropped = max(0, int(tool_chars_total) - int(tool_chars_kept))
    tool_drop_ratio = (tool_chars_dropped / tool_chars_total) if tool_chars_total > 0 else 0.0
    prompt_to_completion = prompt_tokens / max(1, completion_tokens)
    memory_share = memory_tokens / max(1, peak_context_tokens)

    flags: list[dict[str, str]] = []
    suggestions: list[str] = []

    if prompt_to_completion >= 3.0 and prompt_tokens >= 1_200:
        flags.append(
            {
                "kind": "prompt_overhead",
                "severity": "high",
                "detail": "Prompt tokens are much higher than completion tokens.",
            }
        )
        suggestions.append("Trim conversation aggressively or reduce memory context budget.")

    if memory_share >= 0.35 and memory_tokens >= 600:
        flags.append(
            {
                "kind": "memory_overhead",
                "severity": "medium",
                "detail": "Memory context is consuming a large fraction of prompt context.",
            }
        )
        suggestions.append("Lower memory context budget or tighten memory retrieval mode.")

    if tool_drop_ratio >= 0.30 and tool_chars_total >= 8_000:
        flags.append(
            {
                "kind": "tool_output_waste",
                "severity": "medium",
                "detail": "Large tool outputs were generated but heavily truncated.",
            }
        )
        suggestions.append("Request narrower file ranges and more targeted tool outputs.")

    try:
        context_window = int(getattr(agent, "_context_window", 0) or 0)
    except (TypeError, ValueError):
        context_window = 0
    if context_window > 0 and peak_context_tokens >= int(context_window * 0.85):
        flags.append(
            {
                "kind": "context_pressure",
                "severity": "high",
                "detail": "Context window was near capacity.",
            }
        )
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


def normalize_usage(prompt_tokens: Any, completion_tokens: Any, total_tokens: Any) -> dict[str, int]:
    """Normalize and validate token counts."""
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


def session_usage_snapshot(agent: AgentLoop) -> dict[str, int]:
    """Get current session usage from LLM client."""
    usage = getattr(agent.llm, "session_usage", None)
    return normalize_usage(
        getattr(usage, "prompt_tokens", 0),
        getattr(usage, "completion_tokens", 0),
        getattr(usage, "total_tokens", 0),
    )


def usage_from_event_payload(payload: Any) -> dict[str, int]:
    """Extract usage from event payload (dict or object)."""
    if isinstance(payload, dict):
        return normalize_usage(
            payload.get("prompt_tokens", 0),
            payload.get("completion_tokens", 0),
            payload.get("total_tokens", 0),
        )
    return normalize_usage(
        getattr(payload, "prompt_tokens", 0),
        getattr(payload, "completion_tokens", 0),
        getattr(payload, "total_tokens", 0),
    )


def usage_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """Calculate the difference between two usage snapshots."""
    return normalize_usage(
        int(after.get("prompt_tokens", 0) or 0) - int(before.get("prompt_tokens", 0) or 0),
        int(after.get("completion_tokens", 0) or 0) - int(before.get("completion_tokens", 0) or 0),
        int(after.get("total_tokens", 0) or 0) - int(before.get("total_tokens", 0) or 0),
    )
