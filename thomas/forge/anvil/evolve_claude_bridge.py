"""Claude-Code build bridge: let Thomas-evolve dispatch a build task to an external
coding agent (Claude Code) by typing a composed prompt into it via the existing
``desktop_operator``.

This is the most safety-sensitive capability in the evolve system (it controls the
PC and drives another coding agent), so it is gated HARD and SAFE BY DEFAULT:

  * DISABLED by default (``[evolve.claude_bridge].enabled = false``).
  * ``preview()`` never touches the PC — it returns exactly what WOULD be typed.
  * ``dispatch(..., confirm=True)`` is the only path that can send keystrokes, and
    it still refuses unless ALL gates pass: enabled, explicitly confirmed (human
    approval), no emergency-stop flag, a real desktop driver, AND a window whose
    title matches the configured Claude-Code match (it will never type into an
    unknown/wrong window).
  * Every dispatch is audited.
  * The composed prompt instructs Claude Code to work on a BRANCH and stop before
    merging — results are NEVER auto-applied; the existing fail-closed promotion
    gate still judges everything. The bridge is a dispatcher, not an approver.

Public API — all implementation lives in the sub-modules below; importing from
this module continues to work without any change to callers.
"""

from __future__ import annotations

from typing import Any

from . import bridge_desktop as _bridge_desktop
from . import dispatch_agent_loop as _dispatch_agent_loop
from . import dispatch_claude_cli as _dispatch_claude_cli

# --- config & kill-switch ---
from .bridge_config import BridgeConfig, emergency_stop_active, emergency_stop_path

# --- desktop bridge ---
from .bridge_desktop import (
    DesktopDriver,
    DispatchResult,
    compose_from_funnel,
    connect_desktop_operator_driver,
)

# --- prompt composition ---
from .bridge_prompts import compose_claude_prompt, compose_fix_prompt, compose_headless_prompt

# --- engine verification ---
from .build_verify import verify_python_changes

# --- GPT / AgentLoop dispatch ---
from .dispatch_agent_loop import (
    CHATGPT_NOT_CONNECTED_MSG,
    OPENAI_CODEX_PROFILE,
    _AgentLoopForgeTranslator,
    chatgpt_oauth_connected,
)

# --- claude CLI dispatch ---
from .dispatch_claude_cli import SAFE_CLI_TOOLS, CliDispatchResult

# --- forge-event streaming, insight distillation, stream helpers ---
from .forge_event_stream import (
    FORGE_EVENT_KEY,
    ClaudeStreamTranslator,
    _default_emit,
    _distill_insight,
    _HybridByteDecoder,
    _insight_word_set,
    _insights_similar,
    _stream_cli,
    _StreamState,
    _strip_list_artifacts,
    translate_claude_event,
)


def _sync_legacy_kill_switches() -> None:
    """Keep old evolve_claude_bridge monkeypatches effective after the module split."""
    _bridge_desktop.emergency_stop_active = emergency_stop_active
    _bridge_desktop.emergency_stop_path = emergency_stop_path
    _dispatch_claude_cli.emergency_stop_active = emergency_stop_active
    _dispatch_claude_cli.emergency_stop_path = emergency_stop_path
    _dispatch_agent_loop.emergency_stop_active = emergency_stop_active
    _dispatch_agent_loop.emergency_stop_path = emergency_stop_path


class ClaudeCodeBridge(_bridge_desktop.ClaudeCodeBridge):
    def dispatch(self, *args: Any, **kwargs: Any) -> DispatchResult:
        _sync_legacy_kill_switches()
        return super().dispatch(*args, **kwargs)


def dispatch_via_claude_cli(*args: Any, **kwargs: Any) -> CliDispatchResult:
    _sync_legacy_kill_switches()
    return _dispatch_claude_cli.dispatch_via_claude_cli(*args, **kwargs)


def dispatch_via_agent_loop(*args: Any, **kwargs: Any) -> CliDispatchResult:
    _sync_legacy_kill_switches()
    return _dispatch_agent_loop.dispatch_via_agent_loop(*args, **kwargs)


__all__ = [
    # config
    "BridgeConfig",
    "emergency_stop_active",
    "emergency_stop_path",
    # prompts
    "compose_claude_prompt",
    "compose_fix_prompt",
    "compose_headless_prompt",
    # desktop bridge
    "ClaudeCodeBridge",
    "DesktopDriver",
    "DispatchResult",
    "compose_from_funnel",
    "connect_desktop_operator_driver",
    # streaming
    "FORGE_EVENT_KEY",
    "ClaudeStreamTranslator",
    "_HybridByteDecoder",
    "_StreamState",
    "_default_emit",
    "_distill_insight",
    "_insight_word_set",
    "_insights_similar",
    "_stream_cli",
    "_strip_list_artifacts",
    "translate_claude_event",
    # verification
    "verify_python_changes",
    # claude CLI dispatch
    "SAFE_CLI_TOOLS",
    "CliDispatchResult",
    "dispatch_via_claude_cli",
    # GPT / AgentLoop dispatch
    "CHATGPT_NOT_CONNECTED_MSG",
    "OPENAI_CODEX_PROFILE",
    "_AgentLoopForgeTranslator",
    "chatgpt_oauth_connected",
    "dispatch_via_agent_loop",
]
