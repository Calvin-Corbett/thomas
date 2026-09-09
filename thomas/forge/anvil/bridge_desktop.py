"""Desktop-operator bridge: types prompts into an open Claude Code window via PC control.

DISABLED by default (``[evolve.claude_bridge].enabled = false``).
``preview()`` never touches the PC. ``dispatch(..., confirm=True)`` is the only path
that can send keystrokes, and it still refuses unless ALL gates pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .bridge_config import BridgeConfig, emergency_stop_active, emergency_stop_path
from .bridge_prompts import compose_claude_prompt


class DesktopDriver(Protocol):
    """Minimal surface the bridge needs from desktop_operator (injected for tests)."""

    def find_window(self, match: str) -> str | None: ...
    def type_text(self, text: str) -> None: ...
    def press_enter(self) -> None: ...


@dataclass
class DispatchResult:
    dispatched: bool
    reason: str
    prompt: str
    planned_actions: list[str] = field(default_factory=list)
    window: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dispatched": self.dispatched,
            "reason": self.reason,
            "window": self.window,
            "planned_actions": self.planned_actions,
            "prompt_chars": len(self.prompt),
        }


class ClaudeCodeBridge:
    """Dispatches a build task to Claude Code via the desktop, behind hard safety gates."""

    def __init__(
        self,
        config: BridgeConfig | None = None,
        driver: DesktopDriver | None = None,
        audit: Any = None,
    ) -> None:
        self.cfg = config or BridgeConfig()
        self.driver = driver
        self._audit = audit if audit is not None else (lambda _e: None)

    def preview(self, goal: str, *, definition: str = "", plan: str = "") -> DispatchResult:
        """Return exactly what WOULD be typed + the planned actions. Touches nothing."""
        prompt = compose_claude_prompt(goal, definition=definition, plan=plan, branch_only=self.cfg.branch_only)
        return DispatchResult(
            dispatched=False,
            reason="preview only (no PC control)",
            prompt=prompt,
            planned_actions=[
                f"find a window whose title contains {self.cfg.window_match!r}",
                f"type the {len(prompt)}-char prompt into it",
                "press Enter to submit",
            ],
        )

    def dispatch(self, goal: str, *, confirm: bool = False, definition: str = "", plan: str = "") -> DispatchResult:
        """Type the prompt into Claude Code — only if every safety gate passes."""
        prev = self.preview(goal, definition=definition, plan=plan)
        prompt = prev.prompt

        def refuse(reason: str) -> DispatchResult:
            self._audit({"event": "claude_dispatch_refused", "reason": reason})
            return DispatchResult(False, f"refused: {reason}", prompt, prev.planned_actions)

        if not self.cfg.enabled:
            return refuse("claude bridge is disabled ([evolve.claude_bridge].enabled = false)")
        if self.cfg.require_confirmation and not confirm:
            return refuse("explicit human confirmation required before controlling the PC (pass confirm=True)")
        if emergency_stop_active():
            return refuse(f"emergency stop active ({emergency_stop_path()})")
        if len(prompt) > self.cfg.max_prompt_chars:
            return refuse(f"prompt too large ({len(prompt)} > {self.cfg.max_prompt_chars} chars)")
        if self.driver is None:
            return refuse("no desktop driver available")
        try:
            window = self.driver.find_window(self.cfg.window_match)
        except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as exc:
            return refuse(f"window lookup failed: {exc}")
        if not window:
            return refuse(f"no window matching {self.cfg.window_match!r} (will not type into an unknown window)")

        self._audit({"event": "claude_dispatch_typing", "window": window, "chars": len(prompt)})
        self.driver.type_text(prompt)
        self.driver.press_enter()
        self._audit({"event": "claude_dispatched", "window": window})
        return DispatchResult(True, "dispatched to Claude Code", prompt, prev.planned_actions, window=window)


def compose_from_funnel(
    goal: str,
    *,
    project_root: Path | str = ".",
    profile: str = "",
    funnel_config: Any = None,
    model_call: Any = None,
    model_info: Any = None,
) -> tuple[str, str]:
    """Run the funnel (definition + product stages) to converge a (definition, plan) for ``goal``.

    Uses a no-op capture builder so NO code is built — we only want the converged
    plan text to hand to Claude Code. Returns (definition_text, plan_text). The
    model_call/funnel_config are injectable (tests pass fakes; production resolves
    real providers).
    """
    from .evolve_funnel import run_funnel_session

    def _capture_builder(_root, **_kw):
        return {
            "ok": True,
            "session": {
                "session_id": "bridge-compose",
                "promotable": False,
                "changed_files": [],
                "verification": [],
                "status": "compose_only",
                "session_rejections": [],
                "diff_path": "",
            },
        }

    out = run_funnel_session(
        str(project_root),
        goal=goal,
        profile=profile,
        builder=_capture_builder,
        model_call=model_call,
        model_info=model_info,
        funnel_config=funnel_config,
    )
    stages = ((out.get("session") or {}).get("funnel") or {}).get("stages") or {}
    definition = str((stages.get("definition") or {}).get("text") or "")
    plan = str((stages.get("product") or {}).get("text") or "")
    return definition, plan


def connect_desktop_operator_driver(workflow_profile: str = "claude_code") -> DesktopDriver | None:
    """Best-effort live driver over ``thomas.desktop_operator`` (the guarded host service).

    Returns a driver ONLY if the desktop host service + an allowlisted workflow
    profile are reachable; otherwise returns None so the bridge fails safe (refuses).
    """
    try:
        from thomas.desktop_operator import get_global_desktop_operator_manager
    except (ImportError, RuntimeError, OSError):
        return None
    try:
        manager = get_global_desktop_operator_manager()
    except (RuntimeError, OSError, ValueError, TypeError, AttributeError):
        return None
    return _DesktopOperatorDriver(manager, workflow_profile)


class _DesktopOperatorDriver:
    """Adapter from the bridge's tiny DesktopDriver surface onto desktop_operator.

    Conservative + fail-safe: any error surfaces as 'no window' / no-op so the bridge
    refuses rather than typing into the wrong place.
    """

    def __init__(self, manager: Any, workflow_profile: str) -> None:
        self._m = manager
        self._profile = workflow_profile
        self._session: str | None = None

    def find_window(self, match: str) -> str | None:
        try:
            start = getattr(self._m, "start_session", None)
            list_windows = getattr(self._m, "list_windows", None)
            bind = getattr(self._m, "bind_window", None)
            if not (start and list_windows and bind):
                return None
            sess = start(workflow_profile=self._profile)
            self._session = sess.get("session_id") if isinstance(sess, dict) else getattr(sess, "session_id", None)
            if not self._session:
                return None
            windows = list_windows(self._session)
            items = windows.get("windows") if isinstance(windows, dict) else windows
            for w in items or []:
                title = str((w.get("title") if isinstance(w, dict) else getattr(w, "title", "")) or "")
                if match in title:
                    bind(self._session, window=(w.get("id") if isinstance(w, dict) else getattr(w, "id", None)))
                    return title
            return None
        except (RuntimeError, OSError, ValueError, TypeError, AttributeError):
            return None

    def type_text(self, text: str) -> None:
        act = getattr(self._m, "act", None)
        if act and self._session:
            act(self._session, action="type", payload={"text": text})

    def press_enter(self) -> None:
        act = getattr(self._m, "act", None)
        if act and self._session:
            act(self._session, action="press_keys", payload={"keys": ["enter"]})
