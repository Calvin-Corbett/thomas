"""Intent routing for token-efficient, high-quality replies.

DEPRECATION NOTICE (2026-03-18):
  The IntentRouter and its 8-path classification system are DEPRECATED.
  The dispatch-first architecture (dispatch.py) replaces this with a simple
  binary decision: casual → Thomas replies directly, actionable → workboard.

  This file is KEPT because RouteDecision is still imported by loop_core.py,
  loop_streaming.py, and other modules that expect a RouteDecision object.
  The IntentRouter class still works but is no longer the primary routing
  mechanism for /api/chat.

  See docs/CHAT_EXECUTION_MODEL.md for the current architecture.

Original description:
  Classifies user messages into intent paths, choosing response/tool/memory
  policies per path. Context-aware: accepts prior route hints and follow-up
  signals to avoid misclassification.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

PATH_CASUAL = "casual_chat"
PATH_PERSONAL = "personal_context"
PATH_PLANNING = "planning"
PATH_CODING = "coding_task"
PATH_DEBUG = "debug_audit"
PATH_RESEARCH = "research"
PATH_META = "assistant_meta"
PATH_GENERAL = "general"

# ── Signal Detection Patterns ────────────────────────────────

_WORD_RE = re.compile(r"[A-Za-z0-9_./:\\-]+")
_PATHY_RE = re.compile(r"[A-Za-z]:\\|/[\w.-]+/|\\\\|\.(?:py|ts|js|go|rs|toml|json|md)\b", re.I)
_STACK_RE = re.compile(r"\b(traceback|stack trace|exception|error:|failed|failure)\b", re.I)
_LIVENESS_RE = re.compile(
    r"\b(are you (?:there|working|alive)|you there|still there|ping|status check)\b",
    re.I,
)
_INTEGRATION_RE = re.compile(
    r"\b(telegram|discord|slack|whatsapp|webhook|oauth|integration|integrate)\b",
    re.I,
)
_SETUP_RE = re.compile(r"\b(set ?up|setup|configure|configuration|config|connect|wire up)\b", re.I)
_TROUBLESHOOT_RE = re.compile(r"\b(not working|broken|crash|failing|issue|problem)\b", re.I)

# Code-context words — "fix" only boosts coding when near these
_CODE_CONTEXT_RE = re.compile(
    r"\b(bug|code|function|class|file|module|import|syntax|error|test|repo|commit|"
    r"api|endpoint|server|database|query|variable|method|script)\b",
    re.I,
)
_FIX_RE = re.compile(r"\b(fix|patch|repair)\b", re.I)

_BEHAVIOR_FEEDBACK_RE = re.compile(
    r"\b(how you talk|how you speak|too robotic|sound robotic|talk better|"
    r"less robotic|be more human|conversation style|person skills|"
    r"you('re| are) (dumb|stupid|confusing|annoying|bad at)|"
    r"talking to you (sucks|is bad|is hard))\b",
    re.I,
)
_FRUSTRATION_RE = re.compile(
    r"\b(frustrat\w*|annoy\w*|upset|this sucks|you keep|you always|why do you)\b",
    re.I,
)
_NO_EXECUTION_RE = re.compile(
    r"\b(no task|didn'?t give (?:you )?a task|not asking (?:you )?to code|"
    r"just talking|just chat(?:ting)?|conversation mode|continue talking)\b",
    re.I,
)
_EXECUTION_PREFERENCE_RE = re.compile(
    r"\b(i want|want you to)\b.*\b(program|code|build|implement)\b",
    re.I,
)


@dataclass(frozen=True)
class RouteDecision:
    """Result of intent classification."""

    path: str
    confidence: float
    reasons: list[str]
    mode: str
    tools_policy: str
    include_purpose: bool
    memory_include_global: bool
    memory_include_profile: bool
    memory_budget_tokens: int
    is_followup: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _PathPolicy:
    mode: str
    tools_policy: str
    include_purpose: bool
    memory_include_global: bool
    memory_include_profile: bool
    memory_budget_tokens: int


# Tools policy: "auto" = use tools based on model decision.
# Low-intent chat routes also keep global durable memory enabled so stable
# user/project facts can follow across chats, while per-thread episodes stay isolated.
_POLICY: dict[str, _PathPolicy] = {
    PATH_CASUAL: _PathPolicy(
        mode="auto",
        tools_policy="auto",
        include_purpose=False,
        memory_include_global=True,
        memory_include_profile=True,
        memory_budget_tokens=800,
    ),
    PATH_PERSONAL: _PathPolicy(
        mode="auto",
        tools_policy="auto",
        include_purpose=False,
        memory_include_global=True,
        memory_include_profile=True,
        memory_budget_tokens=800,
    ),
    PATH_PLANNING: _PathPolicy(
        mode="auto",
        tools_policy="auto",
        include_purpose=False,
        memory_include_global=True,
        memory_include_profile=True,
        memory_budget_tokens=900,
    ),
    PATH_CODING: _PathPolicy(
        mode="auto",
        tools_policy="auto",
        include_purpose=False,
        memory_include_global=True,
        memory_include_profile=True,
        memory_budget_tokens=1300,
    ),
    PATH_DEBUG: _PathPolicy(
        mode="auto",
        tools_policy="auto",
        include_purpose=False,
        memory_include_global=True,
        memory_include_profile=True,
        memory_budget_tokens=1500,
    ),
    PATH_RESEARCH: _PathPolicy(
        mode="auto",
        tools_policy="auto",
        include_purpose=False,
        memory_include_global=True,
        memory_include_profile=False,
        memory_budget_tokens=900,
    ),
    PATH_META: _PathPolicy(
        mode="auto",
        tools_policy="auto",
        include_purpose=False,
        memory_include_global=True,
        memory_include_profile=True,
        memory_budget_tokens=700,
    ),
    PATH_GENERAL: _PathPolicy(
        mode="auto",
        tools_policy="auto",
        include_purpose=False,
        memory_include_global=True,
        memory_include_profile=True,
        memory_budget_tokens=800,
    ),
}


class IntentRouter:
    """Context-aware intent router for response policy selection.

    Classifies messages into intent paths using keyword scoring,
    with support for follow-up detection and prior route bias.
    """

    def decide(
        self,
        text: str,
        *,
        requested_mode: str = "auto",
        requested_tools_policy: str = "auto",
        is_followup: bool = False,
        prior_route: str | None = None,
    ) -> RouteDecision:
        """Classify a message and return routing decision.

        Args:
            text: User message
            requested_mode: Override mode
            requested_tools_policy: Override tools policy
            is_followup: Whether this is a follow-up turn
            prior_route: The route from the previous turn

        Returns:
            RouteDecision with path, policies, and confidence
        """
        src = str(text or "").strip()
        lower = src.lower()
        scores: dict[str, float] = {k: 0.0 for k in _POLICY}
        reasons: dict[str, list[str]] = {k: [] for k in _POLICY}

        def add(path: str, weight: float, reason: str) -> None:
            scores[path] += float(weight)
            if len(reasons[path]) < 6:
                reasons[path].append(reason)

        tokens = [t.lower() for t in _WORD_RE.findall(lower)]
        tok_set = set(tokens)

        if not src:
            add(PATH_CASUAL, 1.0, "empty_or_short")

        # ── Structural signals ───────────────────────────────
        if _PATHY_RE.search(src):
            add(PATH_CODING, 2.5, "file_or_path_signal")
        if _STACK_RE.search(src):
            add(PATH_DEBUG, 3.2, "error_signal")
        if _LIVENESS_RE.search(src):
            add(PATH_CASUAL, 3.0, "liveness_check")
        if _INTEGRATION_RE.search(src) and _SETUP_RE.search(src):
            add(PATH_CODING, 2.8, "integration_setup")
        elif _INTEGRATION_RE.search(src):
            add(PATH_CODING, 1.8, "integration_signal")

        # ── Casual + personal ────────────────────────────────
        if tok_set & {"hi", "hello", "hey", "yo", "sup", "whats", "wassup"}:
            add(PATH_CASUAL, 2.4, "greeting")
        if tok_set & {"life", "family", "stress", "anxious", "relationship"}:
            add(PATH_PERSONAL, 2.2, "personal_topic")
        if "my " in lower or "i feel" in lower:
            add(PATH_PERSONAL, 1.0, "self_context")

        # ── Planning ─────────────────────────────────────────
        if tok_set & {"plan", "roadmap", "strategy", "steps", "workflow"}:
            add(PATH_PLANNING, 2.8, "planning_keywords")
        if "how should" in lower or "what's the best way" in lower:
            add(PATH_PLANNING, 1.8, "decision_prompt")

        # ── Coding (context-aware "fix") ─────────────────────
        if tok_set & {"code", "coding", "program", "refactor", "function", "class", "api", "repo", "test"}:
            add(PATH_CODING, 2.8, "coding_keywords")
        if tok_set & {"build", "implement", "implementation", "commit"}:
            add(PATH_CODING, 1.4, "implementation_intent")

        # "fix" only boosts coding if code context is present
        if _FIX_RE.search(src):
            if _CODE_CONTEXT_RE.search(src):
                add(PATH_CODING, 2.0, "fix_with_code_context")
            elif _BEHAVIOR_FEEDBACK_RE.search(src):
                add(PATH_META, 3.0, "fix_conversation_style")
            else:
                add(PATH_GENERAL, 0.5, "ambiguous_fix")

        if _EXECUTION_PREFERENCE_RE.search(src):
            add(PATH_CODING, 2.4, "execution_preference")
        if _NO_EXECUTION_RE.search(src):
            add(PATH_CASUAL, 4.6, "no_execution_intent")
            add(PATH_META, 2.0, "no_execution_meta")

        # ── Debug/security ───────────────────────────────────
        if tok_set & {"debug", "bug", "audit", "security", "vulnerability", "regression"}:
            add(PATH_DEBUG, 3.0, "debug_keywords")
        if tok_set & {"latency", "performance", "cost"}:
            add(PATH_DEBUG, 1.3, "optimization_signal")
        if _TROUBLESHOOT_RE.search(src) and _CODE_CONTEXT_RE.search(src):
            add(PATH_DEBUG, 2.6, "troubleshoot_code")
        elif _TROUBLESHOOT_RE.search(src):
            add(PATH_GENERAL, 1.0, "troubleshoot_ambiguous")
        if re.search(r"\bsettings?\b", lower) and re.search(r"\b(reset|resetting|restart|restarting)\b", lower):
            add(PATH_DEBUG, 2.4, "state_reset_troubleshoot")
            add(PATH_CODING, 0.8, "state_reset_code_signal")

        # ── Research ─────────────────────────────────────────
        if tok_set & {"research", "compare", "latest", "news", "lookup", "online"}:
            add(PATH_RESEARCH, 2.5, "research_keywords")
        if re.search(r"^\s*research\b", lower):
            add(PATH_RESEARCH, 1.2, "research_prefix")
        if "look online" in lower or "search for" in lower:
            add(PATH_RESEARCH, 1.9, "explicit_lookup")

        # ── Assistant meta ───────────────────────────────────
        if _BEHAVIOR_FEEDBACK_RE.search(src):
            add(PATH_META, 3.5, "behavior_feedback")
            add(PATH_PERSONAL, 1.0, "behavior_tone")
        if "how do you work" in lower or "what are you" in lower:
            add(PATH_META, 3.0, "self_model")
        if _FRUSTRATION_RE.search(src):
            add(PATH_PERSONAL, 1.6, "frustration_signal")
            add(PATH_META, 1.0, "frustration_meta")

        # ── Follow-up bias ───────────────────────────────────
        if is_followup and prior_route and prior_route in scores:
            add(prior_route, 2.0, "followup_continuity")

        # ── Backstop ─────────────────────────────────────────
        add(PATH_GENERAL, 0.4, "general_backstop")

        chosen, confidence = self._choose(scores)
        rule = _POLICY.get(chosen, _POLICY[PATH_GENERAL])
        chosen_reasons = reasons.get(chosen, []) or ["fallback"]

        mode = rule.mode if str(requested_mode or "auto") == "auto" else str(requested_mode)
        tools_policy = (
            rule.tools_policy if str(requested_tools_policy or "auto") == "auto" else str(requested_tools_policy)
        )

        return RouteDecision(
            path=chosen,
            confidence=confidence,
            reasons=chosen_reasons,
            mode=mode,
            tools_policy=tools_policy,
            include_purpose=rule.include_purpose,
            memory_include_global=rule.memory_include_global,
            memory_include_profile=rule.memory_include_profile,
            memory_budget_tokens=rule.memory_budget_tokens,
            is_followup=is_followup,
        )

    def _choose(self, scores: dict[str, float]) -> tuple[str, float]:
        """Select highest-scoring path with confidence."""
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if not ranked:
            return PATH_GENERAL, 0.25
        top_path, top_score = ranked[0]
        if top_score <= 0:
            return PATH_GENERAL, 0.25
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        conf = top_score / max(0.01, (top_score + second_score))
        return top_path, max(0.35, min(0.99, conf))
