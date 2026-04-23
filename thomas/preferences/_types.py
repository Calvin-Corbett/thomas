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
AnimationFidelity = Literal["high", "balanced", "minimal"]
EventLogVerbosity = Literal["minimal", "standard", "verbose"]
ProfileType = Literal["adaptive", "coder", "non_coder"]
ReviewDepth = Literal["adaptive", "simple", "technical"]
WorkflowMode = Literal["guided", "expert"]
DesktopTrustMode = Literal["ask_every_time", "remembered", "always_allow"]
GuardrailsPosture = Literal["locked", "standard", "builder"]

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

_GUARDRAIL_TOOL_ALLOW_FIELDS = (
    "allow_shell",
    "allow_file_write",
    "allow_network",
    "allow_browser",
    "allow_channels",
    "allow_git",
)

_GUARDRAIL_TOOL_MIN_FIELDS = ("require_command_approval",)

_GUARDRAIL_RUNTIME_MIN_FIELDS = (
    "quality_enforce",
    "quality_require_verification_for_coding",
    "quality_require_tests_for_code_edits",
    "quality_require_monolith_guard_for_coding",
)

_GUARDRAIL_POSTURE_ORDER: dict[str, int] = {
    "builder": 0,
    "standard": 1,
    "locked": 2,
}

_GUARDRAIL_TOOL_MAXIMA: dict[str, dict[str, bool]] = {
    "builder": {field: True for field in _GUARDRAIL_TOOL_ALLOW_FIELDS},
    "standard": {field: True for field in _GUARDRAIL_TOOL_ALLOW_FIELDS},
    "locked": {field: False for field in _GUARDRAIL_TOOL_ALLOW_FIELDS},
}

_GUARDRAIL_TOOL_MINIMA: dict[str, dict[str, bool]] = {
    "builder": {"require_command_approval": False},
    "standard": {"require_command_approval": True},
    "locked": {"require_command_approval": True},
}

_GUARDRAIL_RUNTIME_MINIMA: dict[str, dict[str, bool]] = {
    "builder": {
        "quality_enforce": False,
        "quality_require_verification_for_coding": False,
        "quality_require_tests_for_code_edits": False,
        "quality_require_monolith_guard_for_coding": False,
    },
    "standard": {
        "quality_enforce": True,
        "quality_require_verification_for_coding": True,
        "quality_require_tests_for_code_edits": False,
        "quality_require_monolith_guard_for_coding": True,
    },
    "locked": {
        "quality_enforce": True,
        "quality_require_verification_for_coding": True,
        "quality_require_tests_for_code_edits": True,
        "quality_require_monolith_guard_for_coding": True,
    },
}
