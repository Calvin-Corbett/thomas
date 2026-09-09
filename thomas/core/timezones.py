"""Safe timezone resolution for Thomas runtimes on every supported platform."""

from __future__ import annotations

import re
from datetime import tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_IANA_TIMEZONE = re.compile(r"^[A-Za-z][A-Za-z0-9._+-]*(?:/[A-Za-z0-9._+-]+)*$")


def resolve_timezone(value: object) -> tzinfo:
    """Resolve an IANA timezone, including Windows installs without system tzdata."""
    name = str(value or "UTC").strip() or "UTC"
    if len(name) > 128 or not _IANA_TIMEZONE.fullmatch(name) or ".." in name.split("/"):
        raise ValueError(f"invalid timezone: {name}")

    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        # croniter already supplies python-dateutil. Its bundled IANA database is
        # the reliable fallback on Windows, where the stdlib has no zone files.
        try:
            from dateutil.tz import gettz
        except ImportError as exc:  # pragma: no cover - dependency installation failure
            raise ValueError(f"invalid timezone: {name}") from exc
        zone = gettz(name)
        if zone is None:
            raise ValueError(f"invalid timezone: {name}")
        return zone
