"""Type definitions and constants for preferences."""

from typing import Literal

Theme = Literal["auto", "light", "dark"]
BubbleStyle = Literal["rounded", "square", "compact"]
AutonomyLevel = Literal["L1", "L2", "L3", "L4"]
ReasoningEffort = Literal["low", "medium", "high", "max", "xhigh"]
RunMode = Literal["auto", "fast", "thinking"]
TokenEconomyLevel = Literal["cheap", "optimal", "max"]
ContradictionPolicy = Literal["latest_wins", "ask", "strict"]
ContextPruneStrategy = Literal["recency", "balanced", "aggressive"]
UIDensity = Literal["comfortable", "compact", "dense"]
EventLogVerbosity = Literal["minimal", "standard", "verbose"]
ProfileType = Literal["adaptive", "coder", "non_coder"]
ReviewDepth = Literal["adaptive", "simple", "technical"]
WorkflowMode = Literal["guided", "expert"]
DesktopTrustMode = Literal["ask_every_time", "remembered", "always_allow"]

PROVIDERS = ("openai", "anthropic", "google", "elevenlabs", "azure_openai", "custom")

_PROFILE_TYPE_ALIASES = {
    "": "adaptive",
    "auto": "adaptive",
    "automatic": "adaptive",
    "adaptive": "adaptive",
    "default": "adaptive",
    "balanced": "adaptive",
    "general": "adaptive",
    "non_coder": "non_coder",
    "non-coder": "non_coder",
    "noncoder": "non_coder",
    "non technical": "non_coder",
    "non_technical": "non_coder",
    "beginner": "non_coder",
    "new": "non_coder",
    "coder": "coder",
    "developer": "coder",
    "technical": "coder",
    "expert": "coder",
}

_REVIEW_DEPTH_ALIASES = {
    "": "adaptive",
    "adaptive": "adaptive",
    "auto": "adaptive",
    "default": "adaptive",
    "balanced": "adaptive",
    "simple": "simple",
    "simplified": "simple",
    "plain": "simple",
    "non_technical": "simple",
    "non-technical": "simple",
    "non technical": "simple",
    "easy": "simple",
    "technical": "technical",
    "detailed": "technical",
    "deep": "technical",
}

_NON_CODER_RUNTIME_LOCKS: dict[str, bool] = {
    "quality_enforce": True,
    "quality_require_verification_for_coding": True,
    "quality_require_tests_for_code_edits": True,
    "quality_require_monolith_guard_for_coding": True,
}
