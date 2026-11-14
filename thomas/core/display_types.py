"""Which kinds of block the chat feed may draw with their own renderer, and which it shows as plain words.

The display kernel (``thomas/server/web/js/display_kernel.js``) draws each part of a reply by its type. This file keeps
the types you switched off, in ``display_types.json`` in the data folder, so the choice survives a restart. A type that is
not listed is on. A read never raises: a missing or unreadable file means every type is on, and says so once in the log.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from thomas.core.atomic_json import read_text_with_retry, write_json_atomic
from thomas.core.config import resolve_thomas_data_dir

log = logging.getLogger(__name__)

FILE_NAME = "display_types.json"
TYPE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")

_warned_for: str | None = None


def types_path() -> Path:
    """Where the list lives: ``display_types.json`` in the data folder, worked out on every call."""
    return resolve_thomas_data_dir() / FILE_NAME


def valid_type(name: Any) -> bool:
    """True for a block type name: lowercase letters, digits, ``_`` and ``-``, starting with a letter."""
    return isinstance(name, str) and TYPE_NAME.match(name) is not None


def disabled() -> list[str]:
    """The block types switched off, sorted. Never raises."""
    global _warned_for
    path = types_path()
    try:
        if not path.is_file():
            return []
        data = json.loads(read_text_with_retry(path))
        if not isinstance(data, dict) or not isinstance(data.get("disabled"), list):
            raise ValueError("the file does not hold a list of disabled types")
        _warned_for = None
        return sorted({name for name in data["disabled"] if valid_type(name)})
    except (OSError, ValueError) as exc:
        if _warned_for != str(path):
            _warned_for = str(path)
            log.warning("Display types file %s cannot be read, so every block type is on: %s", path, exc)
        return []


def set_enabled(name: str, enabled: bool) -> list[str]:
    """Switch one block type on or off and return the new list of those off. Raises ``ValueError`` for a bad name."""
    if not valid_type(name):
        raise ValueError("a block type is lowercase letters, digits, _ and -, starting with a letter")
    off = set(disabled())
    if enabled:
        off.discard(name)
    else:
        off.add(name)
    result = sorted(off)
    write_json_atomic(types_path(), {"disabled": result})
    return result
