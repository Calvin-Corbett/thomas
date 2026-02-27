# thomas/observability/redaction.py
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DEFAULT_PLACEHOLDER = "[REDACTED]"

DEFAULT_SENSITIVE_KEYS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "client_secret",
    "password",
    "passphrase",
    "private_key",
    "ssh_key",
    "openai_api_key",
    "anthropic_api_key",
    "google_api_key",
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_session_token",
}

DEFAULT_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
]


def _load_extra_patterns_from_env() -> list[re.Pattern[str]]:
    raw = os.getenv("THOMAS_REDACTION_REGEXES", "").strip()
    if not raw:
        return []
    try:
        arr = json.loads(raw)
        if not isinstance(arr, list):
            return []
        out: list[re.Pattern[str]] = []
        for s in arr:
            if isinstance(s, str) and s:
                try:
                    out.append(re.compile(s))
                except re.error:
                    pass
        return out
    except json.JSONDecodeError:
        return []


@dataclass(frozen=True)
class RedactionConfig:
    placeholder: str = DEFAULT_PLACEHOLDER
    sensitive_keys: set[str] | None = None
    patterns: list[re.Pattern[str]] | None = None
    max_depth: int = 32
    max_string_len: int = 200_000

    @staticmethod
    def default() -> RedactionConfig:
        extra = _load_extra_patterns_from_env()
        return RedactionConfig(
            placeholder=DEFAULT_PLACEHOLDER,
            sensitive_keys=set(DEFAULT_SENSITIVE_KEYS),
            patterns=[*DEFAULT_SECRET_PATTERNS, *extra],
        )


def _is_sensitive_key(key: str, cfg: RedactionConfig) -> bool:
    try:
        return key.strip().lower() in (cfg.sensitive_keys or set())
    except Exception:  # REVIEWED: broad catch
        return False


def redact_string(s: str, cfg: RedactionConfig) -> str:
    if not s:
        return s
    if len(s) > cfg.max_string_len:
        s = s[: cfg.max_string_len] + "…(truncated)"
    out = s
    for pat in cfg.patterns or []:
        out = pat.sub(cfg.placeholder, out)
    return out


def redact_obj(obj: Any, cfg: RedactionConfig | None = None, _depth: int = 0) -> Any:
    if cfg is None:
        cfg = RedactionConfig.default()
    if _depth > cfg.max_depth:
        return cfg.placeholder

    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return redact_string(obj, cfg)

    if isinstance(obj, Mapping):
        out = {}
        for k, v in obj.items():
            ks = str(k)
            if _is_sensitive_key(ks, cfg):
                out[ks] = cfg.placeholder
            else:
                out[ks] = redact_obj(v, cfg, _depth=_depth + 1)
        return out

    if isinstance(obj, (list, tuple, set)):
        return [redact_obj(v, cfg, _depth=_depth + 1) for v in obj]

    try:
        return redact_string(str(obj), cfg)
    except (ValueError, TypeError):
        return cfg.placeholder
