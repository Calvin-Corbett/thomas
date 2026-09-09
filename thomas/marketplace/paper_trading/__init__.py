"""Paper Trading — propose / approve / execute / score / learn on a paper account.

Phase 1 of Thomas's trading capability: stocks & ETFs, paper-only (Alpaca free
paper API + free IEX market data), with a human approving every order. The model
proposes with a thesis; outcomes are scored against that thesis and written to
memory so future proposals improve.

Safety invariants:
* Paper-only: the trading endpoint is a hardcoded paper URL, re-asserted before
  every request. There is no live-trading mode flag.
* Human gate: the model can only create proposals; a human must approve before
  anything is submitted.
* Risk rules: every proposal is mechanically checked (per-order cap, position
  concentration, daily trade count, penny-stock guard, market hours) before a
  human ever sees it.
"""

from __future__ import annotations

from thomas.marketplace.paper_trading._exceptions import (
    ApprovalRequired,
    BrokerError,
    ConfigError,
    CredentialsMissing,
    LiveTradingBlocked,
    PaperTradingError,
    ProposalNotFound,
    RiskRejected,
)
from thomas.marketplace.paper_trading._types import (
    AccountSnapshot,
    JournalEntry,
    PositionSnapshot,
    Proposal,
    ProposalStatus,
    Quote,
    RiskCheck,
    RiskRules,
    Side,
    ThesisOutcome,
    TrackRecord,
)
from thomas.marketplace.paper_trading.config import (
    PaperTradingConfig,
    load_paper_trading_config,
)
from thomas.marketplace.paper_trading.engine import PaperTradingEngine
from thomas.marketplace.paper_trading.tools import register_paper_trading_tools

__version__ = "1.0.0"

__all__ = [
    "PaperTradingEngine",
    "PaperTradingConfig",
    "load_paper_trading_config",
    "register_paper_trading_tools",
    "AccountSnapshot",
    "PositionSnapshot",
    "Proposal",
    "ProposalStatus",
    "JournalEntry",
    "Quote",
    "RiskCheck",
    "RiskRules",
    "Side",
    "ThesisOutcome",
    "TrackRecord",
    "PaperTradingError",
    "ConfigError",
    "CredentialsMissing",
    "LiveTradingBlocked",
    "RiskRejected",
    "ProposalNotFound",
    "ApprovalRequired",
    "BrokerError",
]
