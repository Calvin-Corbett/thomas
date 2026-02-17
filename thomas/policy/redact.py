from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, MutableSequence, Sequence, Tuple, Union

_REDACT = "<REDACTED>"
_SENSITIVE_KEY_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|pwd|authorization|auth)")

# Token / key / secret patterns. Intentionally broad: false positives are preferable to leaks.
DEFAULT_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # PEM private keys and similar blobs
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.M), "<REDACTED:PRIVATE_KEY>"),
    # Authorization: Bearer ...
    (re.compile(r"(?im)^(authorization\s*:\s*bearer)\s+[^\s]+", re.M), r"\1 <REDACTED:BEARER>"),
    # Generic header-ish: X-Api-Key: ...
    (re.compile(r"(?im)^([\w-]*api[\w-]*key\s*:\s*)([^\s]+)", re.M), r"\1<REDACTED:API_KEY>"),
    # AWS access keys
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<REDACTED:AWS_ACCESS_KEY>"),
    (re.compile(r"\bASIA[0-9A-Z]{16}\b"), "<REDACTED:AWS_ACCESS_KEY>"),
    # JWT (three base64url-ish segments)
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"), "<REDACTED:JWT>"),
    # Slack tokens
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "<REDACTED:SLACK_TOKEN>"),
    # Common key prefixes (OpenAI, etc.) - broad
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "<REDACTED:SECRET_KEY>"),
    # Generic assignments: api_key=..., token: "...", secret = '...'
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|pwd)\b\s*([=:])\s*(['\"]?)[^\s'\"\n]{6,}(['\"]?)"), lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{_REDACT}{m.group(4)}"),
    # Emails
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "<REDACTED:EMAIL>"),
    # SSN (US) naive
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<REDACTED:SSN>"),
    # Credit card-ish (very rough)
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "<REDACTED:CARD>"),
    # Long hex strings
    (re.compile(r"\b[a-f0-9]{32,}\b", re.I), "<REDACTED:HEX>"),
]

@dataclass
class Redactor:
    additional_patterns: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._compiled: List[Tuple[re.Pattern, Union[str, object]]] = list(DEFAULT_PATTERNS)
        for pat in self.additional_patterns:
            try:
                self._compiled.append((re.compile(pat), _REDACT))
            except re.error:
                # ignore invalid custom patterns
                pass

    def redact_text(self, text: str) -> str:
        if not text:
            return text
        out = text
        for rx, repl in self._compiled:
            if callable(repl):
                out = rx.sub(repl, out)
            else:
                out = rx.sub(repl, out)
        return out

    def redact_obj(self, obj: Any) -> Any:
        """Recursively redact secrets/PII from arbitrary JSON-like payloads."""
        if obj is None:
            return None
        if isinstance(obj, str):
            return self.redact_text(obj)
        if isinstance(obj, (int, float, bool)):
            return obj
        if isinstance(obj, Mapping):
            # preserve mapping type where possible
            new: Dict[Any, Any] = {}
            for k, v in obj.items():
                nk = self.redact_text(k) if isinstance(k, str) else k
                if isinstance(k, str) and _SENSITIVE_KEY_RE.search(k):
                    # Key names like "password"/"token" should redact value even if
                    # value is short or does not match text patterns. Keep specific
                    # pattern-based labels when available (e.g. SECRET_KEY).
                    if v is None:
                        new[nk] = None
                    else:
                        rv = self.redact_obj(v)
                        if isinstance(rv, str) and isinstance(v, str) and rv != v:
                            new[nk] = rv
                        else:
                            new[nk] = _REDACT
                else:
                    new[nk] = self.redact_obj(v)
            return new
        if isinstance(obj, (list, tuple, set)):
            seq = [self.redact_obj(v) for v in obj]
            if isinstance(obj, tuple):
                return tuple(seq)
            if isinstance(obj, set):
                return set(seq)
            return seq
        # fallback: stringify and redact
        try:
            s = str(obj)
        except Exception:
            return "<REDACTED:UNSERIALIZABLE>"
        return self.redact_text(s)
