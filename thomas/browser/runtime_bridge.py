"""Bridge from browser contract modules to the live browser runtime.

The canonical runtime is ``thomas.tools.browser``.  Modules under
``thomas.browser`` should use this helper instead of guessing between legacy
browser package locations.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

CANONICAL_BROWSER_RUNTIME = "thomas.tools.browser"
CONTRACT_PACKAGE = "thomas.browser"


def import_browser_runtime() -> tuple[ModuleType | None, dict[str, Any]]:
    """Import the live browser runtime without making browser support mandatory."""

    try:
        return importlib.import_module(CANONICAL_BROWSER_RUNTIME), {
            "runtime": CANONICAL_BROWSER_RUNTIME,
            "available": True,
        }
    except Exception as exc:  # pragma: no cover - depends on optional browser deps
        return None, {
            "runtime": CANONICAL_BROWSER_RUNTIME,
            "available": False,
            "error": type(exc).__name__,
        }


def browser_runtime_status() -> dict[str, Any]:
    """Return a small diagnostic payload for CLI/status surfaces."""

    module, meta = import_browser_runtime()
    payload = dict(meta)
    payload["contract_package"] = CONTRACT_PACKAGE
    if module is not None:
        payload["module_file"] = str(getattr(module, "__file__", "") or "")
    return payload
