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
    answers: Dict[str, Any] = Field(default_factory=dict)


class APIKeysMasked(BaseModel):
    openai: Optional[str] = None
    anthropic: Optional[str] = None
    google: Optional[str] = None
    elevenlabs: Optional[str] = None
    azure_openai: Optional[str] = None
    custom: Optional[str] = None


class PreferencesResponse(BaseModel):
    appearance: AppearancePrefs = Field(default_factory=AppearancePrefs)
    voice: VoicePrefs = Field(default_factory=VoicePrefs)
    memory: MemoryPrefs = Field(default_factory=MemoryPrefs)
    notifications: NotificationPrefs = Field(default_factory=NotificationPrefs)
    autonomy: AutonomyPrefs = Field(default_factory=AutonomyPrefs)
    onboarding: OnboardingPrefs = Field(default_factory=OnboardingPrefs)
    api_keys: APIKeysMasked = Field(default_factory=APIKeysMasked)
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


class PreferencesPatch(BaseModel):
    appearance: Optional[AppearancePatch] = None
    voice: Optional[VoicePatch] = None
    memory: Optional[MemoryPatch] = None
    notifications: Optional[NotificationPatch] = None
    autonomy: Optional[AutonomyPatch] = None
    onboarding: Optional[OnboardingPatch] = None
    api_keys: Optional[APIKeysPatch] = None


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
            "onboarding": OnboardingPrefs().model_dump(),
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
                onboarding=OnboardingPrefs(**(base.get("onboarding") or {})),
                api_keys=APIKeysMasked(**masked),
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

                if patch.onboarding is not None:
                    current = OnboardingPrefs(**(base.get("onboarding") or {})).model_dump()
                    incoming = patch.onboarding.model_dump(exclude_unset=True)
                    fields_set = patch.onboarding.model_fields_set

                    # allow explicit nulls for timestamp/answers fields
                    for key in ("completed_at", "dismissed_at", "answers"):
                        if key in fields_set:
                            current[key] = incoming.get(key, None)

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

                self._save_base_prefs(conn, user_id, base)

        return self.get(user_id=user_id, thread_id=thread_id)
