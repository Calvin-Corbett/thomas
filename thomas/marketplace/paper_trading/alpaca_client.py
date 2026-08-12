"""Broker clients for paper trading.

Two implementations share one duck-typed async interface:

* ``AlpacaPaperClient`` — talks to Alpaca's FREE paper API + FREE IEX market data.
  Every outbound URL is SSRF-checked and asserted to be a paper endpoint.
* ``SimBroker`` — a deterministic, offline simulator used when no credentials are
  configured, so the module (and its tests) work end-to-end without network.

``make_broker(config)`` returns the right one based on whether credentials exist.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from thomas.marketplace.paper_trading._exceptions import BrokerError
from thomas.marketplace.paper_trading._types import (
    AccountSnapshot,
    OrderType,
    PositionSnapshot,
    Quote,
    Side,
)
from thomas.marketplace.paper_trading.config import (
    ALLOWED_BROKER_HOSTS,
    PaperTradingConfig,
    assert_paper,
)

log = logging.getLogger(__name__)

_TIMEOUT_S = 20


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class AlpacaPaperClient:
    """Async client for Alpaca paper trading + IEX (free) market data."""

    def __init__(self, config: PaperTradingConfig) -> None:
        config.validate_paper()
        self._cfg = config
        self._headers = {
            "APCA-API-KEY-ID": config.key_id,
            "APCA-API-SECRET-KEY": config.secret_key,
            "accept": "application/json",
        }

    @property
    def is_simulated(self) -> bool:
        return False

    async def _request(
        self,
        method: str,
        base: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        import aiohttp

        url = f"{base}{path}"
        assert_paper(base)  # belt-and-suspenders: never call a non-paper base
        err = check_url_guard(url)
        if err:
            raise BrokerError(f"blocked outbound URL: {err}")
        try:
            timeout = aiohttp.ClientTimeout(total=_TIMEOUT_S)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method,
                    url,
                    headers=self._headers,
                    params=params,
                    json=json_body,
                ) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        raise BrokerError(f"Alpaca {method} {path} -> HTTP {resp.status}: {text[:300]}")
                    if not text:
                        return {}
                    return json.loads(text)
        except BrokerError:
            raise
        except Exception as exc:
            # Deliberately broad, logged, and re-raised as the module's own error.
            # This is the adapter boundary between an arbitrary HTTP/JSON transport
            # stack and BrokerError: aiohttp client faults, socket/TLS errors,
            # timeouts, decode failures and malformed JSON must ALL arrive at the
            # engine as one type, because the engine's fail-closed risk checks key
            # on BrokerError. Naming a narrow tuple here would let an unnamed
            # transport fault escape as itself and crash a live reconciliation
            # instead of blocking a proposal, so the catch stays broad.
            log.warning("Alpaca %s %s failed: %s", method, path, exc, exc_info=True)
            raise BrokerError(f"Alpaca request failed: {type(exc).__name__}: {exc}") from exc

    async def get_account(self) -> AccountSnapshot:
        data = await self._request("GET", self._cfg.paper_base_url, "/v2/account")
        return AccountSnapshot(
            equity=_f(data.get("equity")),
            cash=_f(data.get("cash")),
            buying_power=_f(data.get("buying_power")),
            currency=str(data.get("currency") or "USD"),
            status=str(data.get("status") or ""),
            pattern_day_trader=bool(data.get("pattern_day_trader")),
        )

    async def list_positions(self) -> list[PositionSnapshot]:
        data = await self._request("GET", self._cfg.paper_base_url, "/v2/positions")
        out: list[PositionSnapshot] = []
        if isinstance(data, list):
            for row in data:
                out.append(
                    PositionSnapshot(
                        symbol=str(row.get("symbol") or "").upper(),
                        qty=_f(row.get("qty")),
                        avg_entry_price=_f(row.get("avg_entry_price")),
                        current_price=_f(row.get("current_price")),
                        market_value=_f(row.get("market_value")),
                        unrealized_pl=_f(row.get("unrealized_pl")),
                        unrealized_plpc=_f(row.get("unrealized_plpc")) * 100.0,
                    )
                )
        return out

    async def is_market_open(self) -> bool:
        data = await self._request("GET", self._cfg.paper_base_url, "/v2/clock")
        return bool(data.get("is_open"))

    async def get_latest_quote(self, symbol: str) -> Quote:
        symbol = (symbol or "").upper().strip()
        path = f"/v2/stocks/{symbol}/quotes/latest"
        data = await self._request("GET", self._cfg.data_base_url, path, params={"feed": "iex"})
        q = data.get("quote") if isinstance(data, dict) else None
        q = q if isinstance(q, dict) else {}
        bid = _f(q.get("bp"))
        ask = _f(q.get("ap"))
        if bid > 0 and ask > 0:
            price = round((bid + ask) / 2.0, 4)
        else:
            price = ask or bid
        return Quote(
            symbol=symbol,
            price=price,
            bid=bid,
            ask=ask,
            as_of=str(q.get("t") or ""),
            feed="iex",
        )

    async def get_bars(self, symbol: str, *, timeframe: str = "1Day", limit: int = 30) -> list[dict[str, Any]]:
        symbol = (symbol or "").upper().strip()
        path = f"/v2/stocks/{symbol}/bars"
        data = await self._request(
            "GET",
            self._cfg.data_base_url,
            path,
            params={"timeframe": timeframe, "limit": int(limit), "feed": "iex"},
        )
        bars = data.get("bars") if isinstance(data, dict) else None
        return bars if isinstance(bars, list) else []

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float | None,
        notional: float | None,
        order_type: str,
        limit_price: float | None,
        time_in_force: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "symbol": (symbol or "").upper().strip(),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        if notional and notional > 0:
            body["notional"] = round(float(notional), 2)
        elif qty and qty > 0:
            body["qty"] = qty
        if order_type == OrderType.LIMIT.value and limit_price:
            body["limit_price"] = round(float(limit_price), 2)
        return await self._request("POST", self._cfg.paper_base_url, "/v2/orders", json_body=body)

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return await self._request("GET", self._cfg.paper_base_url, f"/v2/orders/{order_id}")


def check_url_guard(url: str) -> str | None:
    """Run Thomas's SSRF guard, pinned to the paper broker hosts.

    Defensive import so the module still loads if url_safety moves.
    """
    try:
        from thomas.tools.url_safety import check_url

        return check_url(url, allow_private=False, allowed_hosts=list(ALLOWED_BROKER_HOSTS))
    except ImportError:
        return None


class SimBroker:
    """Deterministic offline simulator. No network, no credentials.

    Prices are a stable function of the symbol (via SHA-1, so they're identical
    across processes — unlike the salted built-in ``hash``). Positions persist to
    a local sim file so the full propose -> submit -> score loop works offline.
    """

    def __init__(self, config: PaperTradingConfig) -> None:
        self._cfg = config
        self._positions_file = Path(config.data_dir) / "sim_positions.json"
        self._equity = 100_000.0

    @property
    def is_simulated(self) -> bool:
        return True

    def _price_for(self, symbol: str) -> float:
        digest = hashlib.sha1((symbol or "X").upper().encode()).hexdigest()
        return round(20.0 + (int(digest[:8], 16) % 38_000) / 100.0, 2)

    def _load_positions(self) -> list[dict[str, Any]]:
        if not self._positions_file.exists():
            return []
        try:
            data = json.loads(self._positions_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _save_positions(self, rows: list[dict[str, Any]]) -> None:
        self._positions_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._positions_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(rows, ensure_ascii=False, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._positions_file)

    async def get_account(self) -> AccountSnapshot:
        positions = await self.list_positions()
        invested = sum(p.market_value for p in positions)
        return AccountSnapshot(
            equity=round(self._equity + sum(p.unrealized_pl for p in positions), 2),
            cash=round(self._equity - invested, 2),
            buying_power=round((self._equity - invested) * 2, 2),
            currency="USD",
            status="ACTIVE (simulated)",
        )

    async def list_positions(self) -> list[PositionSnapshot]:
        out: list[PositionSnapshot] = []
        for row in self._load_positions():
            symbol = str(row.get("symbol") or "").upper()
            qty = _f(row.get("qty"))
            avg = _f(row.get("avg_entry_price"))
            price = self._price_for(symbol)
            out.append(
                PositionSnapshot(
                    symbol=symbol,
                    qty=qty,
                    avg_entry_price=avg,
                    current_price=price,
                    market_value=round(qty * price, 2),
                    unrealized_pl=round((price - avg) * qty, 2),
                    unrealized_plpc=round(((price - avg) / avg * 100.0) if avg else 0.0, 2),
                )
            )
        return out

    async def is_market_open(self) -> bool:
        return True

    async def get_latest_quote(self, symbol: str) -> Quote:
        symbol = (symbol or "").upper().strip()
        price = self._price_for(symbol)
        return Quote(
            symbol=symbol,
            price=price,
            bid=round(price * 0.999, 2),
            ask=round(price * 1.001, 2),
            feed="sim",
        )

    async def get_bars(self, symbol: str, *, timeframe: str = "1Day", limit: int = 30) -> list[dict[str, Any]]:
        price = self._price_for(symbol)
        # A flat, deterministic series — enough structure for analysis tools.
        return [
            {"t": f"sim-{i}", "o": price, "h": price, "l": price, "c": price, "v": 0}
            for i in range(min(int(limit), 30))
        ]

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float | None,
        notional: float | None,
        order_type: str,
        limit_price: float | None,
        time_in_force: str,
    ) -> dict[str, Any]:
        symbol = (symbol or "").upper().strip()
        price = float(limit_price) if order_type == OrderType.LIMIT.value and limit_price else self._price_for(symbol)
        fill_qty = float(qty) if qty else (float(notional) / price if notional else 0.0)
        rows = self._load_positions()
        existing = next((r for r in rows if r.get("symbol") == symbol), None)
        signed = fill_qty if side == Side.BUY.value else -fill_qty
        if existing:
            existing["qty"] = _f(existing.get("qty")) + signed
            existing["avg_entry_price"] = price
            rows = [r for r in rows if not (r.get("symbol") == symbol and _f(r.get("qty")) == 0)]
        elif signed != 0:
            rows.append({"symbol": symbol, "qty": signed, "avg_entry_price": price})
        self._save_positions(rows)
        from thomas.marketplace.paper_trading._types import new_id

        return {
            "id": new_id("simord"),
            "status": "filled",
            "filled_avg_price": price,
            "filled_qty": fill_qty,
            "symbol": symbol,
            "side": side,
            "simulated": True,
        }

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return {"id": order_id, "status": "filled", "simulated": True}


def make_broker(config: PaperTradingConfig):
    """Return the live paper client if credentials exist, else the simulator."""
    if config.has_credentials:
        return AlpacaPaperClient(config)
    return SimBroker(config)
