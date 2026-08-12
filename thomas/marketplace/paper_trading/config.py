"""Configuration + safety constants for the paper-trading module.

Safety invariant (Phase 1): this module is PAPER-ONLY. The trading base URL is a
hardcoded constant pointing at Alpaca's paper endpoint, and ``assert_paper()``
rejects any URL that looks like the live (real-money) API. There is intentionally
no "live mode" flag — going live would be a deliberate, reviewed code change.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from thomas.marketplace.paper_trading._exceptions import LiveTradingBlocked
from thomas.marketplace.paper_trading._types import RiskRules

log = logging.getLogger(__name__)

# --- Locked endpoints -------------------------------------------------------
PAPER_TRADING_BASE_URL = "https://paper-api.alpaca.markets"
MARKET_DATA_BASE_URL = "https://data.alpaca.markets"

# Hosts the broker client is allowed to reach (SSRF allow-list).
ALLOWED_BROKER_HOSTS = ("paper-api.alpaca.markets", "data.alpaca.markets")

# A host that contains "api.alpaca.markets" but NOT "paper" is the live endpoint.
_LIVE_TRADING_HOST = "api.alpaca.markets"

_PLUGIN_RELATIVE = Path(".thomas") / "plugins" / "paper-trading"
_CREDENTIALS_FILE = "credentials.json"
_STATE_FILE = "state.json"


def assert_paper(url: str) -> None:
    """Raise LiveTradingBlocked if ``url`` is not an Alpaca *paper* endpoint.

    Allowed: paper-api.alpaca.markets (trading) and data.alpaca.markets (read-only
    market data). Anything pointing at the bare live trading host is blocked.
    """
    u = (url or "").strip().lower()
    if not u.startswith("https://"):
        raise LiveTradingBlocked(f"refusing non-HTTPS broker URL: {url!r}")
    host = u.split("://", 1)[1].split("/", 1)[0]
    if host == _LIVE_TRADING_HOST:
        raise LiveTradingBlocked("refusing the LIVE Alpaca trading endpoint — this module is paper-only")
    if host not in ALLOWED_BROKER_HOSTS:
        raise LiveTradingBlocked(f"broker host not in paper allow-list: {host!r}")


def _env(*names: str) -> str:
    for n in names:
        v = os.environ.get(n)
        if v and v.strip():
            return v.strip()
    return ""


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_data_dir(explicit: Path | str | None = None) -> Path:
    """Resolve the on-disk data dir, agreeing with the server's plugin path.

    Order: explicit arg -> THOMAS_PAPER_TRADING_DIR -> the loaded AppConfig's
    memory root (the same root the route uses) -> ~/.thomas fallback.
    """
    if explicit:
        return Path(explicit)
    env_dir = _env("THOMAS_PAPER_TRADING_DIR")
    if env_dir:
        return Path(env_dir)
    try:
        from thomas.core.config import load_config

        root = load_config().memory.root_path
        return Path(root) / _PLUGIN_RELATIVE
    # Importing the core config module, reading thomas.toml off disk (a TOML/JSON
    # decode error is a ValueError subclass), and walking .memory.root_path. A
    # config that will not load must not stop the plugin from resolving a data
    # dir -- it falls back to ~/.thomas. Anything outside this set is a real bug
    # and should surface rather than silently relocate the owner's state file.
    except (ImportError, OSError, ValueError, TypeError, AttributeError, LookupError):
        log.debug("core config unavailable; using the ~/.thomas paper-trading dir", exc_info=True)
        return Path.home() / _PLUGIN_RELATIVE


def _positive(value: float, default: float) -> float:
    """A non-positive override must never silently DISABLE a guard."""
    return value if value > 0 else default


def _default_risk() -> RiskRules:
    allowlist_raw = _env("THOMAS_PAPER_SYMBOL_ALLOWLIST")
    allowlist = tuple(s.strip().upper() for s in allowlist_raw.split(",") if s.strip())
    # Guards must not be neutered by a 0/negative env override (adversarial
    # review finding): fall back to the safe default instead.
    min_price_raw = _env_float("THOMAS_PAPER_MIN_PRICE", 1.0)
    return RiskRules(
        max_order_usd=_positive(_env_float("THOMAS_PAPER_MAX_ORDER_USD", 1000.0), 1000.0),
        max_position_pct=_positive(_env_float("THOMAS_PAPER_MAX_POSITION_PCT", 20.0), 20.0),
        max_trades_per_day=int(_positive(_env_int("THOMAS_PAPER_MAX_TRADES_PER_DAY", 10), 10)),
        min_price=min_price_raw if min_price_raw >= 0 else 1.0,
        regular_hours_only=_env_bool("THOMAS_PAPER_REGULAR_HOURS_ONLY", True),
        symbol_allowlist=allowlist,
    )


def _read_credentials_file(data_dir: Path) -> tuple[str, str]:
    path = data_dir / _CREDENTIALS_FILE
    if not path.exists():
        return "", ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    return (
        str(payload.get("key_id") or "").strip(),
        str(payload.get("secret_key") or "").strip(),
    )


def write_credentials_file(data_dir: Path, key_id: str, secret_key: str) -> None:
    """Persist Alpaca *paper* credentials to a local JSON file.

    These are paper keys (no real-money authority). The env vars
    APCA_API_KEY_ID / APCA_API_SECRET_KEY are preferred and take precedence at
    read time; this file is a convenience for the UI flow. Note: the chmod below
    only sets POSIX bits — on Windows it merely toggles the read-only flag, so
    the file inherits the user-profile directory ACL.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / _CREDENTIALS_FILE
    tmp = path.with_suffix(path.suffix + ".tmp")
    body = json.dumps(
        {"key_id": key_id.strip(), "secret_key": secret_key.strip()},
        ensure_ascii=False,
        indent=2,
    )
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)  # POSIX-only; no-op for ACLs on Windows
    except OSError:
        pass


@dataclass
class PaperTradingConfig:
    data_dir: Path
    paper_base_url: str = PAPER_TRADING_BASE_URL
    data_base_url: str = MARKET_DATA_BASE_URL
    key_id: str = ""
    secret_key: str = ""
    risk: RiskRules = field(default_factory=RiskRules)

    @property
    def has_credentials(self) -> bool:
        return bool(self.key_id and self.secret_key)

    @property
    def state_path(self) -> Path:
        return self.data_dir / _STATE_FILE

    def validate_paper(self) -> None:
        """Re-assert the paper-only invariant on the configured endpoints."""
        assert_paper(self.paper_base_url)
        assert_paper(self.data_base_url)


def load_paper_trading_config(
    *,
    data_dir: Path | str | None = None,
    key_id: str = "",
    secret_key: str = "",
) -> PaperTradingConfig:
    """Build config from (in order) explicit args, env vars, then the creds file."""
    resolved_dir = resolve_data_dir(data_dir)
    file_id, file_secret = _read_credentials_file(resolved_dir)
    resolved_id = key_id.strip() or _env("APCA_API_KEY_ID", "ALPACA_API_KEY_ID", "ALPACA_API_KEY") or file_id
    resolved_secret = (
        secret_key.strip() or _env("APCA_API_SECRET_KEY", "ALPACA_API_SECRET_KEY", "ALPACA_SECRET_KEY") or file_secret
    )
    cfg = PaperTradingConfig(
        data_dir=resolved_dir,
        key_id=resolved_id,
        secret_key=resolved_secret,
        risk=_default_risk(),
    )
    cfg.validate_paper()
    return cfg
