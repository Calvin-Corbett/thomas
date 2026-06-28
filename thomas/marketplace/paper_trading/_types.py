"""Typed data models for the paper-trading module.

Money is represented as ``float`` throughout. This is a deliberate, bounded
choice: Alpaca returns numeric strings, and these values are used for paper P&L
display and outcome scoring, not as a ledger of record. Values are rounded at
serialization boundaries. If this module ever graduates to real-money custody,
revisit and switch to ``decimal.Decimal``.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


def _now_iso() -> str:
    """UTC ISO-8601 timestamp. Uses time.gmtime to avoid tz-database surprises."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id(prefix: str) -> str:
    """Short, sortable-ish id. Uses os.urandom via secrets for collision safety."""
    import secrets

    return f"{prefix}_{secrets.token_hex(6)}"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"


class ProposalStatus(str, Enum):
    """Lifecycle of a trade proposal.

    The model can only ever produce ``PENDING_APPROVAL`` (or ``BLOCKED_BY_RISK``).
    A human transition is required to reach ``APPROVED``; only an ``APPROVED``
    proposal may be submitted to the broker.
    """

    PENDING_APPROVAL = "pending_approval"
    BLOCKED_BY_RISK = "blocked_by_risk"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELED = "canceled"
    ERROR = "error"


class ThesisOutcome(str, Enum):
    OPEN = "open"
    VALIDATED = "validated"
    INVALIDATED = "invalidated"
    INCONCLUSIVE = "inconclusive"


@dataclass
class RiskRules:
    """Hard limits every proposal is checked against before a human ever sees it.

    Defaults are Calvin's approved Phase-1 numbers. They can be overridden via
    ``THOMAS_PAPER_*`` env vars (see config.py).
    """

    max_order_usd: float = 1000.0
    max_position_pct: float = 20.0  # max % of account equity in any one symbol
    max_trades_per_day: int = 10
    min_price: float = 1.0  # block sub-$1 / penny stocks
    allowed_order_types: tuple[str, ...] = ("market", "limit")
    regular_hours_only: bool = True
    # Optional symbol allow-list. Empty tuple == allow any (subject to other rules).
    symbol_allowlist: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Quote:
    symbol: str
    price: float  # best-effort mid/last
    bid: float = 0.0
    ask: float = 0.0
    as_of: str = ""
    feed: str = "iex"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AccountSnapshot:
    equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    currency: str = "USD"
    status: str = ""
    pattern_day_trader: bool = False
    as_of: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PositionSnapshot:
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_plpc: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RiskCheck:
    passed: bool
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Proposal:
    """A trade the model wants to make, plus the discipline that makes it useful.

    ``thesis`` and ``invalidation`` are required by the propose tool: recording
    *why* and *what would prove it wrong* is what later lets us score the call
    against reality and learn from it.
    """

    id: str
    symbol: str
    side: str  # Side value
    order_type: str  # OrderType value
    qty: float | None
    notional: float | None
    limit_price: float | None
    time_in_force: str
    thesis: str
    invalidation: str
    status: str  # ProposalStatus value
    risk: dict[str, Any]
    created_at: str = field(default_factory=_now_iso)
    decided_at: str = ""
    decided_by: str = ""
    decision_note: str = ""
    # Reference price captured at proposal time, for later scoring.
    reference_price: float = 0.0
    # Populated after submission.
    broker_order_id: str = ""
    submitted_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JournalEntry:
    """One realized trading decision, tracked from submission through scoring.

    This is the dataset that compounds: every entry pairs the original thesis
    with the realized outcome, so the agent can review its own track record.
    """

    id: str
    proposal_id: str
    symbol: str
    side: str
    qty: float
    entry_price: float
    thesis: str
    invalidation: str
    opened_at: str = field(default_factory=_now_iso)
    # Scoring fields, updated by reconcile/score.
    last_price: float = 0.0
    unrealized_pl: float = 0.0
    unrealized_plpc: float = 0.0
    realized_pl: float = 0.0
    closed_at: str = ""
    thesis_outcome: str = ThesisOutcome.OPEN.value
    lesson: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrackRecord:
    total: int = 0
    open_count: int = 0
    closed_count: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_realized_pl: float = 0.0
    total_unrealized_pl: float = 0.0
    avg_realized_pl: float = 0.0
    thesis_validated: int = 0
    thesis_invalidated: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
