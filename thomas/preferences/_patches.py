"""Pydantic patch models for preferences updates."""

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
    ReasoningEffort,
    RunMode,
    Theme,
    TokenEconomyLevel,
    UIDensity,
    WorkflowMode,
)


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
    isolated_desktop_enabled: bool | None = None
    isolated_desktop_installation_state: str | None = None
    isolated_desktop_next_action: str | None = None
    isolated_desktop_reboot_required: bool | None = None
    isolated_desktop_relogin_required: bool | None = None


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
    role_profiles: dict[str, str | None] | None = None
    role_model_ids: dict[str, str | None] | None = None
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

    @field_validator("role_profiles", "role_model_ids", mode="before")
    @classmethod
    def _normalize_role_map(cls, v: Any) -> dict[str, str | None] | None:
        if v is None:
            return None
        if not isinstance(v, dict):
            return None
        normalized: dict[str, str | None] = {}
        for key, value in v.items():
            role = str(key or "").strip().lower().replace("-", "_").replace(" ", "_")
            if not role:
                continue
            if value is None:
                normalized[role] = None
                continue
            text = str(value or "").strip()
            normalized[role] = text if text else None
        return normalized


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
    isolated_desktop_enabled: bool | None = None
    isolated_desktop_trust_mode: DesktopTrustMode | None = None
    isolated_desktop_hidden_by_default: bool | None = None

    @field_validator("isolated_desktop_trust_mode", mode="before")
    @classmethod
    def _normalize_isolated_desktop_trust_mode(cls, v: Any) -> str | None:
        if v is None:
            return None
        raw = str(v or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "": None,
            "ask": "ask_every_time",
            "ask_every_time": "ask_every_time",
            "prompt": "ask_every_time",
            "remember": "remembered",
            "remembered": "remembered",
            "always": "always_allow",
            "always_allow": "always_allow",
        }
        value = aliases.get(raw, raw)
        if value is None:
            return None
        return value if value in {"ask_every_time", "remembered", "always_allow"} else "ask_every_time"

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
    animation_fidelity: AnimationFidelity | None = None
    animations_enabled: bool | None = None
    advanced_chat_physics: bool | None = None
    code_theme: str | None = None
    debug_panel_enabled: bool | None = None
    event_log_verbosity: EventLogVerbosity | None = None
    workflow_mode: WorkflowMode | None = None
    labs_flags: str | None = None

    @field_validator("animation_fidelity", mode="before")
    @classmethod
    def _normalize_animation_fidelity(cls, v: Any) -> str | None:
        if v is None:
            return None
        raw = str(v or "").strip().lower().replace("-", "_").replace(" ", "_")
        if not raw:
            return None
        aliases = {
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
        if self.animation_fidelity is not None:
            self.animations_enabled = self.animation_fidelity != "minimal"
        return self

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


class WorkspacesPatch(BaseModel):
    mission: bool | None = None
    app_builder: bool | None = None
    my_stuff: bool | None = None
    channels: bool | None = None
    token_economy: bool | None = None
    marketplace: bool | None = None
    office: bool | None = None


class TokenEconomySettingsPatch(BaseModel):
    monthly_budget: int | None = Field(default=None, ge=0, le=100_000_000)
    budget_alert_pct: str | None = None
    show_sidebar_spend: bool | None = None
    auto_summarize: bool | None = None


class ChannelsPatch(BaseModel):
    default_channel: str | None = None
    max_message_length: int | None = Field(default=None, ge=100, le=10_000)
    auto_route: bool | None = None
    notifications: bool | None = None
    allow_uploads: bool | None = None


class MarketplacePatch(BaseModel):
    auto_update: bool | None = None
    show_domain_modules: bool | None = None
    plugin_network_access: bool | None = None


class DataPatch(BaseModel):
    persist_history: bool | None = None
    auto_archive: bool | None = None


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
    workspaces: WorkspacesPatch | None = None
    token_economy: TokenEconomySettingsPatch | None = None
    channels: ChannelsPatch | None = None
    marketplace: MarketplacePatch | None = None
    data: DataPatch | None = None
