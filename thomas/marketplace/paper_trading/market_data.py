"""Free historical daily price data for the training simulator.

Source: Yahoo Finance's public chart endpoint (no API key, no signup). Fetched
once per symbol and cached on disk so the simulator works offline afterward and
never hammers the source. Daily bars only — enough for a training game.

This is read-only market data; it is SSRF-guarded and pinned to the Yahoo hosts.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
_USER_AGENT = "Mozilla/5.0 (Thomas PaperTrading Simulator)"
_CACHE_TTL_S = 24 * 3600  # refetch at most once a day


@dataclass
class Bar:
    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketDataError(Exception):
    """Raised when historical data cannot be fetched or parsed."""


def _cache_path(cache_dir: Path, symbol: str, rng: str) -> Path:
    safe = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-")
    return Path(cache_dir) / "market_cache" / f"{safe}_{rng}.json"


def _guard(url: str) -> str | None:
    try:
        from thomas.tools.url_safety import check_url

        return check_url(url, allow_private=False, allowed_hosts=list(_YAHOO_HOSTS))
    except ImportError:
        return None


def _fetch_yahoo(symbol: str, rng: str) -> list[Bar]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1d"
    err = _guard(url)
    if err:
        raise MarketDataError(f"blocked outbound URL: {err}")
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (host-pinned)
            payload = json.loads(resp.read().decode("utf-8"))
    # The whole urllib surface: URLError/HTTPError, socket timeouts and TLS
    # failures are OSError subclasses; a truncated or malformed response arrives
    # as http.client.HTTPException; a bad body decodes into UnicodeDecodeError or
    # json.JSONDecodeError, both ValueError subclasses. Every one of these is an
    # expected remote-data fault and has to reach the caller as MarketDataError.
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise MarketDataError(f"fetch failed for {symbol}: {type(exc).__name__}: {exc}") from exc

    try:
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
        q = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise MarketDataError(f"unexpected data shape for {symbol}: {exc}") from exc

    bars: list[Bar] = []
    for i, ts in enumerate(stamps):
        o, h, low, c, v = (q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i])
        # Yahoo emits nulls for holidays/partial bars — skip incomplete rows.
        if None in (o, h, low, c):
            continue
        bars.append(
            Bar(
                date=time.strftime("%Y-%m-%d", time.gmtime(ts)),
                open=round(float(o), 4),
                high=round(float(h), 4),
                low=round(float(low), 4),
                close=round(float(c), 4),
                volume=float(v or 0),
            )
        )
    if not bars:
        raise MarketDataError(f"no usable bars returned for {symbol}")
    return bars


def load_daily_bars(
    symbol: str,
    *,
    cache_dir: Path | str,
    rng: str = "5y",
    max_age_s: int = _CACHE_TTL_S,
    allow_fetch: bool = True,
) -> list[Bar]:
    """Return cached daily bars, fetching from Yahoo if missing/stale.

    If the cache is present and fresh, no network call is made (works offline).
    """
    symbol = (symbol or "").upper().strip()
    path = _cache_path(cache_dir, symbol, rng)
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < max_age_s or not allow_fetch:
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
                return [Bar(**r) for r in rows]
            except (OSError, json.JSONDecodeError, TypeError):
                pass  # fall through to refetch

    if not allow_fetch:
        raise MarketDataError(f"no cached data for {symbol} and fetch disabled")

    bars = _fetch_yahoo(symbol, rng)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([b.to_dict() for b in bars], ensure_ascii=False),
        encoding="utf-8",
    )
    return bars
