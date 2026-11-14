"""Model ids each provider listed on its last check, for layers below the catalog.

Build (thomas/forge) may not import thomas.models, so the catalog publishes here
and Build asks here whether a Claude id it has never seen is a real one.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable

_LOCK = threading.Lock()
_LISTED: dict[str, frozenset[str]] = {}


def publish(family: str, model_ids: Iterable[str]) -> None:
    ids = frozenset(str(m).strip().lower() for m in model_ids if str(m).strip())
    with _LOCK:
        _LISTED[str(family or "").strip().lower()] = ids


def listed(family: str) -> frozenset[str]:
    with _LOCK:
        return _LISTED.get(str(family or "").strip().lower(), frozenset())
