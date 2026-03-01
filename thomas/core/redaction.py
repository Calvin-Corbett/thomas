"""Lightweight structured/text redaction helpers for logs and JSON output."""

from __future__ import annotations

import re
from typing import Any

DEFAULT_PATTERNS: tuple[str, ...] = (
    r"(?i)(api[_-]?key\s*[=:]\s*)([^\s,;\"']+)",
    r"(?i)(token\s*[=:]\s*)([^\s,;\"']+)",
    r"(?i)(secret\s*[=:]\s*)([^\s,;\"']+)",
    r"(?i)(password\s*[=:]\s*)([^\s,;\"']+)",
    r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;\"']+)",
    r"(?i)(sk-[a-z0-9_-]{16,})",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
)

_MASK = "[REDACTED]"
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passphrase|authorization|cookie|session|private[_-]?key)"
)


class Redactor:
    """Redact likely secret values from text and JSON-like objects."""

    def __init__(self, additional_patterns: list[str] | None = None) -> None:
        raw_patterns = list(DEFAULT_PATTERNS)
        if additional_patterns:
            raw_patterns.extend(str(p) for p in additional_patterns if str(p or "").strip())
        self._compiled: list[re.Pattern[str]] = []
        for pattern in raw_patterns:
            try:
                self._compiled.append(re.compile(pattern))
            except re.error:
                continue

    def redact_text(self, text: str) -> str:
        out = str(text or "")
        for pat in self._compiled:
            if pat.groups >= 2:
                out = pat.sub(r"\1" + _MASK, out)
            else:
                out = pat.sub(_MASK, out)
        return out

    def redact_obj(self, value: Any) -> Any:
        if isinstance(value, dict):
            red: dict[Any, Any] = {}
            for k, v in value.items():
                key_str = str(k)
                if _SENSITIVE_KEY_RE.search(key_str):
                    red[k] = _MASK
                else:
                    red[k] = self.redact_obj(v)
            return red
        if isinstance(value, list):
            return [self.redact_obj(v) for v in value]
        if isinstance(value, tuple):
            return tuple(self.redact_obj(v) for v in value)
        if isinstance(value, set):
            return {self.redact_obj(v) for v in value}
        if isinstance(value, str):
            return self.redact_text(value)
        return value

