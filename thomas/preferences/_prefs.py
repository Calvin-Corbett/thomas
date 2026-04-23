"""Pydantic models for preferences (request/response)."""

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ._types import (
    AnimationFidelity,
    AutonomyLevel,
    BubbleStyle,
    ContextPruneStrategy,
    ContradictionPolicy,
    DesktopTrustMode,
    EventLogVerbosity,
    GuardrailsPosture,
    ProfileType,
    ReasoningEffort,
    ReviewDepth,
    RunMode,
    Theme,
    TokenEconomyLevel,
    UIDensity,
    WorkflowMode,
)
from ._utils import (
    normalize_profile_type,
    normalize_review_depth,
    utc_now_iso,
)
from .guardrails_policy import normalize_guardrails_posture

# ── Response Models ──────────────────────────────────────────────────────────


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
    isolated_desktop_enabled: bool = False
    isolated_desktop_installation_state: str = "not_enabled"
    isolated_desktop_next_action: str = ""
    isolated_desktop_reboot_required: bool = False
    isolated_desktop_relogin_required: bool = False

    @field_validator("current_step", "isolated_desktop_next_action")
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

    @field_validator("isolated_desktop_installation_state", mode="before")
    @classmethod
    def _normalize_installation_state(cls, v: Any) -> str:
        raw = str(v or "").strip().lower().replace("-", "_").replace(" ", "_")
        allowed = {
            "not_enabled",
            "opt_in_requested",
            "host_service_not_installed",
            "host_service_installing",
            "host_service_ready",
            "relogin_required",
            "reboot_required",
            "local_vm_ready",
            "remote_fallback_available",
            "degraded",
            "unavailable",
        }
        return raw if raw in allowed else "not_enabled"


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
    isolated_desktop_enabled: bool = False
    isolated_desktop_trust_mode: DesktopTrustMode = "ask_every_time"
    isolated_desktop_hidden_by_default: bool = True

    @field_validator("isolated_desktop_trust_mode", mode="before")
    @classmethod
    def _normalize_isolated_desktop_trust_mode(cls, v: Any) -> str:
        raw = str(v or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "": "ask_every_time",
            "ask": "ask_every_time",
            "ask_every_time": "ask_every_time",
            "prompt": "ask_every_time",
            "remember": "remembered",
            "remembered": "remembered",
            "always": "always_allow",
            "always_allow": "always_allow",
        }
        value = aliases.get(raw, raw)
        return value if value in {"ask_every_time", "remembered", "always_allow"} else "ask_every_time"


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


class AdvancedSecurityPrefs(BaseModel):
    allow_third_party_agent_access: bool = True
    guardrails_posture: GuardrailsPosture = "standard"
    guardrails_posture_changed_at: str | None = None
    guardrails_posture_changed_by: str | None = None
    human_breakglass_enabled: bool = False
    human_breakglass_changed_at: str | None = None
    human_breakglass_changed_by: str | None = None
    enforcement_mode: str = "protected"
    last_changed_at: str | None = None
    last_changed_by: str | None = None

    @field_validator("guardrails_posture", mode="before")
    @classmethod
    def _normalize_guardrails_posture(cls, v: Any) -> str:
        return normalize_guardrails_posture(v)


class AdvancedInterfacePrefs(BaseModel):
    ui_density: UIDensity = "comfortable"
    show_timestamps: bool = False
    show_token_meter: bool = False
    animation_fidelity: AnimationFidelity = "high"
    animations_enabled: bool = True
    advanced_chat_physics: bool = False
    code_theme: str = "atom-one-dark"
    debug_panel_enabled: bool = False
    event_log_verbosity: EventLogVerbosity = "standard"
    workflow_mode: WorkflowMode = "guided"
    labs_flags: str = ""

    @field_validator("animation_fidelity", mode="before")
    @classmethod
    def _normalize_animation_fidelity(cls, v: Any) -> str:
        raw = str(v or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "": "high",
            "high": "high",
            "high_fidelity": "high",
            "full": "high",
            "balanced": "balanced",
            "medium": "balanced",
            "default": "balanced",
            "minimal": "minimal",
            "minimal_motion": "minimal",
            "reduced": "minimal",
            "off": "minimal",
        }
        return aliases.get(raw, "high")

    @model_validator(mode="after")
    def _sync_animation_flags(self):
        self.animations_enabled = self.animation_fidelity != "minimal"
        return self

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
    security: AdvancedSecurityPrefs = Field(default_factory=AdvancedSecurityPrefs)
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
