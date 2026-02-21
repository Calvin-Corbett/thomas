"""Intent routing policy for token-efficient, high-quality replies.

This module provides a lightweight flowchart-like router:
- classify the user's latest message into an intent path
- choose response/tool/memory policies per path
- keep expensive context for coding/debug turns only
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple

PATH_CASUAL = "casual_chat"
PATH_PERSONAL = "personal_context"
PATH_PLANNING = "planning"
PATH_CODING = "coding_task"
PATH_DEBUG = "debug_audit"
PATH_RESEARCH = "research"
PATH_META = "assistant_meta"
PATH_GENERAL = "general"


_WORD_RE = re.compile(r"[A-Za-z0-9_./:\\-]+")
_PATHY_RE = re.compile(r"[A-Za-z]:\\|/|\\\\|\\.(py|ts|js|go|rs|toml|json|md)\\b", re.I)
_STACK_RE = re.compile(r"\b(traceback|stack trace|exception|error:|failed|failure)\b", re.I)
_LIVENESS_RE = re.compile(
    r"\b(are you (there|working|alive)|you there|still there|ping|status check)\b",
    re.I,
)
_INTEGRATION_RE = re.compile(
    r"\b(telegram|discord|slack|whatsapp|botfather|webhook|oauth|integration|integrate|chat bot|bot)\b",
    re.I,
)
_SETUP_RE = re.compile(
    r"\b(set ?up|setup|configure|configuration|config|connect|wire up)\b",
    re.I,
)
_TROUBLESHOOT_RE = re.compile(
    r"\b("
    r"not working|"
    r"broken|"
    r"reset(?:s|ting)?|"
    r"settings?\s+(?:reset|saving|persist|stick)|"
    r"restart|"
    r"crash|"
    r"failing|"
    r"issue|"
    r"problem"
    r")\b",
    re.I,
)
_EXECUTION_PREFERENCE_RE = re.compile(
    r"\b(i want|don't want|do not want|want thomas to|want you to)\b.*\b(program|code|build|fix|implement)\b",
    re.I,
)
_BEHAVIOR_FEEDBACK_RE = re.compile(
    r"\b("
    r"how you talk|"
    r"how you speak|"
    r"person skills|"
    r"too robotic|"
    r"sound robotic|"
    r"assistant style|"
    r"conversation style|"
    r"talk better|"
    r"less robotic|"
    r"be more human"
    r")\b",
    re.I,
)
_FRUSTRATION_RE = re.compile(
    r"\b("
    r"frustrat(?:ed|ing)?|"
    r"annoy(?:ed|ing)?|"
    r"upset|"
    r"this sucks|"
    r"not working|"
    r"you keep|"
    r"you always|"
    r"why do you"
    r")\b",
    re.I,
)
_NO_EXECUTION_RE = re.compile(
    r"\b("
    r"no task|"
    r"did not give (you )?a task|"
    r"didn'?t give (you )?a task|"
    r"have not given (you )?a task|"
    r"haven'?t given (you )?a task|"
    r"we never (even )?started (a )?coding task|"
    r"not asking (you )?to code|"
    r"continue talking|"
    r"just talking|"
    r"just chat(?:ting)?|"
    r"conversation mode"
    r")\b",
    re.I,
)


@dataclass(frozen=True)
class RouteDecision:
    path: str
    confidence: float
    reasons: List[str]
    mode: str
    tools_policy: str
    include_purpose: bool
    memory_include_global: bool
    memory_include_profile: bool
    memory_budget_tokens: int

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _PathPolicy:
    mode: str
    tools_policy: str
    include_purpose: bool
    memory_include_global: bool
    memory_include_profile: bool
    memory_budget_tokens: int


_POLICY: Dict[str, _PathPolicy] = {
    PATH_CASUAL: _PathPolicy(
        mode="auto",
        tools_policy="never",
        include_purpose=False,
        memory_include_global=False,
        memory_include_profile=True,
        memory_budget_tokens=480,
    ),
    PATH_PERSONAL: _PathPolicy(
        mode="auto",
        tools_policy="never",
        include_purpose=False,
        memory_include_global=False,
        memory_include_profile=True,
        memory_budget_tokens=700,
    ),
    PATH_PLANNING: _PathPolicy(
        mode="auto",
        tools_policy="auto",
        include_purpose=False,
        memory_include_global=False,
        memory_include_profile=True,
        memory_budget_tokens=850,
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
        tools_policy="never",
        include_purpose=False,
        memory_include_global=False,
        memory_include_profile=True,
        memory_budget_tokens=550,
    ),
    PATH_GENERAL: _PathPolicy(
        mode="auto",
        tools_policy="auto",
        include_purpose=False,
        memory_include_global=False,
        memory_include_profile=True,
        memory_budget_tokens=760,
    ),
}


class IntentRouter:
    """Heuristic intent router for response policy selection."""

    def decide(
        self,
        text: str,
        *,
        requested_mode: str = "auto",
        requested_tools_policy: str = "auto",
    ) -> RouteDecision:
        src = str(text or "").strip()
        lower = src.lower()
        scores: Dict[str, float] = {k: 0.0 for k in _POLICY.keys()}
        reasons: Dict[str, List[str]] = {k: [] for k in _POLICY.keys()}

        def add(path: str, weight: float, reason: str) -> None:
            scores[path] += float(weight)
            if len(reasons[path]) < 6:
                reasons[path].append(reason)

        tokens = [t.lower() for t in _WORD_RE.findall(lower)]
        tok_set = set(tokens)

        if not src:
            add(PATH_CASUAL, 1.0, "empty_or_short")

        # Structural signals
        if _PATHY_RE.search(src):
            add(PATH_CODING, 2.5, "file_or_path_signal")
        if _STACK_RE.search(src):
            add(PATH_DEBUG, 3.2, "error_signal")
        if _LIVENESS_RE.search(src):
            add(PATH_CASUAL, 3.0, "liveness_check")
        if _INTEGRATION_RE.search(src):
            add(PATH_CODING, 2.6, "integration_signal")
        if _INTEGRATION_RE.search(src) and _SETUP_RE.search(src):
            add(PATH_CODING, 1.8, "integration_setup_signal")

        # Casual + personal
        if tok_set.intersection({"hi", "hello", "hey", "yo", "sup"}):
            add(PATH_CASUAL, 2.4, "greeting")
        if tok_set.intersection({"life", "family", "stress", "anxious", "relationship"}):
            add(PATH_PERSONAL, 2.2, "personal_topic")
        if "my " in lower or "i feel" in lower or "i am " in lower:
            add(PATH_PERSONAL, 1.0, "self_context")

        # Planning
        if tok_set.intersection({"plan", "roadmap", "strategy", "steps", "workflow", "flowchart"}):
            add(PATH_PLANNING, 2.8, "planning_keywords")
        if "how should" in lower or "what's the best way" in lower:
            add(PATH_PLANNING, 1.8, "decision_prompt")

        # Coding
        if tok_set.intersection(
            {"code", "coding", "program", "programming", "refactor", "function", "class", "api", "repo", "test"}
        ):
            add(PATH_CODING, 2.8, "coding_keywords")
        if tok_set.intersection({"build", "implement", "implemented", "implementation", "fix", "patch", "commit"}):
            add(PATH_CODING, 1.4, "implementation_intent")
        if _EXECUTION_PREFERENCE_RE.search(src):
            add(PATH_CODING, 2.4, "execution_preference")
        if _NO_EXECUTION_RE.search(src):
            add(PATH_CASUAL, 4.6, "no_execution_intent")
            add(PATH_META, 2.0, "no_execution_intent_meta")

        # Debug/security/audit
        if tok_set.intersection({"debug", "bug", "audit", "security", "vulnerability", "regression", "incident"}):
            add(PATH_DEBUG, 3.0, "debug_or_security_keywords")
        if tok_set.intersection({"token", "latency", "performance", "cost"}):
            add(PATH_DEBUG, 1.3, "optimization_signal")

        # Research
        if tok_set.intersection({"research", "compare", "latest", "news", "lookup", "find", "online"}):
            add(PATH_RESEARCH, 2.5, "research_keywords")
        if "look online" in lower or "search" in lower:
            add(PATH_RESEARCH, 1.9, "explicit_lookup")

        # Troubleshooting signals should bias toward debug/coding rather than research.
        if _TROUBLESHOOT_RE.search(src):
            add(PATH_DEBUG, 2.6, "troubleshoot_signal")
            add(PATH_CODING, 1.2, "troubleshoot_signal")

        # Assistant-meta
        if tok_set.intersection({"prompt", "instruction", "behavior", "why", "route", "memory"}):
            add(PATH_META, 1.6, "assistant_meta_keywords")
        if "how do you work" in lower or "what are you told" in lower:
            add(PATH_META, 3.0, "assistant_self_model")
        if _BEHAVIOR_FEEDBACK_RE.search(src):
            add(PATH_META, 3.2, "behavior_feedback")
            add(PATH_PERSONAL, 1.0, "behavior_feedback_tone")
            add(PATH_CASUAL, 0.8, "behavior_feedback_chat")
        if _FRUSTRATION_RE.search(src):
            add(PATH_PERSONAL, 1.6, "frustration_signal")
            add(PATH_META, 0.8, "frustration_meta")

        # Backstop
        add(PATH_GENERAL, 0.4, "general_backstop")

        chosen, confidence = self._choose(scores)
        rule = _POLICY.get(chosen, _POLICY[PATH_GENERAL])
        chosen_reasons = reasons.get(chosen, []) or ["fallback"]

        mode = rule.mode if str(requested_mode or "auto") == "auto" else str(requested_mode)
        tools_policy = (
            rule.tools_policy
            if str(requested_tools_policy or "auto") == "auto"
            else str(requested_tools_policy)
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
        )

    def _choose(self, scores: Dict[str, float]) -> Tuple[str, float]:
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if not ranked:
            return PATH_GENERAL, 0.25
        top_path, top_score = ranked[0]
        if top_score <= 0:
            return PATH_GENERAL, 0.25
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        conf = top_score / max(0.01, (top_score + second_score))
        conf = max(0.35, min(0.99, conf))
        return top_path, conf
