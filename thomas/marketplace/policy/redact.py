from __future__ import annotations

import re
from typing import Any

from thomas.core.redaction import DEFAULT_PATTERNS as CORE_DEFAULT_PATTERNS

DEFAULT_PATTERNS = CORE_DEFAULT_PATTERNS

_DEFAULT_MASK = "<REDACTED>"
_PRIVATE_KEY_MASK = "<REDACTED:PRIVATE_KEY>"
_BEARER_MASK = "<REDACTED:BEARER>"
_SECRET_KEY_MASK = "<REDACTED:SECRET_KEY>"

_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")
_BEARER_RE = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;\"']+)")
_SECRET_KEY_RE = re.compile(r"(?i)\bsk-[a-z0-9_-]{16,}\b")
_ASSIGNMENT_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([^\s,;\"']+)"),
    re.compile(r"(?i)(token\s*[=:]\s*)([^\s,;\"']+)"),
    re.compile(r"(?i)(secret\s*[=:]\s*)([^\s,;\"']+)"),
    re.compile(r"(?i)(password\s*[=:]\s*)([^\s,;\"']+)"),
)
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passphrase|authorization|cookie|session|private[_-]?key)"
)


class Redactor:
    """Policy redactor with typed placeholders for the guardrails layer."""

    def __init__(self, additional_patterns: list[str] | None = None) -> None:
        self._compiled_additional: list[re.Pattern[str]] = []
        for pattern in additional_patterns or []:
            try:
                self._compiled_additional.append(re.compile(str(pattern)))
            except re.error:
                continue

    def redact_text(self, text: str) -> str:
        out = str(text or "")
        out = _PRIVATE_KEY_RE.sub(_PRIVATE_KEY_MASK, out)
        out = _BEARER_RE.sub(r"\1" + _BEARER_MASK, out)
        out = _SECRET_KEY_RE.sub(_SECRET_KEY_MASK, out)
        for pat in _ASSIGNMENT_PATTERNS:
            out = pat.sub(r"\1" + _DEFAULT_MASK, out)
        for pat in self._compiled_additional:
            if pat.groups >= 2:
                out = pat.sub(r"\1" + _DEFAULT_MASK, out)
            else:
                out = pat.sub(_DEFAULT_MASK, out)
        return out

    def redact_obj(self, value: Any) -> Any:
        if isinstance(value, dict):
            red: dict[Any, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                if _SENSITIVE_KEY_RE.search(key_text):
                    red[key] = self._mask_for_value(key_text, item)
                else:
                    red[key] = self.redact_obj(item)
            return red
        if isinstance(value, list):
            return [self.redact_obj(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact_obj(item) for item in value)
        if isinstance(value, set):
            return {self.redact_obj(item) for item in value}
        if isinstance(value, str):
            return self.redact_text(value)
        return value

    def _mask_for_value(self, key: str, value: Any) -> str:
        key_norm = str(key or "").strip().lower()
        value_text = str(value or "")
        if "private" in key_norm and "key" in key_norm:
            return _PRIVATE_KEY_MASK
        if "authorization" in key_norm and value_text.lower().startswith("bearer "):
            return _BEARER_MASK
        if value_text.lower().startswith("sk-"):
            return _SECRET_KEY_MASK
        return _DEFAULT_MASK


__all__ = ["DEFAULT_PATTERNS", "Redactor"]
