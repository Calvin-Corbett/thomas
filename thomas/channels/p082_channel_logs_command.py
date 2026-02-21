"""Channel log inspection (P082).

Implements the domain logic for the `thomas channels logs` CLI subcommand.

Design goals:
- Efficient tailing from the end of the log file.
- Best-effort parsing (JSON lines or plaintext).
- Deterministic errors (stable `code` and `details`).
"""

from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


# ---------------------------
# Contracts
# ---------------------------


@dataclass(frozen=True)
class ChannelLogsRequest:
    """Input contract for channel log retrieval."""

    channel: str = "all"
    lines: int = 200
    # Optional explicit log file path override.
    log_file: Path | None = None


@dataclass(frozen=True)
class ChannelLogEntry:
    """One log record (raw + optional parsed JSON)."""

    raw: str
    parsed: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ChannelLogsResult:
    """Output contract for channel log retrieval."""

    channel: str
    log_file: str
    lines_requested: int
    entries: list[ChannelLogEntry]

    @property
    def lines_returned(self) -> int:
        return len(self.entries)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "ok": True,
            "channel": self.channel,
            "log_file": self.log_file,
            "lines_requested": self.lines_requested,
            "lines_returned": self.lines_returned,
            "entries": [
                {
                    "raw": e.raw,
                    "parsed": dict(e.parsed) if e.parsed is not None else None,
                }
                for e in self.entries
            ],
        }


# ---------------------------
# Errors
# ---------------------------


class ChannelLogsError(RuntimeError):
    """Base exception for deterministic failures in channel log retrieval."""

    code: str = "channel_logs_error"

    def __init__(self, message: str, *, details: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.details: dict[str, Any] = dict(details or {})


class InvalidInputError(ChannelLogsError):
    code = "invalid_input"


class MissingConfigError(ChannelLogsError):
    code = "missing_config"


class ExternalFailureError(ChannelLogsError):
    code = "external_failure"


# ---------------------------
# Public API
# ---------------------------


def get_channel_logs(
    request: ChannelLogsRequest,
    *,
    config: Mapping[str, Any] | None = None,
) -> ChannelLogsResult:
    """Fetch recent channel logs.

    This tails the log file from the end and returns the last N *matching*
    channel-related records, optionally filtered by provider.

    Raises:
        InvalidInputError, MissingConfigError, ExternalFailureError
    """

    channel = (request.channel or "").strip()
    if not channel:
        raise InvalidInputError("channel must be a non-empty string")

    if not isinstance(request.lines, int):
        raise InvalidInputError("lines must be an integer")

    if request.lines <= 0:
        raise InvalidInputError("lines must be > 0")

    # Keep bounded for automation safety.
    if request.lines > 10_000:
        raise InvalidInputError("lines must be <= 10000")

    log_path = _resolve_log_file(request.log_file, config=config)
    channel_norm = channel.lower()

    try:
        entries = _tail_channel_entries(
            log_path,
            limit=request.lines,
            channel_norm=channel_norm,
        )
    except FileNotFoundError as e:
        raise MissingConfigError(
            "log file not found",
            details={"log_file": str(log_path)},
        ) from e
    except OSError as e:
        raise ExternalFailureError(
            "failed to read log file",
            details={"log_file": str(log_path), "os_error": str(e)},
        ) from e

    return ChannelLogsResult(
        channel=channel,
        log_file=str(log_path),
        lines_requested=request.lines,
        entries=entries,
    )


# ---------------------------
# Internals: log discovery
# ---------------------------


_ENV_LOG_KEYS = (
    "THOMAS_LOG_FILE",
    "THOMAS_GATEWAY_LOG_FILE",
    "THOMAS_LOG_PATH",
)


def _resolve_log_file(
    explicit: Path | None,
    *,
    config: Mapping[str, Any] | None,
) -> Path:
    # 0) Explicit override.
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.exists():
            raise MissingConfigError("log file does not exist", details={"log_file": str(path)})
        if not path.is_file():
            raise InvalidInputError("log_file must be a file", details={"log_file": str(path)})
        return path

    # 1) Environment variable overrides (file or directory).
    for key in _ENV_LOG_KEYS:
        env_val = os.environ.get(key)
        if not env_val:
            continue

        p = Path(env_val).expanduser()
        if p.exists() and p.is_file():
            return p
        if p.exists() and p.is_dir():
            newest = _newest_log_in_dir(p)
            if newest is not None:
                return newest

    # 2) Explicit config mapping passed in.
    path_from_config = _log_path_from_mapping(config) if config is not None else None
    if path_from_config:
        p = Path(path_from_config).expanduser()
        if p.exists() and p.is_file():
            return p
        if p.exists() and p.is_dir():
            newest = _newest_log_in_dir(p)
            if newest is not None:
                return newest

    # 3) Best-effort config files.
    for cfg_path in _candidate_config_paths():
        maybe = _log_path_from_config_file(cfg_path)
        if not maybe:
            continue
        p = Path(maybe).expanduser()
        if p.exists() and p.is_file():
            return p
        if p.exists() and p.is_dir():
            newest = _newest_log_in_dir(p)
            if newest is not None:
                return newest

    # 4) Conventional log directories (newest file wins).
    for d in _candidate_log_dirs():
        newest = _newest_log_in_dir(d)
        if newest is not None:
            return newest

    raise MissingConfigError(
        "unable to locate gateway log file",
        details={
            "env_keys": list(_ENV_LOG_KEYS),
            "config_paths": [str(p) for p in _candidate_config_paths()],
            "log_dirs": [str(p) for p in _candidate_log_dirs()],
        },
    )


def _candidate_config_paths() -> list[Path]:
    paths: list[Path] = [
        Path.home() / ".thomas" / "thomas.json",
        Path.home() / ".thomas" / "config.json",
    ]
    # Windows friendly.
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "thomas" / "config.json")
    return paths


def _candidate_log_dirs() -> list[Path]:
    dirs: list[Path] = []

    # Linux/macOS conventional.
    dirs.append(Path("/tmp/thomas"))
    dirs.append(Path.home() / ".thomas" / "logs")

    # TEMP directories (cross-platform).
    temp = os.environ.get("TEMP") or os.environ.get("TMPDIR") or os.environ.get("TMP")
    if temp:
        dirs.append(Path(temp) / "thomas")

    # Windows LOCALAPPDATA
    localapp = os.environ.get("LOCALAPPDATA")
    if localapp:
        dirs.append(Path(localapp) / "thomas" / "logs")

    # Deduplicate while preserving order.
    out: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        key = str(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _newest_log_in_dir(d: Path) -> Path | None:
    try:
        if not d.exists() or not d.is_dir():
            return None
        candidates: list[Path] = []
        for pat in ("*.log", "*.jsonl", "*.txt"):
            candidates.extend(list(d.glob(pat)))
        candidates = [p for p in candidates if p.exists() and p.is_file()]
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]
    except Exception:
        return None


def _log_path_from_mapping(mapping: Mapping[str, Any] | None) -> str | None:
    if not mapping:
        return None

    direct = _first_str(mapping, "log_file", "logFile", "logging.file")
    if direct:
        return direct

    # nested lookup
    for path in (
        ("logging", "file"),
        ("gateway", "logging", "file"),
        ("gateway", "log", "file"),
        ("runtime", "logging", "file"),
    ):
        cur: Any = mapping
        ok = True
        for key in path:
            if isinstance(cur, Mapping) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and isinstance(cur, str) and cur.strip():
            return cur.strip()

    return None


def _log_path_from_config_file(config_path: Path) -> str | None:
    try:
        if not config_path.exists() or not config_path.is_file():
            return None
        text = config_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(text)
        if isinstance(data, Mapping):
            return _log_path_from_mapping(data)
        return None
    except Exception:
        # Best-effort; do not raise.
        return None


# ---------------------------
# Internals: tail + filtering
# ---------------------------


# Safety: don't scan beyond this unless we really must; big logs can be huge.
_MAX_SCAN_BYTES = 256 * 1024 * 1024  # 256 MiB
_CHUNK_SIZE = 64 * 1024  # 64 KiB


def _tail_channel_entries(path: Path, *, limit: int, channel_norm: str) -> list[ChannelLogEntry]:
    """Read the last `limit` matching channel entries, in chronological order."""

    # We'll scan from the end and keep the last N matches in reverse, then reverse at end.
    matches: list[ChannelLogEntry] = []

    size = path.stat().st_size
    pos = size
    buf = b""
    scanned = 0

    with path.open("rb") as f:
        while pos > 0 and len(matches) < limit and scanned < _MAX_SCAN_BYTES:
            read_size = _CHUNK_SIZE if pos >= _CHUNK_SIZE else pos
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
            scanned += len(chunk)

            # Prepend new chunk (we're moving backwards).
            buf = chunk + buf
            parts = buf.split(b"\n")

            # Keep the first part as a possibly-partial line for the next iteration.
            buf = parts[0]

            # Process complete lines in reverse order.
            for lb in reversed(parts[1:]):
                if not lb:
                    continue
                line = lb.decode("utf-8", errors="replace").rstrip("\r")
                if not line:
                    continue

                parsed = _maybe_parse_json(line)

                if not _is_channel_related(line, parsed):
                    continue

                if channel_norm != "all" and not _matches_channel(channel_norm, line, parsed):
                    continue

                matches.append(ChannelLogEntry(raw=line, parsed=parsed))
                if len(matches) >= limit:
                    break

        # If we reached the start of file, `buf` is the first line (possibly without newline).
        if pos == 0 and buf and len(matches) < limit:
            line = buf.decode("utf-8", errors="replace").rstrip("\r")
            if line:
                parsed = _maybe_parse_json(line)
                if _is_channel_related(line, parsed):
                    if channel_norm == "all" or _matches_channel(channel_norm, line, parsed):
                        matches.append(ChannelLogEntry(raw=line, parsed=parsed))

    matches.reverse()
    return matches


def _maybe_parse_json(line: str) -> Mapping[str, Any] | None:
    try:
        data = json.loads(line)
        return data if isinstance(data, Mapping) else None
    except Exception:
        return None


def _is_channel_related(raw: str, parsed: Mapping[str, Any] | None) -> bool:
    raw_l = raw.lower()

    if parsed:
        subsystem = _first_str(parsed, "subsystem", "logger", "name", "component", "module")
        if subsystem and "channels" in subsystem.lower():
            return True

        # Some loggers use a dedicated provider/channel field.
        for key in ("channel", "provider", "integration"):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                return True

        msg = _first_str(parsed, "msg", "message", "event")
        if msg and "channel" in msg.lower():
            return True

    return "channels/" in raw_l or raw_l.startswith("[channels") or "[channels/" in raw_l


def _matches_channel(channel_norm: str, raw: str, parsed: Mapping[str, Any] | None) -> bool:
    raw_l = raw.lower()

    if parsed:
        for key in ("channel", "provider", "integration"):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip().lower() == channel_norm:
                return True

        subsystem = _first_str(parsed, "subsystem", "logger", "name", "component", "module")
        if subsystem and channel_norm in subsystem.lower():
            return True

        msg = _first_str(parsed, "msg", "message", "event")
        if msg and channel_norm in msg.lower():
            return True

    return channel_norm in raw_l


def _first_str(mapping: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key in mapping and isinstance(mapping[key], str) and mapping[key].strip():
            return mapping[key].strip()
    return None
