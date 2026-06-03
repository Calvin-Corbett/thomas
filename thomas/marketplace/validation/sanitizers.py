"""
Input sanitization and cleaning.
"""

import html
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Complete, case-insensitive patterns for stripping <script>/<style> blocks.
# The tag body uses an unambiguous alternation (quoted attribute value | single
# non-">" char) so attribute values containing ">" are consumed without
# catastrophic backtracking, and the closing tag tolerates attributes/whitespace.
_TAG_BODY = r'(?:"[^"]*"|\'[^\']*\'|[^>])*'
_SCRIPT_BLOCK_RE = re.compile(
    rf"<script{_TAG_BODY}>[\s\S]*?</script{_TAG_BODY}>",
    re.IGNORECASE,
)
_STYLE_BLOCK_RE = re.compile(
    rf"<style{_TAG_BODY}>[\s\S]*?</style{_TAG_BODY}>",
    re.IGNORECASE,
)


@dataclass
class SanitizerConfig:
    """Configuration for input sanitization."""

    strip_html: bool = True
    """If True, remove HTML tags."""

    escape_html: bool = False
    """If True, escape HTML special characters."""

    remove_null_bytes: bool = True
    """If True, remove null bytes."""

    trim_whitespace: bool = True
    """If True, trim leading/trailing whitespace."""

    collapse_whitespace: bool = False
    """If True, collapse multiple whitespace to single space."""

    normalize_unicode: bool = False
    """If True, normalize unicode (NFC form)."""

    escape_sql_patterns: bool = False
    """If True, escape SQL injection patterns."""

    max_length: int | None = None
    """Maximum string length (truncate if exceeded)."""

    truncate_suffix: str = "..."
    """Suffix when truncating."""

    lowercase: bool = False
    """If True, convert to lowercase."""

    uppercase: bool = False
    """If True, convert to uppercase."""

    remove_special_chars: bool = False
    """If True, remove special characters."""

    allowed_special_chars: str = ""
    """Special characters to keep when remove_special_chars=True."""

    mask_sensitive: bool = False
    """If True, mask sensitive fields (emails, phones, SSN)."""

    sensitive_patterns: dict[str, str] = field(default_factory=dict)
    """Custom regex patterns to mask."""

    custom_sanitizers: dict[str, Callable[[str], str]] = field(default_factory=dict)
    """Custom sanitization functions by field name."""


class InputSanitizer:
    """Input sanitization engine."""

    # Common sensitive patterns
    EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    PHONE_PATTERN = re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")
    SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    CREDIT_CARD_PATTERN = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")

    def __init__(self, config: SanitizerConfig | None = None) -> None:
        """Initialize sanitizer.

        Args:
            config: SanitizerConfig instance.
        """
        self.config = config or SanitizerConfig()

    def sanitize(self, value: Any, field_name: str = "") -> Any:
        """Sanitize a value.

        Args:
            value: Value to sanitize.
            field_name: Field name (used for custom/sensitive handling).

        Returns:
            Sanitized value.
        """
        if not isinstance(value, str):
            return value

        result = value

        # Custom sanitizer
        if field_name and field_name in self.config.custom_sanitizers:
            return self.config.custom_sanitizers[field_name](result)

        # Mask sensitive
        if self.config.mask_sensitive:
            result = self._mask_sensitive(result)

        # Custom patterns
        for pattern_name, mask_pattern in self.config.sensitive_patterns.items():
            result = re.sub(mask_pattern, "***", result)

        # Trim whitespace
        if self.config.trim_whitespace:
            result = result.strip()

        # Collapse whitespace
        if self.config.collapse_whitespace:
            result = re.sub(r"\s+", " ", result)

        # Remove null bytes
        if self.config.remove_null_bytes:
            result = result.replace("\x00", "")

        # Normalize unicode
        if self.config.normalize_unicode:
            result = unicodedata.normalize("NFC", result)

        # Strip HTML
        if self.config.strip_html:
            result = self._strip_html(result)

        # Escape HTML
        if self.config.escape_html:
            result = html.escape(result)

        # Escape SQL patterns
        if self.config.escape_sql_patterns:
            result = self._escape_sql_patterns(result)

        # Remove special chars
        if self.config.remove_special_chars:
            result = self._remove_special_chars(result)

        # Case conversion
        if self.config.lowercase:
            result = result.lower()
        elif self.config.uppercase:
            result = result.upper()

        # Truncate
        if self.config.max_length and len(result) > self.config.max_length:
            truncate_at = self.config.max_length - len(self.config.truncate_suffix)
            result = result[: max(0, truncate_at)] + self.config.truncate_suffix

        return result

    def sanitize_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Sanitize all string values in dict.

        Args:
            data: Dictionary with values.

        Returns:
            Dictionary with sanitized values.
        """
        result = {}
        for field_name, value in data.items():
            result[field_name] = self.sanitize(value, field_name)
        return result

    def sanitize_list(self, items: list[Any]) -> list[Any]:
        """Sanitize all strings in list.

        Args:
            items: List of values.

        Returns:
            List with sanitized values.
        """
        return [self.sanitize(item) if isinstance(item, str) else item for item in items]

    def _strip_html(self, value: str) -> str:
        """Remove HTML tags."""
        # Remove script and style tags with content. Use complete, case-insensitive
        # patterns that consume attribute values containing ">" and tolerate
        # attributes/whitespace in the closing tag, so variants like <SCRIPT> or
        # </script > cannot bypass the filter.
        value = re.sub(_SCRIPT_BLOCK_RE, "", value)
        value = re.sub(_STYLE_BLOCK_RE, "", value)

        # Remove HTML comments (also matching the "--!>" terminator variant)
        value = re.sub(r"<!--[\s\S]*?--!?>", "", value)

        # Remove remaining tags
        value = re.sub(r"<[^>]+>", "", value)

        # Decode HTML entities
        value = html.unescape(value)

        return value

    def _escape_sql_patterns(self, value: str) -> str:
        """Escape SQL injection patterns."""
        # Escape single quotes
        value = value.replace("'", "''")

        # Escape backslashes (Windows)
        value = value.replace("\\", "\\\\")

        # Remove dangerous SQL keywords (basic)
        dangerous = ["DROP", "DELETE", "INSERT", "UPDATE", "CREATE", "ALTER", "EXEC", "EXECUTE", "UNION", "SELECT"]
        for keyword in dangerous:
            pattern = re.compile(rf"\b{keyword}\b", re.IGNORECASE)
            value = pattern.sub("", value)

        return value

    def _remove_special_chars(self, value: str) -> str:
        """Remove special characters."""
        if self.config.allowed_special_chars:
            # Keep alphanumeric + spaces + allowed
            pattern = f"[^a-zA-Z0-9\\s{re.escape(self.config.allowed_special_chars)}]"
        else:
            # Keep only alphanumeric and spaces
            pattern = r"[^a-zA-Z0-9\s]"

        return re.sub(pattern, "", value)

    def _mask_sensitive(self, value: str) -> str:
        """Mask sensitive information."""
        result = value

        # Mask emails
        def mask_email(match: re.Match) -> str:
            email = match.group(0)
            local, domain = email.rsplit("@", 1)
            masked_local = local[0] + "*" * (len(local) - 2) + local[-1] if len(local) > 2 else "*"
            return f"{masked_local}@{domain}"

        result = self.EMAIL_PATTERN.sub(mask_email, result)

        # Mask phones
        result = re.sub(self.PHONE_PATTERN, "***-****", result)

        # Mask SSN
        result = re.sub(self.SSN_PATTERN, "***-**-****", result)

        # Mask credit cards
        def mask_cc(match: str) -> str:
            cc = "".join(c for c in match if c.isdigit())
            return "*" * max(0, len(cc) - 4) + cc[-4:] if len(cc) >= 4 else "****"

        result = re.sub(self.CREDIT_CARD_PATTERN, mask_cc, result)

        return result

    def set_custom_sanitizer(self, field_name: str, func: Callable[[str], str]) -> None:
        """Register custom sanitizer for field.

        Args:
            field_name: Field name.
            func: Sanitization function.
        """
        self.config.custom_sanitizers[field_name] = func

    def add_sensitive_pattern(self, name: str, pattern: str, mask: str = "***") -> None:
        """Add custom sensitive pattern.

        Args:
            name: Pattern name.
            pattern: Regex pattern.
            mask: Replacement mask.
        """
        self.config.sensitive_patterns[name] = pattern
