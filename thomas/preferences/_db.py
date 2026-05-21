"""SQLite-based preferences store with encryption support."""

import json
import os
import sqlite3
import threading
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from ._patches import PreferencesPatch
from ._prefs import (
    AdvancedCostPrefs,
    AdvancedFailoverPrefs,
    AdvancedInterfacePrefs,
    AdvancedMemoryPrefs,
    AdvancedModelPrefs,
    AdvancedPrefs,
    AdvancedPrivacyPrefs,
    AdvancedRuntimePrefs,
    AdvancedSecurityPrefs,
    AdvancedToolsPrefs,
    APIKeysMasked,
    AppearancePrefs,
    AutonomyPrefs,
    MemoryPrefs,
    NotificationPrefs,
    OnboardingPrefs,
    PreferencesResponse,
    ProfilePrefs,
    VoicePrefs,
)
from ._types import _NON_CODER_RUNTIME_LOCKS, PROVIDERS
from ._utils import (
    _derive_fernet_key_from_secret,
    _mask_key_tail,
    _sha256_hex,
    get_db_path,
    normalize_profile_type,
    normalize_review_depth,
    utc_now_iso,
)


class PreferencesStore:
    """
    Single-user local-first default.
    Provide X-User-Id header to API to segment settings by user_id.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or get_db_path()
        self._lock = threading.RLock()
        # Ensure parent directory exists. sqlite3.connect fails with
        # "unable to open database file" if the directory is missing — a common
        # failure mode in CI sandboxes where the default db path lives under a
        # not-yet-created HOME subtree.
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        import contextlib

        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.OperationalError:
            # Stale WAL/SHM files from unclean shutdown — try recovering
            conn.close()
            for suffix in ("-wal", "-shm"):
                wal_path = self.db_path + suffix
                if os.path.exists(wal_path):
                    with contextlib.suppress(OSError):
                        os.remove(wal_path)
            conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except sqlite3.OperationalError:
                # Fall back to DELETE journal mode if WAL still won't work
                conn.execute("PRAGMA journal_mode=DELETE;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> dict[str, str]:
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

    def _default_prefs_dict(self) -> dict[str, Any]:
        return {
            "appearance": AppearancePrefs().model_dump(),
            "voice": VoicePrefs().model_dump(),
            "memory": {"enabled_global": True},
            "notifications": NotificationPrefs().model_dump(),
            "autonomy": AutonomyPrefs().model_dump(),
            "advanced": AdvancedPrefs().model_dump(),
            "onboarding": OnboardingPrefs().model_dump(),
            "profile": ProfilePrefs().model_dump(),
            "thomads": {},
            "workspaces": {
                "mission": True,
                "app_builder": True,
                "my_stuff": True,
                "channels": True,
                "token_economy": True,
                "marketplace": True,
                "office": False,
            },
            "token_economy": {
                "monthly_budget": 5_000_000,
                "budget_alert_pct": "75",
                "show_sidebar_spend": True,
                "auto_summarize": False,
            },
            "channels": {
                "default_channel": "none",
                "max_message_length": 4000,
                "auto_route": True,
                "notifications": True,
                "allow_uploads": True,
            },
            "marketplace": {
                "auto_update": True,
                "show_domain_modules": False,
                "plugin_network_access": True,
            },
            "data": {
                "persist_history": True,
                "auto_archive": False,
            },
        }

    @staticmethod
    def _enforce_non_coder_runtime_locks(base: dict[str, Any]) -> bool:
        """Force strict quality runtime flags when profile_type=non_coder."""
        profile = base.get("profile") if isinstance(base, dict) else None
        profile_type = normalize_profile_type(
            (profile or {}).get("profile_type") if isinstance(profile, dict) else None,
            default="adaptive",
        )
        if profile_type != "non_coder":
            return False

        advanced = base.get("advanced") if isinstance(base, dict) else None
        adv_obj = dict(advanced) if isinstance(advanced, dict) else {}
        runtime = adv_obj.get("runtime")
        runtime_obj = dict(runtime) if isinstance(runtime, dict) else {}
        changed = False
        for key, expected in _NON_CODER_RUNTIME_LOCKS.items():
            if bool(runtime_obj.get(key)) is not bool(expected):
                runtime_obj[key] = bool(expected)
                changed = True
        if not changed:
            return False
        adv_obj["runtime"] = runtime_obj
        base["advanced"] = adv_obj
        return True

    def _get_or_create_base_prefs(self, conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT data_json FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            try:
                return json.loads(row["data_json"])
            except json.JSONDecodeError:
                return self._default_prefs_dict()
        return self._default_prefs_dict()

    def _save_base_prefs(self, conn: sqlite3.Connection, user_id: str, prefs: dict[str, Any]) -> str:
        updated_at = utc_now_iso()
        conn.execute(
            "INSERT OR REPLACE INTO preferences (user_id, data_json, updated_at) VALUES (?, ?, ?)",
            (user_id, json.dumps(prefs, separators=(",", ":"), ensure_ascii=False), updated_at),
        )
        return updated_at

    def _get_thread_memory_override(self, conn: sqlite3.Connection, user_id: str, thread_id: str) -> bool | None:
        row = conn.execute(
            "SELECT memory_enabled FROM thread_preferences WHERE user_id = ? AND thread_id = ?",
            (user_id, thread_id),
        ).fetchone()
        if not row:
            return None
        v = row["memory_enabled"]
        return None if v is None else bool(int(v))

    def _set_thread_memory_override(
        self, conn: sqlite3.Connection, user_id: str, thread_id: str, enabled: bool | None
    ) -> None:
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

    def _get_masked_keys(self, conn: sqlite3.Connection, user_id: str) -> dict[str, str | None]:
        masked: dict[str, str | None] = {p: None for p in PROVIDERS}
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

    def _set_api_key_in_tx(self, conn: sqlite3.Connection, user_id: str, provider: str, value: str | None) -> None:
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

    def set_api_key(self, user_id: str, provider: str, value: str | None) -> None:
        with self._lock, self._connect() as conn, conn:  # noqa: SIM117
            self._set_api_key_in_tx(conn, user_id, provider, value)

    def get_api_key_plain(self, user_id: str, provider: str) -> str | None:
        provider = provider.strip().lower()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT enc_value FROM preference_keys WHERE user_id = ? AND provider = ?",
                (user_id, provider),
            ).fetchone()
            if not row:
                return None
            return self._decrypt(conn, row["enc_value"])

    def set_third_party_agent_access(
        self,
        enabled: bool,
        *,
        user_id: str = "default",
        changed_by: str = "system",
    ) -> PreferencesResponse:
        with self._lock, self._connect() as conn, conn:
            base = self._get_or_create_base_prefs(conn, user_id)
            advanced = dict(base.get("advanced") or {})
            security = AdvancedSecurityPrefs(**(advanced.get("security") or {})).model_dump()
            security["allow_third_party_agent_access"] = bool(enabled)
            security["enforcement_mode"] = "development" if enabled else "protected"
            security["last_changed_at"] = utc_now_iso()
            security["last_changed_by"] = str(changed_by or "system")
            advanced["security"] = security
            base["advanced"] = advanced
            self._save_base_prefs(conn, user_id, base)
        return self.get(user_id=user_id)

    def set_human_breakglass_enabled(
        self,
        enabled: bool,
        *,
        user_id: str = "default",
        changed_by: str = "system",
    ) -> PreferencesResponse:
        with self._lock, self._connect() as conn, conn:
            base = self._get_or_create_base_prefs(conn, user_id)
            advanced = dict(base.get("advanced") or {})
            security = AdvancedSecurityPrefs(**(advanced.get("security") or {})).model_dump()
            security["human_breakglass_enabled"] = bool(enabled)
            security["human_breakglass_changed_at"] = utc_now_iso()
            security["human_breakglass_changed_by"] = str(changed_by or "system")
            advanced["security"] = security
            base["advanced"] = advanced
            self._save_base_prefs(conn, user_id, base)
        return self.get(user_id=user_id)

    def get(self, user_id: str = "default", thread_id: str | None = None) -> PreferencesResponse:
        with self._lock, self._connect() as conn:
            base = self._get_or_create_base_prefs(conn, user_id)
            self._enforce_non_coder_runtime_locks(base)
            masked = self._get_masked_keys(conn, user_id)

            row = conn.execute("SELECT updated_at FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
            updated_at = row["updated_at"] if row else utc_now_iso()

            mem = base.get("memory", {}) or {}
            enabled_global = bool(mem.get("enabled_global", True))
            thread_enabled: bool | None = None
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
                thomads=base.get("thomads") if isinstance(base.get("thomads"), dict) else {},
                updated_at=updated_at,
            )

    def patch(
        self, patch: PreferencesPatch, user_id: str = "default", thread_id: str | None = None
    ) -> PreferencesResponse:
        """
        PATCH semantics:
        - only fields present are considered
        - null values:
            - memory.thread_enabled: clears override (requires thread_id)
            - api_keys.<provider>: deletes key
        """
        with self._lock, self._connect() as conn, conn:
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

            if patch.thomads is not None or "thomads" in patch.model_fields_set:
                if patch.thomads is None:
                    base["thomads"] = {}
                else:
                    incoming = patch.thomads or {}
                    current = dict(base.get("thomads") or {})
                    if not isinstance(incoming, dict):
                        raise ValueError("thomads must be a JSON object")
                    for key, value in incoming.items():
                        current[str(key)] = value
                    base["thomads"] = current

            if patch.profile is not None:
                current = ProfilePrefs(**(base.get("profile") or {})).model_dump()
                incoming = patch.profile.model_dump(exclude_unset=True)
                fields_set = patch.profile.model_fields_set
                for k in fields_set:
                    if k == "profile_type":
                        current[k] = normalize_profile_type(incoming.get(k, None))
                        continue
                    if k == "review_depth":
                        current[k] = normalize_review_depth(incoming.get(k, None))
                        continue
                    v = incoming.get(k, None)
                    if v is not None:
                        current[k] = str(v).strip()
                base["profile"] = ProfilePrefs(**current).model_dump()

            # ── New patch fields: workspaces, token_economy, channels, marketplace, data ──
            for key in ("workspaces", "token_economy", "channels", "marketplace", "data"):
                patch_field = getattr(patch, key, None)
                if patch_field is not None:
                    current = dict(base.get(key) or {})
                    incoming = (
                        patch_field.model_dump(exclude_unset=True)
                        if hasattr(patch_field, "model_dump")
                        else dict(patch_field)
                    )
                    for k, v in incoming.items():
                        current[k] = v
                    base[key] = current

            self._enforce_non_coder_runtime_locks(base)
            self._save_base_prefs(conn, user_id, base)

        return self.get(user_id=user_id, thread_id=thread_id)
