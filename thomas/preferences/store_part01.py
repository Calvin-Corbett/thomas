"""
Thomas - User Preferences Store (SQLite)

Goals
- Durable preferences persisted in SQLite.
- Safe partial updates (PATCH semantics).
- Provider API keys encrypted at rest, with non-sensitive masking available without decrypting.

DB path resolution (in order):
- THOMAS_DB_PATH (preferred)
- THOMAS_SQLITE_PATH (legacy)
- THOMAS_DATA_DIR[/<profile>]/thomas.db (fallback)

Key encryption
- Prefer THOMAS_PREFERENCES_FERNET_KEY (Fernet key, urlsafe base64 32-byte key)
- Else derive from THOMAS_SECRET_KEY (SHA-256 -> Fernet key)
- Else generate a Fernet key and persist it in preferences_meta (local-only fallback).

Security note: If you let the store generate/persist an encryption key in the DB, keys are
obfuscated at-rest but not strongly protected against someone who can read the DB. For
real protection, set THOMAS_PREFERENCES_FERNET_KEY or THOMAS_SECRET_KEY.

Thread-scoped memory override
- Global memory setting in preferences JSON.
- Per-thread override stored in thread_preferences keyed by (user_id, thread_id).
- GET /api/preferences supports ?thread_id=... to compute effective thread memory status.
- PATCH /api/preferences supports memory.thread_enabled when thread_id is provided.
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

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


def normalize_profile_type(value: Any, *, default: ProfileType = "adaptive") -> ProfileType:
    raw = str(value or "").strip().lower().replace("-", "_")
    if not raw:
        return default
    normalized = _PROFILE_TYPE_ALIASES.get(raw)
    if normalized:
        return normalized  # type: ignore[return-value]
    # Handle mixed separators like "non coder".
    normalized = _PROFILE_TYPE_ALIASES.get(raw.replace("_", " "))
    if normalized:
        return normalized  # type: ignore[return-value]
    return default


def normalize_review_depth(value: Any, *, default: ReviewDepth = "adaptive") -> ReviewDepth:
    raw = str(value or "").strip().lower().replace("-", "_")
    if not raw:
        return default
    normalized = _REVIEW_DEPTH_ALIASES.get(raw)
    if normalized:
        return normalized  # type: ignore[return-value]
    normalized = _REVIEW_DEPTH_ALIASES.get(raw.replace("_", " "))
    if normalized:
        return normalized  # type: ignore[return-value]
    return default


def profile_prefers_non_coder_mode(
    profile: Any = None,
    *,
    onboarding_answers: dict[str, Any] | None = None,
) -> bool:
    """Resolve whether robust non-coder defaults should be active."""
    explicit = normalize_profile_type(getattr(profile, "profile_type", None), default="adaptive")
    if explicit == "non_coder":
        return True
    if explicit == "coder":
        return False

    answers = onboarding_answers if isinstance(onboarding_answers, dict) else {}
    answers_profile = normalize_profile_type(answers.get("profile_type"), default="adaptive")
    if answers_profile == "non_coder":
        return True
    if answers_profile == "coder":
        return False

    experience = str(answers.get("experience") or "").strip().lower()
    if experience in {"new", "beginner", "non_coder", "non-coder", "noncoder"}:
        return True
    return False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db_path() -> str:
    env_path = os.getenv("THOMAS_DB_PATH") or os.getenv("THOMAS_SQLITE_PATH")
    if env_path:
        return env_path
    try:
        from thomas.core.config import resolve_thomas_data_dir

        return str((resolve_thomas_data_dir() / "thomas.db").resolve())
    except Exception:
        return str((Path.home() / ".thomas" / "thomas.db").resolve())


def _derive_fernet_key_from_secret(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _mask_key_tail(value: str) -> str:
    v = value.strip()
    if not v:
        return ""
    tail = v[-4:] if len(v) >= 4 else v
    return f"••••••{tail}"


class AppearancePrefs(BaseModel):
    theme: Theme = "auto"
    font_size: int = Field(default=16, ge=12, le=28)
    bubble_style: BubbleStyle = "rounded"

    @field_validator("font_size")
    @classmethod
    def _font_size_reasonable(cls, v: int) -> int:
        return max(12, min(28, int(v)))


class VoicePrefs(BaseModel):
    tts_voice: str = "default"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    wake_word_enabled: bool = False
    mic_device_id: str = ""


class MemoryPrefs(BaseModel):
    enabled_global: bool = True
    thread_enabled: bool | None = None  # computed only when thread_id is provided


class NotificationPrefs(BaseModel):
    web_push: bool = False
    telegram: bool = False
    desktop: bool = True


class AutonomyPrefs(BaseModel):
    default_level: AutonomyLevel = "L1"
    concurrency_limit: int = Field(default=2, ge=1, le=64)


class OnboardingPrefs(BaseModel):
    setup_completed: bool = False
    version: int = Field(default=0, ge=0, le=1000)
    completed_at: str | None = None
    dismissed_at: str | None = None
    current_step: str = ""
    connection_method: str | None = None
    dependency_plan: dict[str, Any] = Field(default_factory=dict)
    answers: dict[str, Any] = Field(default_factory=dict)

    @field_validator("current_step")
    @classmethod
    def _trim_current_step(cls, v: str) -> str:
        return str(v or "").strip()

    @field_validator("connection_method")
    @classmethod
    def _trim_connection_method(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None


class APIKeysMasked(BaseModel):
    openai: str | None = None
    anthropic: str | None = None
    google: str | None = None
    elevenlabs: str | None = None
    azure_openai: str | None = None
    custom: str | None = None


class ProfilePrefs(BaseModel):
    display_name: str = ""
    avatar_url: str = ""
    profile_type: ProfileType = "adaptive"
    review_depth: ReviewDepth = "adaptive"

    @field_validator("display_name", "avatar_url")
    @classmethod
    def _trim_fields(cls, v: str) -> str:
        return str(v or "").strip()

    @field_validator("profile_type", mode="before")
    @classmethod
    def _normalize_profile_type(cls, v: Any) -> str:
        return normalize_profile_type(v)

    @field_validator("review_depth", mode="before")
    @classmethod
    def _normalize_review_depth(cls, v: Any) -> str:
        return normalize_review_depth(v)


class AdvancedModelPrefs(BaseModel):
    active_profile: str = ""  # persisted selected provider/profile
    model_id: str = ""  # persisted model override
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    max_output_tokens: int = Field(default=4096, ge=128, le=32768)
    reasoning_effort: ReasoningEffort = "medium"
    reasoning_token_budget: int = Field(default=4096, ge=128, le=65536)
    json_mode: bool = False
    deterministic_seed: int | None = Field(default=None, ge=0, le=2147483647)
    stop_sequences: str = ""

    @field_validator("stop_sequences")
    @classmethod
    def _trim_stop_sequences(cls, v: str) -> str:
        return str(v or "").strip()


class AdvancedToolsPrefs(BaseModel):
    auto_tool_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    require_command_approval: bool = False
    allow_shell: bool = True
    allow_file_write: bool = True
    allow_network: bool = True
    allow_browser: bool = True
    allow_channels: bool = True
    allow_git: bool = True
    tool_timeout_s: int = Field(default=120, ge=5, le=1800)
    max_parallel_tools: int = Field(default=6, ge=1, le=32)
    allowed_paths: str = ""
    blocked_commands: str = ""

    @field_validator("allowed_paths", "blocked_commands")
    @classmethod
    def _trim_fields(cls, v: str) -> str:
        return str(v or "").strip()


class AdvancedMemoryPrefs(BaseModel):
    include_global_memory: bool = True
    include_profile_memory: bool = True
    include_thread_memory: bool = True
    pins_only: bool = False
    max_pack_tokens: int = Field(default=1200, ge=200, le=64000)
    decay_half_life_hours: float = Field(default=240.0, ge=1.0, le=87600.0)
    retrieval_top_k: int = Field(default=8, ge=1, le=64)
    auto_summarize_threshold: int = Field(default=80, ge=10, le=2000)
    memory_decay_days: int = Field(default=90, ge=1, le=3650)
    auto_compact_enabled: bool = True
    auto_compact_episode_threshold: int = Field(default=2000, ge=10, le=1000000)
    auto_compact_min_interval_hours: float = Field(default=24.0, ge=0.1, le=8760.0)
    auto_optimize_enabled: bool = True
    auto_optimize_waste_threshold: float = Field(default=0.22, ge=0.0, le=1.0)
    auto_optimize_min_interval_hours: float = Field(default=12.0, ge=0.1, le=8760.0)
    contradiction_policy: ContradictionPolicy = "ask"
    context_prune_strategy: ContextPruneStrategy = "balanced"
    pinned_context: str = ""

    @field_validator("pinned_context")
    @classmethod
    def _trim_fields(cls, v: str) -> str:
        return str(v or "").strip()


class AdvancedCostPrefs(BaseModel):
    session_token_budget: int = Field(default=200000, ge=1000, le=5000000)
    daily_token_budget: int = Field(default=2000000, ge=10000, le=50000000)
    throttle_on_budget: bool = True
    low_cost_mode: bool = False
    max_retries: int = Field(default=2, ge=0, le=20)
    retry_backoff_ms: int = Field(default=800, ge=0, le=120000)
    provider_failover_chain: str = ""
    model_failover_chain: str = ""

    @field_validator("provider_failover_chain", "model_failover_chain")
    @classmethod
    def _trim_fields(cls, v: str) -> str:
        return str(v or "").strip()


class AdvancedRuntimePrefs(BaseModel):
    default_mode: RunMode = "auto"
    default_token_economy: TokenEconomyLevel = "optimal"
    max_agent_iterations: int = Field(default=0, ge=0, le=200)
    local_background_agents_enabled: bool = False
    local_background_min_gpu_headroom_pct: int = Field(default=35, ge=5, le=95)
    quality_enforce: bool = True
    quality_require_verification_for_coding: bool = True
    quality_require_tests_for_code_edits: bool = False
    quality_require_monolith_guard_for_coding: bool = True


class AdvancedFailoverPrefs(BaseModel):
    enabled: bool = True
    chat_auto_failover: bool = False
    fallback_on_auth_error: bool = False
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)


class AdvancedPrivacyPrefs(BaseModel):
    telemetry_enabled: bool = False
    redact_secrets_in_logs: bool = True
    pii_guard_strict: bool = False
    local_only_mode: bool = False
    audit_log_enabled: bool = True
    retention_days: int = Field(default=90, ge=1, le=3650)
    export_on_exit: bool = False


class AdvancedInterfacePrefs(BaseModel):
    ui_density: UIDensity = "comfortable"
    show_timestamps: bool = False
    show_token_meter: bool = False
    animations_enabled: bool = True
    code_theme: str = "atom-one-dark"
    debug_panel_enabled: bool = False
    event_log_verbosity: EventLogVerbosity = "standard"
    workflow_mode: WorkflowMode = "guided"
    labs_flags: str = ""

    @field_validator("workflow_mode", mode="before")
    @classmethod
    def _normalize_workflow_mode(cls, v: Any) -> str:
        if v is None:
            return "guided"
        mode_str = str(v or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "": "guided",
            "guided": "guided",
            "default": "guided",
            "safe": "guided",
            "expert": "expert",
            "expert_bypass": "expert",
            "expert_mode": "expert",
            "bypass": "expert",
        }
        return aliases.get(mode_str, "guided")

    @field_validator("code_theme", "labs_flags")
    @classmethod
    def _trim_fields(cls, v: str) -> str:
        return str(v or "").strip()


class AdvancedPrefs(BaseModel):
    model: AdvancedModelPrefs = Field(default_factory=AdvancedModelPrefs)
    tools: AdvancedToolsPrefs = Field(default_factory=AdvancedToolsPrefs)
    memory: AdvancedMemoryPrefs = Field(default_factory=AdvancedMemoryPrefs)
    cost: AdvancedCostPrefs = Field(default_factory=AdvancedCostPrefs)
    runtime: AdvancedRuntimePrefs = Field(default_factory=AdvancedRuntimePrefs)
    failover: AdvancedFailoverPrefs = Field(default_factory=AdvancedFailoverPrefs)
    privacy: AdvancedPrivacyPrefs = Field(default_factory=AdvancedPrivacyPrefs)
    interface: AdvancedInterfacePrefs = Field(default_factory=AdvancedInterfacePrefs)


class PreferencesResponse(BaseModel):
    appearance: AppearancePrefs = Field(default_factory=AppearancePrefs)
    voice: VoicePrefs = Field(default_factory=VoicePrefs)
    memory: MemoryPrefs = Field(default_factory=MemoryPrefs)
    notifications: NotificationPrefs = Field(default_factory=NotificationPrefs)
    autonomy: AutonomyPrefs = Field(default_factory=AutonomyPrefs)
    advanced: AdvancedPrefs = Field(default_factory=AdvancedPrefs)
    onboarding: OnboardingPrefs = Field(default_factory=OnboardingPrefs)
    api_keys: APIKeysMasked = Field(default_factory=APIKeysMasked)
    profile: ProfilePrefs = Field(default_factory=ProfilePrefs)
    thomads: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=utc_now_iso)


class AppearancePatch(BaseModel):
    theme: Theme | None = None
    font_size: int | None = Field(default=None, ge=12, le=28)
    bubble_style: BubbleStyle | None = None

    @field_validator("theme", mode="before")
    @classmethod
    def _normalize_theme(cls, v: Any) -> str | None:
        if v is None:
            return None
        theme_str = str(v or "").strip().lower()
        if not theme_str:
            return None
        # Valid themes: "auto", "light", "dark"
        valid_themes = {"auto", "light", "dark"}
        if theme_str in valid_themes:
            return theme_str
        # Normalize common aliases
        aliases = {
            "auto": "auto",
            "automatic": "auto",
            "default": "auto",
            "system": "auto",
            "light": "light",
            "day": "light",
            "bright": "light",
            "dark": "dark",
            "night": "dark",
            "black": "dark",
        }
        return aliases.get(theme_str, "auto")

    @field_validator("bubble_style", mode="before")
    @classmethod
    def _normalize_bubble_style(cls, v: Any) -> str | None:
        if v is None:
            return None
        style_str = str(v or "").strip().lower()
        if not style_str:
            return None
        # Valid styles: "rounded", "square", "compact"
        valid_styles = {"rounded", "square", "compact"}
        if style_str in valid_styles:
            return style_str
        # Normalize common aliases
        aliases = {
            "rounded": "rounded",
            "smooth": "rounded",
            "circle": "rounded",
            "square": "square",
            "sharp": "square",
            "hard": "square",
            "compact": "compact",
            "tight": "compact",
            "minimal": "compact",
        }
        return aliases.get(style_str, "rounded")


class VoicePatch(BaseModel):
    tts_voice: str | None = None
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    wake_word_enabled: bool | None = None
    mic_device_id: str | None = None


class MemoryPatch(BaseModel):
    enabled_global: bool | None = None
    # If explicitly provided (even null), requires thread_id query param.
    # True/False sets override; null clears override.
    thread_enabled: bool | None = None


class NotificationPatch(BaseModel):
    web_push: bool | None = None
    telegram: bool | None = None
    desktop: bool | None = None


class AutonomyPatch(BaseModel):
    default_level: AutonomyLevel | None = None
    concurrency_limit: int | None = Field(default=None, ge=1, le=64)

    @field_validator("default_level", mode="before")
    @classmethod
    def _normalize_autonomy_level(cls, v: Any) -> str | None:
        if v is None:
            return None
        level_str = str(v or "").strip().upper()
        if not level_str:
            return None
        # Valid levels: "L1", "L2", "L3", "L4"
        valid_levels = {"L1", "L2", "L3", "L4"}
        if level_str in valid_levels:
            return level_str
        # Try to parse numeric versions
        if level_str.startswith("L"):
            level_num = level_str[1:]
        else:
            level_num = level_str
        try:
            num = int(level_num)
            num = max(1, min(4, num))  # clamp to 1-4
            return f"L{num}"
        except (ValueError, TypeError):
            # Default to L1 (chat-only)
            return "L1"


class OnboardingPatch(BaseModel):
    setup_completed: bool | None = None
    version: int | None = Field(default=None, ge=0, le=1000)
    completed_at: str | None = None
    dismissed_at: str | None = None
    current_step: str | None = None
    connection_method: str | None = None
    dependency_plan: dict[str, Any] | None = None
    answers: dict[str, Any] | None = None


class APIKeysPatch(BaseModel):
    # Provide full keys here (encrypted at rest).
    # Empty string "" or null deletes the key.
    openai: str | None = None
    anthropic: str | None = None
    google: str | None = None
    elevenlabs: str | None = None
    azure_openai: str | None = None
    custom: str | None = None


class ProfilePatch(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None
    profile_type: str | None = None
    review_depth: str | None = None


class AdvancedModelPatch(BaseModel):
    active_profile: str | None = None
    model_id: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, ge=128, le=32768)
    reasoning_effort: ReasoningEffort | None = None
    reasoning_token_budget: int | None = Field(default=None, ge=128, le=65536)
    json_mode: bool | None = None
    deterministic_seed: int | None = Field(default=None, ge=0, le=2147483647)
    stop_sequences: str | None = None


class AdvancedToolsPatch(BaseModel):
    auto_tool_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    require_command_approval: bool | None = None
    allow_shell: bool | None = None
    allow_file_write: bool | None = None
    allow_network: bool | None = None
    allow_browser: bool | None = None
    allow_channels: bool | None = None
    allow_git: bool | None = None
    tool_timeout_s: int | None = Field(default=None, ge=5, le=1800)
    max_parallel_tools: int | None = Field(default=None, ge=1, le=32)
    allowed_paths: str | None = None
    blocked_commands: str | None = None


class AdvancedMemoryPatch(BaseModel):
    include_global_memory: bool | None = None
    include_profile_memory: bool | None = None
    include_thread_memory: bool | None = None
    pins_only: bool | None = None
    max_pack_tokens: int | None = Field(default=None, ge=200, le=64000)
    decay_half_life_hours: float | None = Field(default=None, ge=1.0, le=87600.0)
    retrieval_top_k: int | None = Field(default=None, ge=1, le=64)
    auto_summarize_threshold: int | None = Field(default=None, ge=10, le=2000)
    memory_decay_days: int | None = Field(default=None, ge=1, le=3650)
    auto_compact_enabled: bool | None = None
    auto_compact_episode_threshold: int | None = Field(default=None, ge=10, le=1000000)
    auto_compact_min_interval_hours: float | None = Field(default=None, ge=0.1, le=8760.0)
    auto_optimize_enabled: bool | None = None
    auto_optimize_waste_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    auto_optimize_min_interval_hours: float | None = Field(default=None, ge=0.1, le=8760.0)
    contradiction_policy: ContradictionPolicy | None = None
    context_prune_strategy: ContextPruneStrategy | None = None
    pinned_context: str | None = None


class AdvancedCostPatch(BaseModel):
    session_token_budget: int | None = Field(default=None, ge=1000, le=5000000)
    daily_token_budget: int | None = Field(default=None, ge=10000, le=50000000)
    throttle_on_budget: bool | None = None
    low_cost_mode: bool | None = None
    max_retries: int | None = Field(default=None, ge=0, le=20)
    retry_backoff_ms: int | None = Field(default=None, ge=0, le=120000)
    provider_failover_chain: str | None = None
    model_failover_chain: str | None = None


class AdvancedRuntimePatch(BaseModel):
    default_mode: RunMode | None = None
    default_token_economy: TokenEconomyLevel | None = None
    max_agent_iterations: int | None = Field(default=None, ge=0, le=200)
    local_background_agents_enabled: bool | None = None
    local_background_min_gpu_headroom_pct: int | None = Field(default=None, ge=5, le=95)
    quality_enforce: bool | None = None
    quality_require_verification_for_coding: bool | None = None
    quality_require_tests_for_code_edits: bool | None = None
    quality_require_monolith_guard_for_coding: bool | None = None

    @field_validator("default_mode", mode="before")
    @classmethod
    def _normalize_default_mode(cls, v: Any) -> str | None:
        if v is None:
            return None
        mode_str = str(v or "").strip().lower()
        if not mode_str:
            return None
        # Valid modes: "auto", "fast", "thinking"
        valid_modes = {"auto", "fast", "thinking"}
        if mode_str in valid_modes:
            return mode_str
        # Normalize common aliases
        aliases = {
            "auto": "auto",
            "automatic": "auto",
            "fast": "fast",
            "quick": "fast",
            "thinking": "thinking",
            "reason": "thinking",
        }
        return aliases.get(mode_str, "auto")

    @field_validator("default_token_economy", mode="before")
    @classmethod
    def _normalize_token_economy(cls, v: Any) -> str | None:
        if v is None:
            return None
        econ_str = str(v or "").strip().lower()
        if not econ_str:
            return None
        # Valid economies: "cheap", "optimal", "max"
        valid_economies = {"cheap", "optimal", "max"}
        if econ_str in valid_economies:
            return econ_str
        # Normalize common aliases
        aliases = {
            "cheap": "cheap",
            "low": "cheap",
            "low_cost": "cheap",
            "budget": "cheap",
            "economy": "cheap",
            "optimal": "optimal",
            "balanced": "optimal",
            "default": "optimal",
            "normal": "optimal",
            "max": "max",
            "maximum": "max",
            "high": "max",
            "best": "max",
            "quality": "max",
        }
        return aliases.get(econ_str, "optimal")


class AdvancedFailoverPatch(BaseModel):
    enabled: bool | None = None
    chat_auto_failover: bool | None = None
    fallback_on_auth_error: bool | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)


class AdvancedPrivacyPatch(BaseModel):
    telemetry_enabled: bool | None = None
    redact_secrets_in_logs: bool | None = None
    pii_guard_strict: bool | None = None
    local_only_mode: bool | None = None
    audit_log_enabled: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    export_on_exit: bool | None = None


class AdvancedInterfacePatch(BaseModel):
    ui_density: UIDensity | None = None
    show_timestamps: bool | None = None
    show_token_meter: bool | None = None
    animations_enabled: bool | None = None
    code_theme: str | None = None
    debug_panel_enabled: bool | None = None
    event_log_verbosity: EventLogVerbosity | None = None
    workflow_mode: WorkflowMode | None = None
    labs_flags: str | None = None

    @field_validator("ui_density", mode="before")
    @classmethod
    def _normalize_ui_density(cls, v: Any) -> str | None:
        if v is None:
            return None
        density_str = str(v or "").strip().lower()
        if not density_str:
            return None
        # Valid densities: "comfortable", "compact", "dense"
        valid_densities = {"comfortable", "compact", "dense"}
        if density_str in valid_densities:
            return density_str
        # Normalize common aliases
        aliases = {
            "comfortable": "comfortable",
            "default": "comfortable",
            "normal": "comfortable",
            "normal_spacing": "comfortable",
            "compact": "compact",
            "tight": "compact",
            "condensed": "compact",
            "dense": "dense",
            "max": "dense",
            "maximum": "dense",
        }
        return aliases.get(density_str, "comfortable")

    @field_validator("event_log_verbosity", mode="before")
    @classmethod
    def _normalize_event_log_verbosity(cls, v: Any) -> str | None:
        if v is None:
            return None
        verbosity_str = str(v or "").strip().lower()
        if not verbosity_str:
            return None
        # Valid verbosities: "minimal", "standard", "verbose"
        valid_verbosities = {"minimal", "standard", "verbose"}
        if verbosity_str in valid_verbosities:
            return verbosity_str
        # Normalize common aliases
        aliases = {
            "minimal": "minimal",
            "quiet": "minimal",
            "silent": "minimal",
            "none": "minimal",
            "standard": "standard",
            "default": "standard",
            "normal": "standard",
            "verbose": "verbose",
            "debug": "verbose",
            "detailed": "verbose",
            "full": "verbose",
        }
        return aliases.get(verbosity_str, "standard")


class AdvancedPatch(BaseModel):
    model: AdvancedModelPatch | None = None
    tools: AdvancedToolsPatch | None = None
    memory: AdvancedMemoryPatch | None = None
    cost: AdvancedCostPatch | None = None
    runtime: AdvancedRuntimePatch | None = None
    failover: AdvancedFailoverPatch | None = None
    privacy: AdvancedPrivacyPatch | None = None
    interface: AdvancedInterfacePatch | None = None


class PreferencesPatch(BaseModel):
    appearance: AppearancePatch | None = None
    voice: VoicePatch | None = None
    memory: MemoryPatch | None = None
    notifications: NotificationPatch | None = None
    autonomy: AutonomyPatch | None = None
    advanced: AdvancedPatch | None = None
    onboarding: OnboardingPatch | None = None
    api_keys: APIKeysPatch | None = None
    profile: ProfilePatch | None = None
    thomads: dict[str, Any] | None = None
