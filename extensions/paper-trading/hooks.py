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
        from thomas.marketplace.paper_trading.config import (
            PAPER_TRADING_BASE_URL,
            assert_paper,
        )

        assert_paper(PAPER_TRADING_BASE_URL)
        return {"ok": True, "pack": PACK_ID, "paper_only": True}
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "pack": PACK_ID, "error": f"{type(exc).__name__}: {exc}"}
