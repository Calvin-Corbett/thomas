"""Thomas-owned lifecycle and history support for the Discord bridge."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess as _subprocess
from importlib import import_module
from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig
from thomas.integrations.discord_bridge_runtime_history import DiscordBridgeRuntimeHistoryMixin
from thomas.integrations.discord_bridge_runtime_lifecycle import DiscordBridgeRuntimeLifecycleMixin
from thomas.integrations.discord_bridge_runtime_support import (
    _DEFAULT_VOICE_WAKE_WORDS,
    _ENV_LINE_RE,
    _PATH_ENV_KEY,
    _SECRET_PROFILE_MAP,
    _STATE_VERSION,
    ENV_FIELD_MAP,
    SECRET_FIELDS,
    _clamp_int,
    _default_embedded_bridge_root,
    _default_project_root,
    _default_shared_secret_root,
    _format_env_value,
    _normalize_csv,
    _normalize_string_list,
    _now_utc_iso,
    _parse_bool,
    _parse_env_value,
    _read_json_file,
    _safe_text,
    _write_json_file,
)

subprocess = _subprocess


class DiscordBridgeRuntimeError(RuntimeError):
    """Raised when Discord bridge lifecycle operations fail."""


def _secret_store_cls() -> Any:
    return import_module("thomas.server.secrets").SecretStore


class DiscordBridgeRuntime(
    DiscordBridgeRuntimeLifecycleMixin,
    DiscordBridgeRuntimeHistoryMixin,
):
    """Manage the Discord bridge from the Thomas server."""

    def __init__(self, config: AppConfig, *, bridge_root: Path | None = None):
        self._config = config
        self._project_root = _default_project_root()
        self._default_bridge_root = _default_embedded_bridge_root()
        self._legacy_external_bridge_root = (Path.home() / "discord-server-bot").expanduser()
        self._bridge_root = Path(bridge_root or os.environ.get(_PATH_ENV_KEY) or self._default_bridge_root).expanduser()
        self._state_dir = config.memory.root_path / ".thomas" / "discord_bridge"
        self._bridge_data_dir = self._state_dir / "service_data"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._bridge_data_dir.mkdir(parents=True, exist_ok=True)
        self._legacy_secret_root = config.memory.root_path / ".thomas"
        self._secret_store = _secret_store_cls()(_default_shared_secret_root())
        self._migrate_legacy_external_bridge_layout()
        self._migrate_legacy_secret_store()

    @property
    def bridge_root(self) -> Path:
        return self._bridge_root

    @property
    def env_path(self) -> Path:
        if self.uses_embedded_bridge:
            return self._state_dir / "bridge.env"
        return self._bridge_root / ".env"

    @property
    def state_path(self) -> Path:
        return self._state_dir / "state.json"

    @property
    def history_path(self) -> Path:
        return self._state_dir / "history.jsonl"

    @property
    def log_path(self) -> Path:
        return self._state_dir / "bridge.log"

    @property
    def runtime_settings_path(self) -> Path:
        if self.uses_embedded_bridge:
            return self._bridge_data_dir / "runtime-settings.json"
        return self._bridge_root / "data" / "runtime-settings.json"

    @property
    def sessions_path(self) -> Path:
        if self.uses_embedded_bridge:
            return self._bridge_data_dir / "sessions.json"
        return self._bridge_root / "data" / "sessions.json"

    @property
    def entrypoint_path(self) -> Path:
        return self._bridge_root / "src" / "index.js"

    @property
    def voice_probe_path(self) -> Path:
        return self._bridge_root / "scripts" / "voice-probe.mjs"

    @property
    def package_json_path(self) -> Path:
        return self._bridge_root / "package.json"

    @property
    def package_lock_path(self) -> Path:
        return self._bridge_root / "package-lock.json"

    @property
    def node_modules_path(self) -> Path:
        return self._bridge_root / "node_modules"

    @property
    def node_dependency_state_path(self) -> Path:
        return self._state_dir / "node_dependencies.json"

    @property
    def bridge_process_cwd(self) -> Path:
        return self._project_root if self.uses_embedded_bridge else self._bridge_root

    @property
    def bridge_data_dir(self) -> Path:
        return self.runtime_settings_path.parent

    @property
    def uses_embedded_bridge(self) -> bool:
        with contextlib.suppress(OSError):
            return self._bridge_root.resolve() == self._default_bridge_root.resolve()
        return False

    def exists(self) -> bool:
        return self._bridge_root.exists() and self.entrypoint_path.exists() and self.package_json_path.exists()

    def load_state(self) -> dict[str, Any]:
        payload = _read_json_file(self.state_path, default={})
        if not isinstance(payload, dict):
            payload = {}
        return {
            "version": int(payload.get("version") or _STATE_VERSION),
            "enabled": bool(payload.get("enabled", False)),
            "pid": int(payload.get("pid") or 0) or None,
            "last_started_at": _safe_text(payload.get("last_started_at")),
            "last_stopped_at": _safe_text(payload.get("last_stopped_at")),
            "last_error": _safe_text(payload.get("last_error")),
            "log_path": _safe_text(payload.get("log_path")) or str(self.log_path),
        }

    def save_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = {
            "version": _STATE_VERSION,
            "enabled": bool(payload.get("enabled", False)),
            "pid": int(payload.get("pid") or 0) or None,
            "last_started_at": _safe_text(payload.get("last_started_at")),
            "last_stopped_at": _safe_text(payload.get("last_stopped_at")),
            "last_error": _safe_text(payload.get("last_error")),
            "log_path": _safe_text(payload.get("log_path")) or str(self.log_path),
        }
        tmp_path = Path(str(self.state_path) + ".tmp")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.state_path)
        return state

    def load_env(self) -> dict[str, str]:
        if not self.env_path.exists():
            return {}
        env: dict[str, str] = {}
        try:
            lines = self.env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        for line in lines:
            match = _ENV_LINE_RE.match(line)
            if not match:
                continue
            env[match.group(1)] = _parse_env_value(match.group(2))
        return env

    def _migrate_legacy_secret_store(self) -> None:
        with contextlib.suppress(Exception):
            if self._legacy_secret_root.resolve() == Path(self._secret_store.storage_info.path).parent.resolve():
                return
        legacy_store = _secret_store_cls()(self._legacy_secret_root)
        for field in SECRET_FIELDS:
            profile = self._secret_profile(field)
            if self._secret_store.get(profile):
                continue
            legacy_value = legacy_store.get(profile)
            if not legacy_value:
                continue
            self._secret_store.set(
                profile,
                legacy_value,
                persist=legacy_store.is_persisted(profile),
            )

    def _migrate_legacy_external_bridge_layout(self) -> None:
        if not self.uses_embedded_bridge:
            return
        with contextlib.suppress(OSError):
            if self._legacy_external_bridge_root.resolve() == self._bridge_root.resolve():
                return
        if not self._legacy_external_bridge_root.exists():
            return

        legacy_env_path = self._legacy_external_bridge_root / ".env"
        if legacy_env_path.exists() and not self.env_path.exists():
            self.env_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_env_path, self.env_path)

        legacy_data_dir = self._legacy_external_bridge_root / "data"
        if not legacy_data_dir.exists():
            return

        self.bridge_data_dir.mkdir(parents=True, exist_ok=True)
        for child in legacy_data_dir.iterdir():
            target = self.bridge_data_dir / child.name
            if target.exists():
                continue
            try:
                if child.is_dir():
                    shutil.copytree(child, target)
                else:
                    shutil.copy2(child, target)
            except OSError:
                continue

    def _update_env_file(self, updates: dict[str, Any]) -> dict[str, str]:
        existing_lines: list[str]
        if self.env_path.exists():
            existing_lines = self.env_path.read_text(encoding="utf-8").splitlines()
        else:
            self.env_path.parent.mkdir(parents=True, exist_ok=True)
            existing_lines = []
        env_updates = {ENV_FIELD_MAP[key]: value for key, value in updates.items() if key in ENV_FIELD_MAP}
        rewritten: list[str] = []
        seen_keys: set[str] = set()
        for raw_line in existing_lines:
            match = _ENV_LINE_RE.match(raw_line)
            if not match:
                rewritten.append(raw_line)
                continue
            env_key = match.group(1)
            if env_key not in env_updates:
                rewritten.append(raw_line)
                continue
            if env_updates[env_key] is not None:
                rewritten.append(f"{env_key}={_format_env_value(env_updates[env_key])}")
            seen_keys.add(env_key)
        for env_key, value in env_updates.items():
            if env_key in seen_keys:
                continue
            if value is None:
                continue
            rewritten.append(f"{env_key}={_format_env_value(value)}")
        body = "\n".join(rewritten).strip()
        if body:
            self.env_path.write_text(body + "\n", encoding="utf-8")
        elif self.env_path.exists():
            self.env_path.unlink()
        return self.load_env()

    def _secret_profile(self, field: str) -> str:
        return _SECRET_PROFILE_MAP[field]

    def _get_secret(self, field: str) -> str:
        return _safe_text(self._secret_store.get(self._secret_profile(field)))

    def _set_secret(self, field: str, value: Any) -> None:
        text = _safe_text(value)
        if not text:
            self._secret_store.clear(self._secret_profile(field))
            return
        self._secret_store.set(self._secret_profile(field), text, persist=True)

    def migrate_plaintext_secrets(self) -> bool:
        env = self.load_env()
        file_updates: dict[str, Any] = {}
        changed = False
        for field in SECRET_FIELDS:
            env_key = ENV_FIELD_MAP[field]
            plain = _safe_text(env.get(env_key))
            if not plain:
                continue
            if not self._get_secret(field):
                self._set_secret(field, plain)
                changed = True
            file_updates[field] = None
        if file_updates:
            self._update_env_file(file_updates)
            changed = True
        return changed

    def load_effective_env(self) -> dict[str, str]:
        self.migrate_plaintext_secrets()
        env = self.load_env()
        for field in SECRET_FIELDS:
            secret = self._get_secret(field)
            if secret:
                env[ENV_FIELD_MAP[field]] = secret
        return env

    def update_env(self, updates: dict[str, Any]) -> dict[str, str]:
        file_updates: dict[str, Any] = {}
        for key, value in (updates or {}).items():
            if key not in ENV_FIELD_MAP:
                continue
            if key in SECRET_FIELDS:
                text = _safe_text(value)
                if text:
                    self._set_secret(key, text)
                elif value is None:
                    self._set_secret(key, None)
                file_updates[key] = None
                continue
            file_updates[key] = value
        for field in SECRET_FIELDS:
            if self._get_secret(field):
                file_updates[field] = None
        if file_updates:
            self._update_env_file(file_updates)
        return self.load_effective_env()

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        state = self.load_state()
        state["enabled"] = bool(enabled)
        if not enabled:
            state["last_stopped_at"] = _now_utc_iso()
        return self.save_state(state)

    def runtime_settings(self) -> dict[str, Any]:
        payload = _read_json_file(self.runtime_settings_path, default={})
        candidate = payload if isinstance(payload, dict) else {}
        defaults = self.runtime_settings_defaults()
        return {
            "requireMention": _parse_bool(
                candidate.get("requireMention"),
                default=bool(defaults["requireMention"]),
            ),
            "voiceRequireWakeWord": _parse_bool(
                candidate.get("voiceRequireWakeWord"),
                default=bool(defaults["voiceRequireWakeWord"]),
            ),
            "voiceWakeWords": _normalize_string_list(candidate.get("voiceWakeWords"))
            or list(defaults["voiceWakeWords"]),
            "voiceMediaVolume": _clamp_int(
                candidate.get("voiceMediaVolume"),
                default=int(defaults["voiceMediaVolume"]),
                minimum=0,
                maximum=200,
            ),
            "voiceProfile": _safe_text(candidate.get("voiceProfile")) or defaults["voiceProfile"],
            "accessGrants": candidate.get("accessGrants") if isinstance(candidate.get("accessGrants"), dict) else {},
        }

    def runtime_settings_defaults(self) -> dict[str, Any]:
        env = self.load_effective_env()
        tts_backend = _safe_text(env.get("DISCORD_VOICE_TTS_BACKEND")).lower() or "piper"
        stt_backend = _safe_text(env.get("DISCORD_VOICE_STT_BACKEND")).lower() or "faster-whisper"
        return {
            "requireMention": _parse_bool(env.get("DISCORD_REQUIRE_MENTION"), default=True),
            "voiceRequireWakeWord": _parse_bool(env.get("DISCORD_VOICE_REQUIRE_WAKE_WORD"), default=True),
            "voiceWakeWords": _normalize_string_list(env.get("DISCORD_VOICE_WAKE_WORDS"))
            or list(_DEFAULT_VOICE_WAKE_WORDS),
            "voiceMediaVolume": _clamp_int(env.get("DISCORD_VOICE_MEDIA_VOLUME"), default=100, minimum=0, maximum=200),
            "voiceProfile": _safe_text(env.get("DISCORD_VOICE_PROFILE")) or "",
            "voiceTtsBackend": tts_backend,
            "voiceTtsModel": _safe_text(env.get("DISCORD_VOICE_TTS_MODEL"))
            or ("gpt-4o-mini-tts" if tts_backend == "openai" else "en_US-ryan-high"),
            "voiceCloudVoice": _safe_text(env.get("DISCORD_VOICE_CLOUD_VOICE")) or "alloy",
            "voiceSilenceMs": _clamp_int(env.get("DISCORD_VOICE_SILENCE_MS"), default=700, minimum=200, maximum=5000),
            "voiceMinSpeechMs": _clamp_int(
                env.get("DISCORD_VOICE_MIN_SPEECH_MS"),
                default=400,
                minimum=100,
                maximum=10000,
            ),
            "voiceMaxSpeechMs": _clamp_int(
                env.get("DISCORD_VOICE_MAX_SPEECH_MS"),
                default=20000,
                minimum=500,
                maximum=120000,
            ),
            "voiceWakeCaptureMs": _clamp_int(
                env.get("DISCORD_VOICE_WAKE_CAPTURE_MS"),
                default=6500,
                minimum=500,
                maximum=30000,
            ),
            "voiceNoWakeCooldownMs": _clamp_int(
                env.get("DISCORD_VOICE_NO_WAKE_COOLDOWN_MS"),
                default=8000,
                minimum=0,
                maximum=60000,
            ),
            "voiceMaxReplyChars": _clamp_int(
                env.get("DISCORD_VOICE_MAX_REPLY_CHARS"),
                default=320,
                minimum=40,
                maximum=600,
            ),
            "voiceTtsSentencePauseMs": _clamp_int(
                env.get("DISCORD_VOICE_TTS_SENTENCE_PAUSE_MS"),
                default=140,
                minimum=0,
                maximum=1000,
            ),
            "voiceTtsLengthScale": _safe_text(env.get("DISCORD_VOICE_TTS_LENGTH_SCALE")),
            "voiceSttBackend": stt_backend,
            "voiceSttModel": _safe_text(env.get("DISCORD_VOICE_STT_MODEL"))
            or ("gpt-4o-transcribe" if stt_backend == "openai" else "distil-large-v3"),
            "voiceSttDevice": _safe_text(env.get("DISCORD_VOICE_STT_DEVICE")) or "cpu",
            "voiceSttComputeType": _safe_text(env.get("DISCORD_VOICE_STT_COMPUTE_TYPE")) or "int8",
            "voiceSttBeamSize": _clamp_int(env.get("DISCORD_VOICE_STT_BEAM_SIZE"), default=5, minimum=1, maximum=10),
            "voiceSttVadFilter": _parse_bool(env.get("DISCORD_VOICE_STT_VAD_FILTER"), default=True),
            "voiceSttVadMinSilenceMs": _clamp_int(
                env.get("DISCORD_VOICE_STT_VAD_MIN_SILENCE_MS"),
                default=500,
                minimum=100,
                maximum=5000,
            ),
            "voiceSttLanguage": _safe_text(env.get("DISCORD_VOICE_STT_LANGUAGE")) or "en",
            "voiceSttPrompt": _safe_text(env.get("DISCORD_VOICE_STT_PROMPT")),
            "voiceSttHintPhrases": _normalize_string_list(env.get("DISCORD_VOICE_STT_HINT_PHRASES")),
        }

    def update_runtime_settings(self, updates: dict[str, Any], *, restart_if_running: bool = True) -> dict[str, Any]:
        current = self.runtime_settings()
        normalized_updates = dict(updates or {})
        if "require_mention" not in normalized_updates and "requireMention" in normalized_updates:
            normalized_updates["require_mention"] = normalized_updates.get("requireMention")
        if "voice_require_wake_word" not in normalized_updates and "voiceRequireWakeWord" in normalized_updates:
            normalized_updates["voice_require_wake_word"] = normalized_updates.get("voiceRequireWakeWord")
        if "voice_wake_words" not in normalized_updates and "voiceWakeWords" in normalized_updates:
            normalized_updates["voice_wake_words"] = normalized_updates.get("voiceWakeWords")
        if "voice_media_volume" not in normalized_updates and "voiceMediaVolume" in normalized_updates:
            normalized_updates["voice_media_volume"] = normalized_updates.get("voiceMediaVolume")
        if "voice_profile" not in normalized_updates and "voiceProfile" in normalized_updates:
            normalized_updates["voice_profile"] = normalized_updates.get("voiceProfile")
        next_settings = {
            "requireMention": bool(current.get("requireMention", True)),
            "voiceRequireWakeWord": bool(current.get("voiceRequireWakeWord", True)),
            "voiceWakeWords": list(current.get("voiceWakeWords") or list(_DEFAULT_VOICE_WAKE_WORDS)),
            "voiceMediaVolume": _clamp_int(current.get("voiceMediaVolume"), default=100, minimum=0, maximum=200),
            "voiceProfile": _safe_text(current.get("voiceProfile")),
            "accessGrants": dict(current.get("accessGrants") or {}),
        }
        if "require_mention" in normalized_updates:
            next_settings["requireMention"] = _parse_bool(
                normalized_updates.get("require_mention"),
                default=bool(next_settings["requireMention"]),
            )
        if "voice_require_wake_word" in normalized_updates:
            next_settings["voiceRequireWakeWord"] = _parse_bool(
                normalized_updates.get("voice_require_wake_word"),
                default=bool(next_settings["voiceRequireWakeWord"]),
            )
        if "voice_wake_words" in normalized_updates:
            next_settings["voiceWakeWords"] = _normalize_string_list(normalized_updates.get("voice_wake_words")) or list(
                next_settings["voiceWakeWords"] or list(_DEFAULT_VOICE_WAKE_WORDS)
            )
        if "voice_media_volume" in normalized_updates:
            next_settings["voiceMediaVolume"] = _clamp_int(
                normalized_updates.get("voice_media_volume"),
                default=int(next_settings["voiceMediaVolume"]),
                minimum=0,
                maximum=200,
            )
        if "voice_profile" in normalized_updates:
            next_settings["voiceProfile"] = _safe_text(normalized_updates.get("voice_profile"))
        _write_json_file(self.runtime_settings_path, next_settings)
        restarted = False
        if restart_if_running and self._probe_process(self.load_state().get("pid")) is not None:
            self.restart()
            restarted = True
        return {
            "settings": next_settings,
            "restarted": restarted,
        }

    def session_versions(self) -> dict[str, int]:
        payload = _read_json_file(self.sessions_path, default={})
        if not isinstance(payload, dict):
            return {}
        versions = payload.get("versions")
        if not isinstance(versions, dict):
            return {}
        output: dict[str, int] = {}
        for scope_key, version in versions.items():
            try:
                output[_safe_text(scope_key)] = int(version)
            except (TypeError, ValueError):
                continue
        return output

    def is_configured(self, env: dict[str, str] | None = None) -> bool:
        resolved = env or self.load_effective_env()
        return bool(
            _safe_text(resolved.get("DISCORD_BOT_TOKEN"))
            and _safe_text(resolved.get("THOMAS_BASE_URL"))
            and _normalize_csv(resolved.get("DISCORD_OWNER_USER_IDS"))
        )
