"""Model-owned routing compatibility types for the agent loop.

Thomas does not infer a semantic route from prompt words.  The frontier model
receives the conversation and available capabilities, then chooses whether to
answer or call a tool.  ``IntentRouter`` remains as a small compatibility
adapter for callers that expect ``RouteDecision`` metadata; it only preserves
explicit structured controls supplied by the caller.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

PATH_CASUAL = "casual_chat"
PATH_PERSONAL = "personal_context"
PATH_PLANNING = "planning"
PATH_CODING = "coding_task"
PATH_DEBUG = "debug_audit"
PATH_RESEARCH = "research"
PATH_META = "assistant_meta"
PATH_GENERAL = "general"
PATH_MODEL_OWNED = "model_owned"


@dataclass(frozen=True)
class RouteDecision:
    """Execution metadata that does not classify the user's prose."""

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


class IntentRouter:
    """Preserve explicit controls without making semantic intent decisions."""

    def decide(
        self,
        text: str,
        *,
        requested_mode: str = "auto",
        requested_tools_policy: str = "auto",
        is_followup: bool = False,
        prior_route: str | None = None,
    ) -> RouteDecision:
        """Return one neutral execution policy for every natural-language turn.

        ``text`` and ``prior_route`` are accepted for API compatibility only.
        They never affect the decision.  An externally supplied follow-up flag
        is retained as metadata, but Thomas does not derive one from prose.
        """
        del text, prior_route
        mode = str(requested_mode or "auto").strip() or "auto"
        tools_policy = str(requested_tools_policy or "auto").strip() or "auto"
        if tools_policy not in {"never", "auto", "always"}:
            tools_policy = "auto"

        return RouteDecision(
            path=PATH_MODEL_OWNED,
            confidence=1.0,
            reasons=["model_owned"],
            mode=mode,
            tools_policy=tools_policy,
            include_purpose=False,
            memory_include_global=True,
            memory_include_profile=True,
            memory_budget_tokens=1000,
            is_followup=bool(is_followup),
        )
