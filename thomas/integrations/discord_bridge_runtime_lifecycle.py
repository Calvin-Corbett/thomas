"""Lifecycle and process helpers for the Discord bridge runtime."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from thomas.integrations.discord_bridge_runtime_support import (
    _NODE_INSTALL_TIMEOUT_S,
    _PATH_ENV_KEY,
    _STATUS_MISSING,
    _STATUS_RUNNING,
    _STATUS_STOPPED,
    _STATUS_UNCONFIGURED,
    _VOICE_PROBE_TIMEOUT_S,
    _WINDOWS_PROCESS_QUERY_TIMEOUT_S,
    _WINDOWS_STOP_POLL_ATTEMPTS,
    _WINDOWS_STOP_POLL_INTERVAL_S,
    _clamp_int,
    _mask_secret,
    _normalize_csv,
    _normalize_string_list,
    _now_utc_iso,
    _package_manifest_hash,
    _parse_bool,
    _parse_json_line,
    _read_json_file,
    _safe_text,
    _write_json_file,
)


def _runtime_error_cls():
    from thomas.integrations.discord_bridge_runtime import DiscordBridgeRuntimeError

    return DiscordBridgeRuntimeError


def _runtime_module():
    import thomas.integrations.discord_bridge_runtime as runtime_module

    return runtime_module


class DiscordBridgeRuntimeLifecycleMixin:
    """Process, dependency, and status helpers."""

    _DISCORD_API_BASE_URL = "https://discord.com/api/v10"

    def _normalize_process_result(self, payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        pid = int(payload.get("ProcessId") or payload.get("processId") or 0)
        command_line = _safe_text(payload.get("CommandLine") or payload.get("commandLine"))
        if pid <= 0 or not command_line:
            return None
        return {
            "pid": pid,
            "command_line": command_line,
            "executable_path": _safe_text(payload.get("ExecutablePath") or payload.get("executablePath")),
        }

    def _probe_process(self, pid: int | None) -> dict[str, Any] | None:
        if not pid or pid <= 0:
            return None
        if os.name != "nt":
            return None
        runtime_module = _runtime_module()
        script = (
            f'$p = Get-CimInstance Win32_Process -Filter "ProcessId = {int(pid)}";'
            "if ($null -eq $p) { exit 0 } ;"
            "$p | Select-Object ProcessId, CommandLine, ExecutablePath | ConvertTo-Json -Compress"
        )
        try:
            result = runtime_module.subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    script,
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=_WINDOWS_PROCESS_QUERY_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        stdout = _safe_text(result.stdout)
        if not stdout:
            return None
        with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
            payload = json.loads(stdout)
            info = self._normalize_process_result(payload)
            if info and self._is_bridge_process(info.get("command_line")):
                return info
        return None

    def _is_bridge_process(self, command_line: Any) -> bool:
        command = _safe_text(command_line).replace("/", "\\").lower()
        entrypoint = str(self.entrypoint_path).replace("/", "\\").lower()
        return bool(entrypoint and entrypoint in command)

    def _tail_log(self, max_lines: int = 20) -> str:
        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(lines[-max_lines:]).strip()

    def _package_manifest_hash(self) -> str:
        return _package_manifest_hash(self.package_json_path, self.package_lock_path)

    def _node_dependency_marker_path(self) -> Path:
        return self.node_modules_path / "discord.js" / "package.json"

    def _node_dependencies_installed(self) -> bool:
        marker_path = self._node_dependency_marker_path()
        if not marker_path.exists():
            return False
        state = _read_json_file(self.node_dependency_state_path, default={})
        recorded_hash = _safe_text(state.get("lock_hash"))
        expected_hash = self._package_manifest_hash()
        return recorded_hash == expected_hash or not recorded_hash

    def _save_node_dependency_state(self) -> None:
        _write_json_file(
            self.node_dependency_state_path,
            {
                "lock_hash": self._package_manifest_hash(),
                "updated_at": _now_utc_iso(),
            },
        )

    def _find_node(self) -> str:
        return _safe_text(_runtime_module().shutil.which("node") or "")

    def _find_npm(self) -> str:
        runtime_module = _runtime_module()
        return _safe_text(runtime_module.shutil.which("npm.cmd") or runtime_module.shutil.which("npm") or "")

    def _discord_api_request(
        self,
        *,
        method: str,
        path: str,
        token: str,
        payload: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> tuple[int, Any]:
        body = None
        headers = {
            "Authorization": f"Bot {token}",
            "User-Agent": "ThomasDiscordBridgeRuntime/1.0",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib_request.Request(
            f"{self._DISCORD_API_BASE_URL}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib_request.urlopen(request, timeout=timeout) as response:
                raw_body = response.read().decode("utf-8", errors="replace")
                parsed_body: Any = None
                if raw_body:
                    with contextlib.suppress(json.JSONDecodeError):
                        parsed_body = json.loads(raw_body)
                    if parsed_body is None:
                        parsed_body = raw_body
                return int(getattr(response, "status", 200) or 200), parsed_body
        except urllib_error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            parsed_body = None
            if raw_body:
                with contextlib.suppress(json.JSONDecodeError):
                    parsed_body = json.loads(raw_body)
                if parsed_body is None:
                    parsed_body = raw_body
            return int(exc.code or 500), parsed_body

    def _configured_guild_ids(self, env: dict[str, str]) -> list[str]:
        guild_ids: list[str] = []
        seen: set[str] = set()
        candidates = [
            _safe_text(env.get("DISCORD_GUILD_ID")),
            *_normalize_csv(env.get("DISCORD_ALLOWED_GUILD_IDS")),
        ]
        for candidate in candidates:
            guild_id = _safe_text(candidate)
            if not guild_id or guild_id in seen:
                continue
            guild_ids.append(guild_id)
            seen.add(guild_id)
        return guild_ids

    def _disconnect_bot_voice_sessions(self, env: dict[str, str]) -> dict[str, Any]:
        token = _safe_text(env.get("DISCORD_BOT_TOKEN"))
        guild_ids = self._configured_guild_ids(env)
        result: dict[str, Any] = {
            "attempted": False,
            "bot_user_id": "",
            "guild_ids": guild_ids,
            "disconnected_guild_ids": [],
            "errors": [],
        }
        if not token or not guild_ids:
            return result

        result["attempted"] = True
        try:
            status_code, payload = self._discord_api_request(method="GET", path="/users/@me", token=token)
        except OSError as exc:
            result["errors"].append(f"bot lookup failed: {exc}")
            return result
        if status_code < 200 or status_code >= 300 or not isinstance(payload, dict):
            detail = _safe_text(payload.get("message")) if isinstance(payload, dict) else _safe_text(payload)
            result["errors"].append(f"bot lookup failed ({status_code}){f': {detail}' if detail else ''}")
            return result

        bot_user_id = _safe_text(payload.get("id"))
        result["bot_user_id"] = bot_user_id
        if not bot_user_id:
            result["errors"].append("bot lookup succeeded without returning a user id")
            return result

        for guild_id in guild_ids:
            try:
                status_code, payload = self._discord_api_request(
                    method="PATCH",
                    path=f"/guilds/{guild_id}/members/{bot_user_id}",
                    token=token,
                    payload={"channel_id": None},
                )
            except OSError as exc:
                result["errors"].append(f"{guild_id}: disconnect failed: {exc}")
                continue
            if 200 <= status_code < 300:
                result["disconnected_guild_ids"].append(guild_id)
                continue
            detail = _safe_text(payload.get("message")) if isinstance(payload, dict) else _safe_text(payload)
            result["errors"].append(f"{guild_id}: disconnect failed ({status_code}){f': {detail}' if detail else ''}")
        return result

    def ensure_node_dependencies(self) -> dict[str, Any]:
        runtime_error = _runtime_error_cls()
        runtime_module = _runtime_module()
        if not self.exists():
            raise runtime_error(f"Discord bridge root is missing: {self._bridge_root}")
        node = self._find_node()
        if not node:
            raise runtime_error("Could not find `node` on PATH.")
        npm = self._find_npm()
        if not npm:
            raise runtime_error("Could not find `npm` on PATH.")
        if self._node_dependencies_installed():
            return {"ready": True, "installed": False, "node": node, "npm": npm}

        args = [npm]
        if self.package_lock_path.exists():
            args.extend(["ci", "--no-audit", "--no-fund"])
        else:
            args.extend(["install", "--no-audit", "--no-fund"])
        result = runtime_module.subprocess.run(
            args,
            cwd=str(self._bridge_root),
            capture_output=True,
            check=False,
            text=True,
            timeout=_NODE_INSTALL_TIMEOUT_S,
        )
        if result.returncode != 0:
            details = _safe_text(result.stderr or result.stdout)
            raise runtime_error(details or f"Discord bridge dependency install failed with code {result.returncode}.")
        self._save_node_dependency_state()
        return {"ready": True, "installed": True, "node": node, "npm": npm}

    def _build_process_env(self, env: dict[str, str]) -> dict[str, str]:
        process_env = os.environ.copy()
        process_env.update({key: str(value) for key, value in env.items() if _safe_text(value)})
        process_env[_PATH_ENV_KEY] = str(self._bridge_root)
        process_env["THOMAS_PROJECT_ROOT"] = str(self._project_root)
        process_env["DISCORD_DATA_DIR"] = str(self.bridge_data_dir)
        process_env.setdefault("DISCORD_VOICE_TTS_PYTHON", sys.executable)
        process_env.setdefault("DISCORD_VOICE_STT_PYTHON", sys.executable)
        process_env.setdefault("DISCORD_MEDIA_PYTHON", sys.executable)
        process_env.setdefault("DISCORD_VOICE_TTS_DATA_DIR", str(self.bridge_data_dir / "piper-voices"))
        return process_env

    def start(self) -> dict[str, Any]:
        runtime_error = _runtime_error_cls()
        runtime_module = _runtime_module()
        if not self.exists():
            raise runtime_error(f"Discord bridge root is missing: {self._bridge_root}")
        env = self.load_effective_env()
        if not self.is_configured(env):
            raise runtime_error("Discord bridge is not configured yet.")
        running = self._probe_process(self.load_state().get("pid"))
        if running:
            state = self.load_state()
            state["pid"] = running["pid"]
            state["last_error"] = ""
            self.save_state(state)
            return self.status()
        with contextlib.suppress(Exception):
            self._disconnect_bot_voice_sessions(env)
        install_result = self.ensure_node_dependencies()
        node = _safe_text(install_result.get("node"))
        if not node:
            raise runtime_error("Could not find `node` on PATH.")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        process_env = self._build_process_env(env)
        with self.log_path.open("ab") as log_handle:
            creationflags = 0
            for flag_name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NO_WINDOW"):
                creationflags |= int(getattr(runtime_module.subprocess, flag_name, 0) or 0)
            process = runtime_module.subprocess.Popen(
                [node, str(self.entrypoint_path)],
                cwd=str(self.bridge_process_cwd),
                stdin=runtime_module.subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env=process_env,
                creationflags=creationflags,
                close_fds=False,
            )
        exit_code = None
        start_deadline = time.monotonic() + 2.0
        while time.monotonic() < start_deadline:
            exit_code = process.poll()
            if exit_code is not None:
                break
            if self._probe_process(int(process.pid or 0) or None) is not None:
                break
            time.sleep(0.2)
        if exit_code is None:
            exit_code = process.poll()
        state = self.load_state()
        state.update(
            {
                "pid": int(process.pid or 0) or None,
                "last_started_at": _now_utc_iso(),
                "last_error": "",
                "log_path": str(self.log_path),
            }
        )
        if exit_code is not None:
            state["pid"] = None
            state["last_error"] = self._tail_log() or f"Discord bridge exited with code {exit_code}."
            self.save_state(state)
            raise runtime_error(state["last_error"])
        self.save_state(state)
        return self.status()

    def stop(self) -> dict[str, Any]:
        runtime_error = _runtime_error_cls()
        runtime_module = _runtime_module()
        state = self.load_state()
        env = self.load_effective_env()
        pid = state.get("pid")
        running = self._probe_process(pid)
        if not running:
            cleanup = self._disconnect_bot_voice_sessions(env)
            state["pid"] = None
            state["last_stopped_at"] = _now_utc_iso()
            state["last_error"] = (
                "; ".join(str(item) for item in cleanup.get("errors") or [])
                if cleanup.get("errors")
                else ""
            )
            self.save_state(state)
            return self.status()
        if os.name == "nt":
            result = runtime_module.subprocess.run(
                ["taskkill", "/PID", str(running["pid"]), "/T", "/F"],
                capture_output=True,
                check=False,
                text=True,
                timeout=10.0,
            )
            stderr_text = _safe_text(result.stderr or result.stdout)
        else:
            result = runtime_module.subprocess.run(
                ["kill", str(running["pid"])],
                capture_output=True,
                check=False,
                text=True,
                timeout=10.0,
            )
            stderr_text = _safe_text(result.stderr or result.stdout)
        remaining = self._probe_process(running["pid"])
        for _ in range(_WINDOWS_STOP_POLL_ATTEMPTS):
            if remaining is None:
                break
            time.sleep(_WINDOWS_STOP_POLL_INTERVAL_S)
            remaining = self._probe_process(running["pid"])
        if remaining is not None:
            state["last_error"] = stderr_text or "Discord bridge did not stop cleanly."
            self.save_state(state)
            raise runtime_error(state["last_error"])
        cleanup = self._disconnect_bot_voice_sessions(env)
        state["pid"] = None
        state["last_stopped_at"] = _now_utc_iso()
        if stderr_text and result.returncode not in {0, 128}:
            state["last_error"] = stderr_text
        elif cleanup.get("errors"):
            state["last_error"] = "; ".join(str(item) for item in cleanup["errors"])
        else:
            state["last_error"] = ""
        self.save_state(state)
        return self.status()

    def restart(self) -> dict[str, Any]:
        with contextlib.suppress(_runtime_error_cls()):
            self.stop()
        return self.start()

    def run_voice_probe(
        self,
        *,
        wake: str = "",
        ask: str = "",
        say: str = "",
        speaker_name: str = "Voice Probe",
        speaker_id: str = "",
        channel: str = "",
        keep_audio: bool = False,
        probe_backend: str = "windows",
    ) -> dict[str, Any]:
        runtime_error = _runtime_error_cls()
        runtime_module = _runtime_module()
        if not self.exists():
            raise runtime_error(f"Discord bridge root is missing: {self._bridge_root}")
        if not self.voice_probe_path.exists():
            raise runtime_error(f"Discord voice probe is missing: {self.voice_probe_path}")
        env = self.load_effective_env()
        if not self.is_configured(env):
            raise runtime_error("Discord bridge is not configured yet.")
        install_result = self.ensure_node_dependencies()
        node = _safe_text(install_result.get("node"))
        if not node:
            raise runtime_error("Could not find `node` on PATH.")

        state = self.load_state()
        was_running = self._probe_process(state.get("pid")) is not None
        if was_running:
            self.stop()

        process_env = self._build_process_env(env)
        args = [node, str(self.voice_probe_path), "--json"]
        wake_text = _safe_text(wake)
        ask_text = _safe_text(ask)
        say_text = _safe_text(say)
        if wake_text:
            args.extend(["--wake", wake_text])
        elif ask_text:
            args.extend(["--ask", ask_text])
        elif say_text:
            args.extend(["--say", say_text])
        if _safe_text(speaker_name):
            args.extend(["--speaker-name", _safe_text(speaker_name)])
        if _safe_text(speaker_id):
            args.extend(["--speaker-id", _safe_text(speaker_id)])
        if _safe_text(channel):
            args.extend(["--channel", _safe_text(channel)])
        if keep_audio:
            args.append("--keep-audio")
        if _safe_text(probe_backend):
            args.extend(["--probe-backend", _safe_text(probe_backend)])

        stderr_text = ""
        payload: dict[str, Any] | None = None
        restart_error = ""
        started_at = time.perf_counter()
        try:
            result = runtime_module.subprocess.run(
                args,
                cwd=str(self.bridge_process_cwd),
                capture_output=True,
                check=False,
                text=True,
                timeout=_VOICE_PROBE_TIMEOUT_S,
                env=process_env,
            )
            stdout_lines = result.stdout.splitlines()
            for raw_line in reversed(stdout_lines):
                payload = _parse_json_line(raw_line)
                if payload:
                    break
            stderr_text = _safe_text(result.stderr)
            if result.returncode != 0:
                raise runtime_error(
                    stderr_text
                    or _safe_text(result.stdout)
                    or f"Discord voice probe exited with code {result.returncode}."
                )
            if payload is None:
                raise runtime_error("Discord voice probe did not return JSON output.")
        finally:
            if was_running:
                with contextlib.suppress(_runtime_error_cls()):
                    self.start()
                restarted = self._probe_process(self.load_state().get("pid")) is not None
                if not restarted:
                    restart_error = self._tail_log() or "Discord bridge did not restart after the voice probe."
        return {
            "ok": True,
            "probe": payload,
            "bridge_was_running": was_running,
            "bridge_restart_error": restart_error,
            "stderr": stderr_text,
            "duration_ms": int((time.perf_counter() - started_at) * 1000),
        }

    def status(self) -> dict[str, Any]:
        env = self.load_effective_env()
        state = self.load_state()
        running = self._probe_process(state.get("pid"))
        if running is None and state.get("pid"):
            state["pid"] = None
            self.save_state(state)
        node_path = self._find_node()
        npm_path = self._find_npm()
        dependencies_ready = self._node_dependencies_installed()
        sessions = self.session_versions()
        indexed_sessions = self.list_sessions(limit=20)
        indexed_turns = len(self._iter_history_rows())
        runtime_settings = self.runtime_settings()
        defaults = self.runtime_settings_defaults()
        configured = self.is_configured(env)
        bridge_status = _STATUS_MISSING if not self.exists() else _STATUS_RUNNING if running else _STATUS_STOPPED
        if bridge_status == _STATUS_STOPPED and not configured:
            bridge_status = _STATUS_UNCONFIGURED
        return {
            "ok": self.exists(),
            "channel": "discord",
            "bridge": {
                "root_path": str(self._bridge_root),
                "embedded": self.uses_embedded_bridge,
                "data_path": str(self.bridge_data_dir),
                "env_path": str(self.env_path),
                "log_path": str(self.log_path),
                "configured": configured,
                "enabled": bool(state.get("enabled", False)),
                "running": running is not None,
                "status": bridge_status,
                "pid": int((running or {}).get("pid") or 0) or None,
                "node_path": node_path or None,
                "npm_path": npm_path or None,
                "dependencies_ready": dependencies_ready,
                "last_started_at": _safe_text(state.get("last_started_at")),
                "last_stopped_at": _safe_text(state.get("last_stopped_at")),
                "last_error": _safe_text(state.get("last_error")),
            },
            "config": {
                "bot_token_masked": _mask_secret(env.get("DISCORD_BOT_TOKEN", "")),
                "bot_token_stored": bool(self._get_secret("bot_token")),
                "guild_id": _safe_text(env.get("DISCORD_GUILD_ID")),
                "allowed_guild_ids": _normalize_csv(env.get("DISCORD_ALLOWED_GUILD_IDS")),
                "auto_channel_ids": _normalize_csv(env.get("DISCORD_AUTO_CHANNEL_IDS")),
                "owner_user_ids": _normalize_csv(env.get("DISCORD_OWNER_USER_IDS")),
                "owner_only_mode": _parse_bool(env.get("DISCORD_OWNER_ONLY_MODE"), default=False),
                "require_mention": _parse_bool(env.get("DISCORD_REQUIRE_MENTION"), default=True),
                "default_voice_channel_name": _safe_text(env.get("DISCORD_DEFAULT_VOICE_CHANNEL_NAME")),
                "thomas_base_url": _safe_text(env.get("THOMAS_BASE_URL") or "http://127.0.0.1:8899"),
                "thomas_api_token_masked": _mask_secret(env.get("THOMAS_SERVER_API_TOKEN", "")),
                "thomas_api_token_stored": bool(self._get_secret("thomas_api_token")),
                "session_prefix": _safe_text(env.get("SESSION_PREFIX") or "thomas-discord"),
                "voice_tts_backend": _safe_text(env.get("DISCORD_VOICE_TTS_BACKEND")) or "piper",
                "voice_tts_model": _safe_text(env.get("DISCORD_VOICE_TTS_MODEL")) or defaults["voiceTtsModel"],
                "voice_cloud_voice": _safe_text(env.get("DISCORD_VOICE_CLOUD_VOICE")) or defaults["voiceCloudVoice"],
                "voice_silence_ms": _clamp_int(
                    env.get("DISCORD_VOICE_SILENCE_MS"),
                    default=int(defaults["voiceSilenceMs"]),
                    minimum=200,
                    maximum=5000,
                ),
                "voice_min_speech_ms": _clamp_int(
                    env.get("DISCORD_VOICE_MIN_SPEECH_MS"),
                    default=int(defaults["voiceMinSpeechMs"]),
                    minimum=100,
                    maximum=10000,
                ),
                "voice_max_speech_ms": _clamp_int(
                    env.get("DISCORD_VOICE_MAX_SPEECH_MS"),
                    default=int(defaults["voiceMaxSpeechMs"]),
                    minimum=500,
                    maximum=120000,
                ),
                "voice_wake_capture_ms": _clamp_int(
                    env.get("DISCORD_VOICE_WAKE_CAPTURE_MS"),
                    default=int(defaults["voiceWakeCaptureMs"]),
                    minimum=500,
                    maximum=30000,
                ),
                "voice_no_wake_cooldown_ms": _clamp_int(
                    env.get("DISCORD_VOICE_NO_WAKE_COOLDOWN_MS"),
                    default=int(defaults["voiceNoWakeCooldownMs"]),
                    minimum=0,
                    maximum=60000,
                ),
                "voice_max_reply_chars": _clamp_int(
                    env.get("DISCORD_VOICE_MAX_REPLY_CHARS"),
                    default=int(defaults["voiceMaxReplyChars"]),
                    minimum=40,
                    maximum=600,
                ),
                "voice_tts_sentence_pause_ms": _clamp_int(
                    env.get("DISCORD_VOICE_TTS_SENTENCE_PAUSE_MS"),
                    default=int(defaults["voiceTtsSentencePauseMs"]),
                    minimum=0,
                    maximum=1000,
                ),
                "voice_tts_use_cuda": _parse_bool(env.get("DISCORD_VOICE_TTS_USE_CUDA"), default=False),
                "voice_tts_length_scale": _safe_text(env.get("DISCORD_VOICE_TTS_LENGTH_SCALE"))
                or _safe_text(defaults["voiceTtsLengthScale"]),
                "voice_stt_backend": _safe_text(env.get("DISCORD_VOICE_STT_BACKEND")) or defaults["voiceSttBackend"],
                "voice_stt_model": _safe_text(env.get("DISCORD_VOICE_STT_MODEL")) or defaults["voiceSttModel"],
                "voice_stt_device": _safe_text(env.get("DISCORD_VOICE_STT_DEVICE")) or defaults["voiceSttDevice"],
                "voice_stt_compute_type": _safe_text(env.get("DISCORD_VOICE_STT_COMPUTE_TYPE"))
                or defaults["voiceSttComputeType"],
                "voice_stt_beam_size": _clamp_int(
                    env.get("DISCORD_VOICE_STT_BEAM_SIZE"),
                    default=int(defaults["voiceSttBeamSize"]),
                    minimum=1,
                    maximum=10,
                ),
                "voice_stt_vad_filter": _parse_bool(
                    env.get("DISCORD_VOICE_STT_VAD_FILTER"),
                    default=bool(defaults["voiceSttVadFilter"]),
                ),
                "voice_stt_vad_min_silence_ms": _clamp_int(
                    env.get("DISCORD_VOICE_STT_VAD_MIN_SILENCE_MS"),
                    default=int(defaults["voiceSttVadMinSilenceMs"]),
                    minimum=100,
                    maximum=5000,
                ),
                "voice_stt_language": _safe_text(env.get("DISCORD_VOICE_STT_LANGUAGE")) or defaults["voiceSttLanguage"],
                "voice_stt_prompt": _safe_text(env.get("DISCORD_VOICE_STT_PROMPT")) or defaults["voiceSttPrompt"],
                "voice_stt_hint_phrases": _normalize_string_list(env.get("DISCORD_VOICE_STT_HINT_PHRASES"))
                or list(defaults["voiceSttHintPhrases"]),
                "secret_storage": self._secret_store.storage_info.__dict__,
            },
            "runtime": {
                "require_mention": _parse_bool(runtime_settings.get("requireMention"), default=True),
                "voice_require_wake_word": _parse_bool(runtime_settings.get("voiceRequireWakeWord"), default=True),
                "voice_wake_words": list(runtime_settings.get("voiceWakeWords") or []),
                "voice_media_volume": int(runtime_settings.get("voiceMediaVolume") or 0),
                "voice_profile": _safe_text(runtime_settings.get("voiceProfile")),
                "access_grants_count": len(runtime_settings.get("accessGrants") or {}),
            },
            "conversations": {
                "tracked_bridge_sessions": len(sessions),
                "tracked_scope_keys": sorted(sessions.keys()),
                "indexed_turns": indexed_turns,
                "indexed_sessions": len(indexed_sessions),
                "recent_sessions": indexed_sessions[:8],
            },
        }
