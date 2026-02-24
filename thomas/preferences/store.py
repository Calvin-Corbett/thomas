"""
Thomas - User Preferences Store (SQLite)

Goals
- Durable preferences persisted in SQLite.
- Safe partial updates (PATCH semantics).
- Provider API keys encrypted at rest, with non-sensitive masking available without decrypting.

DB path resolution (in order):
- THOMAS_DB_PATH (preferred)
- THOMAS_SQLITE_PATH (legacy)
- ./thomas.db (fallback)

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
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field, field_validator

Theme = Literal["auto", "light", "dark"]
BubbleStyle = Literal["rounded", "square", "compact"]
AutonomyLevel = Literal["L1", "L2", "L3", "L4"]
ReasoningEffort = Literal["low", "medium", "high", "max", "xhigh"]
RunMode = Literal["auto", "fast", "thinking", "swarm", "batch"]
TokenEconomyLevel = Literal["cheap", "optimal", "max"]
ContradictionPolicy = Literal["latest_wins", "ask", "strict"]
ContextPruneStrategy = Literal["recency", "balanced", "aggressive"]
UIDensity = Literal["comfortable", "compact", "dense"]
EventLogVerbosity = Literal["minimal", "standard", "verbose"]

PROVIDERS = ("openai", "anthropic", "google", "elevenlabs", "azure_openai", "custom")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db_path() -> str:
    env_path = os.getenv("THOMAS_DB_PATH") or os.getenv("THOMAS_SQLITE_PATH")
    if env_path:
        return env_path
    return str(Path.cwd() / "thomas.db")


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
    thread_enabled: Optional[bool] = None  # computed only when thread_id is provided


class NotificationPrefs(BaseModel):
    web_push: bool = False
    telegram: bool = False
    desktop: bool = True


class AutonomyPrefs(BaseModel):
    default_level: AutonomyLevel = "L2"
    concurrency_limit: int = Field(default=2, ge=1, le=64)


class OnboardingPrefs(BaseModel):
    setup_completed: bool = False
    version: int = Field(default=0, ge=0, le=1000)
    completed_at: Optional[str] = None
    dismissed_at: Optional[str] = None
    current_step: str = ""
    connection_method: Optional[str] = None
    dependency_plan: Dict[str, Any] = Field(default_factory=dict)
    answers: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("current_step")
    @classmethod
    def _trim_current_step(cls, v: str) -> str:
        return str(v or "").strip()

    @field_validator("connection_method")
    @classmethod
    def _trim_connection_method(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None


class APIKeysMasked(BaseModel):
    openai: Optional[str] = None
    anthropic: Optional[str] = None
    google: Optional[str] = None
    elevenlabs: Optional[str] = None
    azure_openai: Optional[str] = None
    custom: Optional[str] = None


class ProfilePrefs(BaseModel):
    display_name: str = ""
    avatar_url: str = ""

    @field_validator("display_name", "avatar_url")
    @classmethod
    def _trim_fields(cls, v: str) -> str:
        return str(v or "").strip()


class AdvancedModelPrefs(BaseModel):
    active_profile: str = ""    # persisted selected provider/profile
    model_id: str = ""          # persisted model override
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    max_output_tokens: int = Field(default=4096, ge=128, le=32768)
    reasoning_effort: ReasoningEffort = "medium"
    reasoning_token_budget: int = Field(default=4096, ge=128, le=65536)
    json_mode: bool = False
    deterministic_seed: Optional[int] = Field(default=None, ge=0, le=2147483647)
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
    labs_flags: str = ""

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
    updated_at: str = Field(default_factory=utc_now_iso)


class AppearancePatch(BaseModel):
    theme: Optional[Theme] = None
    font_size: Optional[int] = Field(default=None, ge=12, le=28)
    bubble_style: Optional[BubbleStyle] = None


class VoicePatch(BaseModel):
    tts_voice: Optional[str] = None
    speed: Optional[float] = Field(default=None, ge=0.5, le=2.0)
    wake_word_enabled: Optional[bool] = None
    mic_device_id: Optional[str] = None


class MemoryPatch(BaseModel):
    enabled_global: Optional[bool] = None
    # If explicitly provided (even null), requires thread_id query param.
    # True/False sets override; null clears override.
    thread_enabled: Optional[bool] = None


class NotificationPatch(BaseModel):
    web_push: Optional[bool] = None
    telegram: Optional[bool] = None
    desktop: Optional[bool] = None


class AutonomyPatch(BaseModel):
    default_level: Optional[AutonomyLevel] = None
    concurrency_limit: Optional[int] = Field(default=None, ge=1, le=64)


class OnboardingPatch(BaseModel):
    setup_completed: Optional[bool] = None
    version: Optional[int] = Field(default=None, ge=0, le=1000)
    completed_at: Optional[str] = None
    dismissed_at: Optional[str] = None
    current_step: Optional[str] = None
    connection_method: Optional[str] = None
    dependency_plan: Optional[Dict[str, Any]] = None
    answers: Optional[Dict[str, Any]] = None


class APIKeysPatch(BaseModel):
    # Provide full keys here (encrypted at rest).
    # Empty string "" or null deletes the key.
    openai: Optional[str] = None
    anthropic: Optional[str] = None
    google: Optional[str] = None
    elevenlabs: Optional[str] = None
    azure_openai: Optional[str] = None
    custom: Optional[str] = None


class ProfilePatch(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


class AdvancedModelPatch(BaseModel):
    active_profile: Optional[str] = None
    model_id: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    frequency_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    max_output_tokens: Optional[int] = Field(default=None, ge=128, le=32768)
    reasoning_effort: Optional[ReasoningEffort] = None
    reasoning_token_budget: Optional[int] = Field(default=None, ge=128, le=65536)
    json_mode: Optional[bool] = None
    deterministic_seed: Optional[int] = Field(default=None, ge=0, le=2147483647)
    stop_sequences: Optional[str] = None


class AdvancedToolsPatch(BaseModel):
    auto_tool_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    require_command_approval: Optional[bool] = None
    allow_shell: Optional[bool] = None
    allow_file_write: Optional[bool] = None
    allow_network: Optional[bool] = None
    allow_browser: Optional[bool] = None
    allow_channels: Optional[bool] = None
    allow_git: Optional[bool] = None
    tool_timeout_s: Optional[int] = Field(default=None, ge=5, le=1800)
    max_parallel_tools: Optional[int] = Field(default=None, ge=1, le=32)
    allowed_paths: Optional[str] = None
    blocked_commands: Optional[str] = None


class AdvancedMemoryPatch(BaseModel):
    include_global_memory: Optional[bool] = None
    include_profile_memory: Optional[bool] = None
    include_thread_memory: Optional[bool] = None
    pins_only: Optional[bool] = None
    max_pack_tokens: Optional[int] = Field(default=None, ge=200, le=64000)
    decay_half_life_hours: Optional[float] = Field(default=None, ge=1.0, le=87600.0)
    retrieval_top_k: Optional[int] = Field(default=None, ge=1, le=64)
    auto_summarize_threshold: Optional[int] = Field(default=None, ge=10, le=2000)
    memory_decay_days: Optional[int] = Field(default=None, ge=1, le=3650)
    auto_compact_enabled: Optional[bool] = None
    auto_compact_episode_threshold: Optional[int] = Field(default=None, ge=10, le=1000000)
    auto_compact_min_interval_hours: Optional[float] = Field(default=None, ge=0.1, le=8760.0)
    auto_optimize_enabled: Optional[bool] = None
    auto_optimize_waste_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    auto_optimize_min_interval_hours: Optional[float] = Field(default=None, ge=0.1, le=8760.0)
    contradiction_policy: Optional[ContradictionPolicy] = None
    context_prune_strategy: Optional[ContextPruneStrategy] = None
    pinned_context: Optional[str] = None


class AdvancedCostPatch(BaseModel):
    session_token_budget: Optional[int] = Field(default=None, ge=1000, le=5000000)
    daily_token_budget: Optional[int] = Field(default=None, ge=10000, le=50000000)
    throttle_on_budget: Optional[bool] = None
    low_cost_mode: Optional[bool] = None
    max_retries: Optional[int] = Field(default=None, ge=0, le=20)
    retry_backoff_ms: Optional[int] = Field(default=None, ge=0, le=120000)
    provider_failover_chain: Optional[str] = None
    model_failover_chain: Optional[str] = None


class AdvancedRuntimePatch(BaseModel):
    default_mode: Optional[RunMode] = None
    default_token_economy: Optional[TokenEconomyLevel] = None
    max_agent_iterations: Optional[int] = Field(default=None, ge=0, le=200)
    quality_enforce: Optional[bool] = None
    quality_require_verification_for_coding: Optional[bool] = None
    quality_require_tests_for_code_edits: Optional[bool] = None
    quality_require_monolith_guard_for_coding: Optional[bool] = None


class AdvancedFailoverPatch(BaseModel):
    enabled: Optional[bool] = None
    chat_auto_failover: Optional[bool] = None
    fallback_on_auth_error: Optional[bool] = None
    cooldown_seconds: Optional[int] = Field(default=None, ge=0, le=86400)


class AdvancedPrivacyPatch(BaseModel):
    telemetry_enabled: Optional[bool] = None
    redact_secrets_in_logs: Optional[bool] = None
    pii_guard_strict: Optional[bool] = None
    local_only_mode: Optional[bool] = None
    audit_log_enabled: Optional[bool] = None
    retention_days: Optional[int] = Field(default=None, ge=1, le=3650)
    export_on_exit: Optional[bool] = None


class AdvancedInterfacePatch(BaseModel):
    ui_density: Optional[UIDensity] = None
    show_timestamps: Optional[bool] = None
    show_token_meter: Optional[bool] = None
    animations_enabled: Optional[bool] = None
    code_theme: Optional[str] = None
    debug_panel_enabled: Optional[bool] = None
    event_log_verbosity: Optional[EventLogVerbosity] = None
    labs_flags: Optional[str] = None


class AdvancedPatch(BaseModel):
    model: Optional[AdvancedModelPatch] = None
    tools: Optional[AdvancedToolsPatch] = None
    memory: Optional[AdvancedMemoryPatch] = None
    cost: Optional[AdvancedCostPatch] = None
    runtime: Optional[AdvancedRuntimePatch] = None
    failover: Optional[AdvancedFailoverPatch] = None
    privacy: Optional[AdvancedPrivacyPatch] = None
    interface: Optional[AdvancedInterfacePatch] = None


class PreferencesPatch(BaseModel):
    appearance: Optional[AppearancePatch] = None
    voice: Optional[VoicePatch] = None
    memory: Optional[MemoryPatch] = None
    notifications: Optional[NotificationPatch] = None
    autonomy: Optional[AutonomyPatch] = None
    advanced: Optional[AdvancedPatch] = None
    onboarding: Optional[OnboardingPatch] = None
    api_keys: Optional[APIKeysPatch] = None
    profile: Optional[ProfilePatch] = None


class PreferencesStore:
    """
    Single-user local-first default.
    Provide X-User-Id header to API to segment settings by user_id.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or get_db_path()
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> Dict[str, str]:
        rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
        return {r["name"]: r["type"] for r in rows}

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            # Base tables
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS preferences (
                    user_id TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS preference_keys (
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    enc_value TEXT NOT NULL,
                    mask_tail TEXT,
                    key_hash TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, provider)
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_preferences (
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    memory_enabled INTEGER,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, thread_id)
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS preferences_meta (
                    k TEXT PRIMARY KEY,
                    v TEXT NOT NULL
                );
                """
            )

            # Migrations: add columns if an older DB exists
            cols = self._table_columns(conn, "preference_keys")
            if "mask_tail" not in cols:
                conn.execute("ALTER TABLE preference_keys ADD COLUMN mask_tail TEXT;")
            if "key_hash" not in cols:
                conn.execute("ALTER TABLE preference_keys ADD COLUMN key_hash TEXT;")

            conn.commit()

    def _get_fernet(self, conn: sqlite3.Connection) -> Fernet:
        env_key = os.getenv("THOMAS_PREFERENCES_FERNET_KEY")
        if env_key:
            return Fernet(env_key.encode("utf-8"))

        secret = os.getenv("THOMAS_SECRET_KEY")
        if secret:
            return Fernet(_derive_fernet_key_from_secret(secret))

        row = conn.execute("SELECT v FROM preferences_meta WHERE k = ?", ("fernet_key",)).fetchone()
        if row:
            return Fernet(row["v"].encode("utf-8"))

        # local-only fallback: generate and persist in DB
        new_key = Fernet.generate_key()
        conn.execute(
            "INSERT OR REPLACE INTO preferences_meta (k, v) VALUES (?, ?)",
            ("fernet_key", new_key.decode("utf-8")),
        )
        # do NOT commit inside a transaction caller might be holding
        return Fernet(new_key)

    def _encrypt(self, conn: sqlite3.Connection, plaintext: str) -> str:
        token = self._get_fernet(conn).encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def _decrypt(self, conn: sqlite3.Connection, token: str) -> str:
        try:
            b = self._get_fernet(conn).decrypt(token.encode("utf-8"))
        except InvalidToken as e:
            raise ValueError("Unable to decrypt stored key (encryption key mismatch).") from e
        return b.decode("utf-8")

    def _default_prefs_dict(self) -> Dict[str, Any]:
        return {
            "appearance": AppearancePrefs().model_dump(),
            "voice": VoicePrefs().model_dump(),
            "memory": {"enabled_global": True},
            "notifications": NotificationPrefs().model_dump(),
            "autonomy": AutonomyPrefs().model_dump(),
            "advanced": AdvancedPrefs().model_dump(),
            "onboarding": OnboardingPrefs().model_dump(),
            "profile": ProfilePrefs().model_dump(),
        }

    def _get_or_create_base_prefs(self, conn: sqlite3.Connection, user_id: str) -> Dict[str, Any]:
        row = conn.execute("SELECT data_json FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            try:
                return json.loads(row["data_json"])
            except json.JSONDecodeError:
                return self._default_prefs_dict()
        return self._default_prefs_dict()

    def _save_base_prefs(self, conn: sqlite3.Connection, user_id: str, prefs: Dict[str, Any]) -> str:
        updated_at = utc_now_iso()
        conn.execute(
            "INSERT OR REPLACE INTO preferences (user_id, data_json, updated_at) VALUES (?, ?, ?)",
            (user_id, json.dumps(prefs, separators=(",", ":"), ensure_ascii=False), updated_at),
        )
        return updated_at

    def _get_thread_memory_override(self, conn: sqlite3.Connection, user_id: str, thread_id: str) -> Optional[bool]:
        row = conn.execute(
            "SELECT memory_enabled FROM thread_preferences WHERE user_id = ? AND thread_id = ?",
            (user_id, thread_id),
        ).fetchone()
        if not row:
            return None
        v = row["memory_enabled"]
        return None if v is None else bool(int(v))

    def _set_thread_memory_override(self, conn: sqlite3.Connection, user_id: str, thread_id: str, enabled: Optional[bool]) -> None:
        if enabled is None:
            conn.execute(
                "DELETE FROM thread_preferences WHERE user_id = ? AND thread_id = ?",
                (user_id, thread_id),
            )
            return
        conn.execute(
            """
            INSERT OR REPLACE INTO thread_preferences (user_id, thread_id, memory_enabled, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, thread_id, 1 if enabled else 0, utc_now_iso()),
        )

    def _get_masked_keys(self, conn: sqlite3.Connection, user_id: str) -> Dict[str, Optional[str]]:
        masked: Dict[str, Optional[str]] = {p: None for p in PROVIDERS}
        rows = conn.execute(
            "SELECT provider, mask_tail, enc_value FROM preference_keys WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        for r in rows:
            provider = r["provider"]
            if provider not in masked:
                continue
            if r["mask_tail"]:
                masked[provider] = r["mask_tail"]
                continue
            # fallback for older rows: decrypt once, compute mask, update row
            try:
                plain = self._decrypt(conn, r["enc_value"])
                m = _mask_key_tail(plain)
                masked[provider] = m
                conn.execute(
                    "UPDATE preference_keys SET mask_tail=?, key_hash=? WHERE user_id=? AND provider=?",
                    (m, _sha256_hex(plain), user_id, provider),
                )
            except Exception:
                masked[provider] = "••••••(unreadable)"
        return masked

    def _set_api_key_in_tx(self, conn: sqlite3.Connection, user_id: str, provider: str, value: Optional[str]) -> None:
        provider = provider.strip().lower()
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}'.")
        if value is None or (isinstance(value, str) and value.strip() == ""):
            conn.execute(
                "DELETE FROM preference_keys WHERE user_id = ? AND provider = ?",
                (user_id, provider),
            )
            return
        v = value.strip()
        enc = self._encrypt(conn, v)
        mask_tail = _mask_key_tail(v)
        key_hash = _sha256_hex(v)
        conn.execute(
            """
            INSERT OR REPLACE INTO preference_keys (user_id, provider, enc_value, mask_tail, key_hash, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, provider, enc, mask_tail, key_hash, utc_now_iso()),
        )

    def set_api_key(self, user_id: str, provider: str, value: Optional[str]) -> None:
        with self._lock, self._connect() as conn:
            with conn:
                self._set_api_key_in_tx(conn, user_id, provider, value)

    def get_api_key_plain(self, user_id: str, provider: str) -> Optional[str]:
        provider = provider.strip().lower()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT enc_value FROM preference_keys WHERE user_id = ? AND provider = ?",
                (user_id, provider),
            ).fetchone()
            if not row:
                return None
            return self._decrypt(conn, row["enc_value"])

    def get(self, user_id: str = "default", thread_id: Optional[str] = None) -> PreferencesResponse:
        with self._lock, self._connect() as conn:
            base = self._get_or_create_base_prefs(conn, user_id)
            masked = self._get_masked_keys(conn, user_id)

            row = conn.execute("SELECT updated_at FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
            updated_at = row["updated_at"] if row else utc_now_iso()

            mem = base.get("memory", {}) or {}
            enabled_global = bool(mem.get("enabled_global", True))
            thread_enabled: Optional[bool] = None
            if thread_id:
                ov = self._get_thread_memory_override(conn, user_id, thread_id)
                thread_enabled = enabled_global if ov is None else ov

            return PreferencesResponse(
                appearance=AppearancePrefs(**(base.get("appearance") or {})),
                voice=VoicePrefs(**(base.get("voice") or {})),
                memory=MemoryPrefs(enabled_global=enabled_global, thread_enabled=thread_enabled),
                notifications=NotificationPrefs(**(base.get("notifications") or {})),
                autonomy=AutonomyPrefs(**(base.get("autonomy") or {})),
                advanced=AdvancedPrefs(**(base.get("advanced") or {})),
                onboarding=OnboardingPrefs(**(base.get("onboarding") or {})),
                api_keys=APIKeysMasked(**masked),
                profile=ProfilePrefs(**(base.get("profile") or {})),
                updated_at=updated_at,
            )

    def patch(self, patch: PreferencesPatch, user_id: str = "default", thread_id: Optional[str] = None) -> PreferencesResponse:
        """
        PATCH semantics:
        - only fields present are considered
        - null values:
            - memory.thread_enabled: clears override (requires thread_id)
            - api_keys.<provider>: deletes key
        """
        with self._lock, self._connect() as conn:
            with conn:
                base = self._get_or_create_base_prefs(conn, user_id)

                if patch.appearance is not None:
                    current = AppearancePrefs(**(base.get("appearance") or {})).model_dump()
                    incoming = patch.appearance.model_dump(exclude_unset=True)
                    for k, v in incoming.items():
                        if v is not None:
                            current[k] = v
                    base["appearance"] = AppearancePrefs(**current).model_dump()

                if patch.voice is not None:
                    current = VoicePrefs(**(base.get("voice") or {})).model_dump()
                    incoming = patch.voice.model_dump(exclude_unset=True)
                    for k, v in incoming.items():
                        if v is not None:
                            current[k] = v
                    base["voice"] = VoicePrefs(**current).model_dump()

                if patch.memory is not None:
                    mem = base.get("memory") or {}
                    incoming = patch.memory.model_dump(exclude_unset=True)

                    if "enabled_global" in incoming and incoming["enabled_global"] is not None:
                        mem["enabled_global"] = bool(incoming["enabled_global"])
                    base["memory"] = mem

                    if "thread_enabled" in patch.memory.model_fields_set:
                        if not thread_id:
                            raise ValueError("thread_id is required to patch memory.thread_enabled")
                        self._set_thread_memory_override(conn, user_id, thread_id, incoming.get("thread_enabled", None))

                if patch.notifications is not None:
                    current = NotificationPrefs(**(base.get("notifications") or {})).model_dump()
                    incoming = patch.notifications.model_dump(exclude_unset=True)
                    for k, v in incoming.items():
                        if v is not None:
                            current[k] = v
                    base["notifications"] = NotificationPrefs(**current).model_dump()

                if patch.autonomy is not None:
                    current = AutonomyPrefs(**(base.get("autonomy") or {})).model_dump()
                    incoming = patch.autonomy.model_dump(exclude_unset=True)
                    for k, v in incoming.items():
                        if v is not None:
                            current[k] = v
                    base["autonomy"] = AutonomyPrefs(**current).model_dump()

                if patch.advanced is not None:
                    current_adv = AdvancedPrefs(**(base.get("advanced") or {})).model_dump()

                    if patch.advanced.model is not None:
                        current = AdvancedModelPrefs(**(current_adv.get("model") or {})).model_dump()
                        incoming = patch.advanced.model.model_dump(exclude_unset=True)
                        fields_set = patch.advanced.model.model_fields_set
                        for k in fields_set:
                            if k == "deterministic_seed":
                                current[k] = incoming.get(k, None)
                                continue
                            if k in incoming and incoming[k] is not None:
                                current[k] = incoming[k]
                        current_adv["model"] = AdvancedModelPrefs(**current).model_dump()

                    if patch.advanced.tools is not None:
                        current = AdvancedToolsPrefs(**(current_adv.get("tools") or {})).model_dump()
                        incoming = patch.advanced.tools.model_dump(exclude_unset=True)
                        for k, v in incoming.items():
                            if v is not None:
                                current[k] = v
                        current_adv["tools"] = AdvancedToolsPrefs(**current).model_dump()

                    if patch.advanced.memory is not None:
                        current = AdvancedMemoryPrefs(**(current_adv.get("memory") or {})).model_dump()
                        incoming = patch.advanced.memory.model_dump(exclude_unset=True)
                        for k, v in incoming.items():
                            if v is not None:
                                current[k] = v
                        current_adv["memory"] = AdvancedMemoryPrefs(**current).model_dump()

                    if patch.advanced.cost is not None:
                        current = AdvancedCostPrefs(**(current_adv.get("cost") or {})).model_dump()
                        incoming = patch.advanced.cost.model_dump(exclude_unset=True)
                        for k, v in incoming.items():
                            if v is not None:
                                current[k] = v
                        current_adv["cost"] = AdvancedCostPrefs(**current).model_dump()

                    if patch.advanced.runtime is not None:
                        current = AdvancedRuntimePrefs(**(current_adv.get("runtime") or {})).model_dump()
                        incoming = patch.advanced.runtime.model_dump(exclude_unset=True)
                        for k, v in incoming.items():
                            if v is not None:
                                current[k] = v
                        current_adv["runtime"] = AdvancedRuntimePrefs(**current).model_dump()

                    if patch.advanced.failover is not None:
                        current = AdvancedFailoverPrefs(**(current_adv.get("failover") or {})).model_dump()
                        incoming = patch.advanced.failover.model_dump(exclude_unset=True)
                        for k, v in incoming.items():
                            if v is not None:
                                current[k] = v
                        current_adv["failover"] = AdvancedFailoverPrefs(**current).model_dump()

                    if patch.advanced.privacy is not None:
                        current = AdvancedPrivacyPrefs(**(current_adv.get("privacy") or {})).model_dump()
                        incoming = patch.advanced.privacy.model_dump(exclude_unset=True)
                        for k, v in incoming.items():
                            if v is not None:
                                current[k] = v
                        current_adv["privacy"] = AdvancedPrivacyPrefs(**current).model_dump()

                    if patch.advanced.interface is not None:
                        current = AdvancedInterfacePrefs(**(current_adv.get("interface") or {})).model_dump()
                        incoming = patch.advanced.interface.model_dump(exclude_unset=True)
                        for k, v in incoming.items():
                            if v is not None:
                                current[k] = v
                        current_adv["interface"] = AdvancedInterfacePrefs(**current).model_dump()

                    base["advanced"] = AdvancedPrefs(**current_adv).model_dump()

                if patch.onboarding is not None:
                    current = OnboardingPrefs(**(base.get("onboarding") or {})).model_dump()
                    incoming = patch.onboarding.model_dump(exclude_unset=True)
                    fields_set = patch.onboarding.model_fields_set

                    # Nullable fields can be explicitly cleared via null.
                    for key in ("completed_at", "dismissed_at", "connection_method"):
                        if key in fields_set:
                            current[key] = incoming.get(key, None)

                    # Dict fields can be explicitly cleared via null -> {}.
                    for key in ("answers", "dependency_plan"):
                        if key in fields_set:
                            value = incoming.get(key, None)
                            current[key] = value if isinstance(value, dict) else {}

                    # String progress marker: null/empty clears to default "".
                    if "current_step" in fields_set:
                        value = incoming.get("current_step", None)
                        current["current_step"] = str(value).strip() if isinstance(value, str) else ""

                    for key in ("setup_completed", "version"):
                        if key in incoming and incoming[key] is not None:
                            current[key] = incoming[key]

                    base["onboarding"] = OnboardingPrefs(**current).model_dump()

                if patch.api_keys is not None:
                    incoming = patch.api_keys.model_dump(exclude_unset=True)
                    for provider, value in incoming.items():
                        if value is None or (isinstance(value, str) and value.strip() == ""):
                            self._set_api_key_in_tx(conn, user_id, provider, None)
                        else:
                            self._set_api_key_in_tx(conn, user_id, provider, value)

                if patch.profile is not None:
                    current = ProfilePrefs(**(base.get("profile") or {})).model_dump()
                    incoming = patch.profile.model_dump(exclude_unset=True)
                    for k, v in incoming.items():
                        if v is not None:
                            current[k] = str(v).strip()
                    base["profile"] = ProfilePrefs(**current).model_dump()

                self._save_base_prefs(conn, user_id, base)

        return self.get(user_id=user_id, thread_id=thread_id)
