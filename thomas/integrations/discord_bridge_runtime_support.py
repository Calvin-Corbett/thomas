"""Support constants and helpers for the Discord bridge runtime."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")
_PATH_ENV_KEY = "THOMAS_DISCORD_BRIDGE_ROOT"
_SHARED_SECRET_STORE_ENV_KEY = "THOMAS_SHARED_SECRET_STORE_DIR"
_STATE_VERSION = 1
_STATUS_RUNNING = "running"
_STATUS_STOPPED = "stopped"
_STATUS_UNCONFIGURED = "unconfigured"
_STATUS_MISSING = "missing"
_WINDOWS_PROCESS_QUERY_TIMEOUT_S = 4.0
_WINDOWS_STOP_POLL_INTERVAL_S = 0.1
_WINDOWS_STOP_POLL_ATTEMPTS = 10
_HISTORY_RESULT_LIMIT_MAX = 100
_VOICE_PROBE_TIMEOUT_S = 240.0
_NODE_INSTALL_TIMEOUT_S = 300.0
_DEFAULT_VOICE_WAKE_WORDS = ("thomas", "hey thomas")
_SECRET_PROFILE_MAP = {
    "bot_token": "channels.discord.bot_token",
    "thomas_api_token": "channels.discord.thomas_api_token",
}

ENV_FIELD_MAP: dict[str, str] = {
    "bot_token": "DISCORD_BOT_TOKEN",
    "guild_id": "DISCORD_GUILD_ID",
    "allowed_guild_ids": "DISCORD_ALLOWED_GUILD_IDS",
    "auto_channel_ids": "DISCORD_AUTO_CHANNEL_IDS",
    "owner_user_ids": "DISCORD_OWNER_USER_IDS",
    "owner_only_mode": "DISCORD_OWNER_ONLY_MODE",
    "require_mention": "DISCORD_REQUIRE_MENTION",
    "default_voice_channel_name": "DISCORD_DEFAULT_VOICE_CHANNEL_NAME",
    "voice_tts_backend": "DISCORD_VOICE_TTS_BACKEND",
    "voice_tts_model": "DISCORD_VOICE_TTS_MODEL",
    "voice_cloud_voice": "DISCORD_VOICE_CLOUD_VOICE",
    "voice_silence_ms": "DISCORD_VOICE_SILENCE_MS",
    "voice_min_speech_ms": "DISCORD_VOICE_MIN_SPEECH_MS",
    "voice_max_speech_ms": "DISCORD_VOICE_MAX_SPEECH_MS",
    "voice_wake_capture_ms": "DISCORD_VOICE_WAKE_CAPTURE_MS",
    "voice_no_wake_cooldown_ms": "DISCORD_VOICE_NO_WAKE_COOLDOWN_MS",
    "voice_max_reply_chars": "DISCORD_VOICE_MAX_REPLY_CHARS",
    "thomas_base_url": "THOMAS_BASE_URL",
    "thomas_api_token": "THOMAS_SERVER_API_TOKEN",
    "session_prefix": "SESSION_PREFIX",
    "voice_stt_backend": "DISCORD_VOICE_STT_BACKEND",
    "voice_stt_model": "DISCORD_VOICE_STT_MODEL",
    "voice_stt_device": "DISCORD_VOICE_STT_DEVICE",
    "voice_stt_compute_type": "DISCORD_VOICE_STT_COMPUTE_TYPE",
    "voice_stt_beam_size": "DISCORD_VOICE_STT_BEAM_SIZE",
    "voice_stt_vad_filter": "DISCORD_VOICE_STT_VAD_FILTER",
    "voice_stt_vad_min_silence_ms": "DISCORD_VOICE_STT_VAD_MIN_SILENCE_MS",
    "voice_stt_language": "DISCORD_VOICE_STT_LANGUAGE",
    "voice_stt_prompt": "DISCORD_VOICE_STT_PROMPT",
    "voice_stt_hint_phrases": "DISCORD_VOICE_STT_HINT_PHRASES",
    "voice_tts_use_cuda": "DISCORD_VOICE_TTS_USE_CUDA",
    "voice_tts_sentence_pause_ms": "DISCORD_VOICE_TTS_SENTENCE_PAUSE_MS",
    "voice_tts_length_scale": "DISCORD_VOICE_TTS_LENGTH_SCALE",
}

SECRET_FIELDS = {"bot_token", "thomas_api_token"}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _mask_secret(value: str) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    if len(text) <= 4:
        return "*" * len(text)
    return ("*" * max(0, len(text) - 4)) + text[-4:]


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    if not text:
        return bool(default)
    return text in {"1", "true", "yes", "on", "enabled"}


def _normalize_csv(value: Any) -> list[str]:
    items = [_safe_text(item) for item in str(value or "").replace("\r", "\n").replace("\n", ",").split(",")]
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list | tuple | set):
        items = [_safe_text(item) for item in value]
        deduped: list[str] = []
        seen: set[str] = set()
        for item in items:
            if not item or item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped
    return _normalize_csv(value)


def _read_json_file(path: Path, default: Any) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default
    return payload if isinstance(payload, type(default)) else default


def _write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(str(path) + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _parse_json_line(text: str) -> dict[str, Any] | None:
    candidate = _safe_text(text)
    if not candidate:
        return None
    with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            return payload
    return None


def _format_env_value(value: Any) -> str:
    if isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = _safe_text(value)
    if not text:
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_./:\\-]+", text):
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _default_shared_secret_root() -> Path:
    override = _safe_text(os.environ.get(_SHARED_SECRET_STORE_ENV_KEY))
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        local_app_data = _safe_text(os.environ.get("LOCALAPPDATA"))
        base = Path(local_app_data).expanduser() if local_app_data else (Path.home() / "AppData" / "Local")
        return base / "Thomas" / "shared"
    if os.name == "posix" and os.uname().sysname.lower() == "darwin":  # type: ignore[attr-defined]
        return Path.home() / "Library" / "Application Support" / "Thomas" / "shared"
    xdg_data_home = _safe_text(os.environ.get("XDG_DATA_HOME"))
    base = Path(xdg_data_home).expanduser() if xdg_data_home else (Path.home() / ".local" / "share")
    return base / "thomas" / "shared"


def _parse_env_value(raw_value: str) -> str:
    text = raw_value.strip()
    if not text:
        return ""
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        inner = text[1:-1]
        return bytes(inner, "utf-8").decode("unicode_escape")
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1]
    hash_index = text.find("#")
    if hash_index >= 0:
        text = text[:hash_index].rstrip()
    return text


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _default_embedded_bridge_root() -> Path:
    return Path(__file__).resolve().parent / "discord_bridge_service"


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _package_manifest_hash(package_json_path: Path, package_lock_path: Path) -> str:
    digest = hashlib.sha256()
    for path in (package_json_path, package_lock_path):
        if not path.exists():
            continue
        with contextlib.suppress(OSError):
            digest.update(path.read_bytes())
    return digest.hexdigest()
