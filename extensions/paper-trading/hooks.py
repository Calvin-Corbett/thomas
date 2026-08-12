from __future__ import annotations

from typing import Any

PACK_ID = "paper-trading"
MODULE_NAME = "paper_trading"
MODE = "paper_trading"


def before_tool(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault("extension_pack", PACK_ID)
    data.setdefault("mode", MODE)
    data.setdefault("validated", True)
    return data


def after_tool(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault("extension_pack", PACK_ID)
    data.setdefault("mode", MODE)
    data.setdefault("post_processed", True)
    return data


def healthcheck() -> dict[str, Any]:
    """Report pack health. Confirms the domain module imports and is paper-locked."""
    try:
        from thomas.marketplace.paper_trading._exceptions import PaperTradingError
        from thomas.marketplace.paper_trading.config import (
            PAPER_TRADING_BASE_URL,
            assert_paper,
        )
    # The import IS half the check. A missing/uninstalled domain module raises
    # ImportError, a renamed symbol AttributeError, and a package __init__ that
    # reads env/files on import can raise OSError or RuntimeError. All four mean
    # "pack not healthy", which is exactly what this function reports.
    except (AttributeError, ImportError, OSError, RuntimeError) as exc:  # pragma: no cover - defensive
        return {"ok": False, "pack": PACK_ID, "error": f"{type(exc).__name__}: {exc}"}

    try:
        assert_paper(PAPER_TRADING_BASE_URL)
    # assert_paper raises LiveTradingBlocked (a PaperTradingError) when the
    # configured broker URL is not a paper endpoint -- the failure this check
    # exists to report. A non-string URL from a broken config surfaces as
    # AttributeError/TypeError from the string handling inside it.
    except (AttributeError, PaperTradingError, TypeError) as exc:  # pragma: no cover - defensive
        return {"ok": False, "pack": PACK_ID, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "pack": PACK_ID, "paper_only": True}
