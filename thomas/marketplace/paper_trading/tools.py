"""Agent-facing tools for paper trading.

These are what let Thomas *use* the module: read market data, propose trades
(with a required thesis + invalidation), inspect proposals, submit ones a human
approved, and review its own track record. There is intentionally NO approve
tool — approval is a human action exposed only through the authenticated UI/route.
"""

from __future__ import annotations

from typing import Any

from thomas.marketplace.paper_trading._exceptions import (
    ApprovalRequired,
    PaperTradingError,
    ProposalNotFound,
)
from thomas.marketplace.paper_trading.engine import PaperTradingEngine
from thomas.tools.base import Tool, ToolResult


def _engine() -> PaperTradingEngine:
    # Tools run outside the aiohttp app, so credentials come from env / creds file
    # and there is no memory handle here (the route does memory writes on reconcile).
    return PaperTradingEngine.build()


# Everything the engine path can realistically raise, reported to the model as a
# failed ToolResult instead of killing its turn:
#   PaperTradingError  - the module's own errors (broker unreachable, bad config,
#                        live-endpoint block, risk rejection, approval refused,
#                        unknown proposal id)
#   LookupError        - a missing key in the model-supplied ``args`` dict
#   TypeError/ValueError - args of the wrong shape (int(args["limit"]) on prose)
#   ArithmeticError    - price/qty maths on a zero or absent reference price
#   OSError            - the JSON state file and the sim positions file
#   AttributeError     - a broker object missing part of the duck-typed interface
# Anything outside this set (ImportError from a bad refactor, a NameError) is a
# genuine bug and must surface rather than be reported as a tool failure.
_TOOL_FAULTS = (
    PaperTradingError,
    ArithmeticError,
    AttributeError,
    LookupError,
    OSError,
    TypeError,
    ValueError,
)


def _err(exc: Exception) -> ToolResult:
    return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")


class PaperTradingAccountTool(Tool):
    name = "paper_trading.account"
    category = "paper_trading"
    description = (
        "Get the paper trading account snapshot: equity, cash, buying power. "
        "Uses a simulated account if no Alpaca paper credentials are configured."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            acct = await _engine().account()
            return ToolResult(ok=True, data=acct.to_dict())
        except _TOOL_FAULTS as exc:
            return _err(exc)


class PaperTradingPositionsTool(Tool):
    name = "paper_trading.positions"
    category = "paper_trading"
    description = "List current open paper-trading positions with unrealized P&L."
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            positions = await _engine().positions()
            return ToolResult(ok=True, data=[p.to_dict() for p in positions])
        except _TOOL_FAULTS as exc:
            return _err(exc)


class PaperTradingQuoteTool(Tool):
    name = "paper_trading.quote"
    category = "paper_trading"
    description = "Get the latest quote (bid/ask/mid) for a stock or ETF symbol."
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Ticker, e.g. AAPL or SPY"},
        },
        "required": ["symbol"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            q = await _engine().quote(args["symbol"])
            return ToolResult(ok=True, data=q.to_dict())
        except _TOOL_FAULTS as exc:
            return _err(exc)


class PaperTradingBarsTool(Tool):
    name = "paper_trading.bars"
    category = "paper_trading"
    description = "Get recent OHLCV price bars for a symbol, for technical analysis (default: 30 daily bars)."
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Ticker, e.g. AAPL"},
            "timeframe": {
                "type": "string",
                "description": "Alpaca timeframe, e.g. 1Day, 1Hour, 15Min",
            },
            "limit": {"type": "integer", "description": "Number of bars (max 30)"},
        },
        "required": ["symbol"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            bars = await _engine().bars(
                args["symbol"],
                timeframe=str(args.get("timeframe") or "1Day"),
                limit=int(args.get("limit") or 30),
            )
            return ToolResult(ok=True, data={"symbol": args["symbol"], "bars": bars})
        except _TOOL_FAULTS as exc:
            return _err(exc)


class PaperTradingProposeTool(Tool):
    name = "paper_trading.propose"
    category = "paper_trading"
    description = (
        "Propose a paper trade for HUMAN APPROVAL. You must state a thesis (why) "
        "and an invalidation condition (what would prove it wrong) — these are "
        "recorded and later scored against the real outcome. This does NOT execute "
        "the trade; it creates a pending proposal the owner must approve. Provide "
        "either qty (shares) or notional (dollar amount)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Ticker, e.g. AAPL"},
            "side": {"type": "string", "enum": ["buy", "sell"]},
            "thesis": {
                "type": "string",
                "description": "Why you want this trade — the reasoning behind it.",
            },
            "invalidation": {
                "type": "string",
                "description": "What would prove the thesis wrong / your exit condition.",
            },
            "qty": {"type": "number", "description": "Number of shares (or use notional)"},
            "notional": {
                "type": "number",
                "description": "Dollar amount to trade (or use qty)",
            },
            "order_type": {"type": "string", "enum": ["market", "limit"]},
            "limit_price": {"type": "number", "description": "Required if order_type=limit"},
            "time_in_force": {"type": "string", "enum": ["day", "gtc"]},
        },
        "required": ["symbol", "side", "thesis", "invalidation"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        thesis = str(args.get("thesis") or "").strip()
        invalidation = str(args.get("invalidation") or "").strip()
        if not thesis or not invalidation:
            return ToolResult(
                ok=False,
                error="thesis and invalidation are both required — record why and what would prove the trade wrong.",
            )
        try:
            proposal = await _engine().propose(
                symbol=args["symbol"],
                side=str(args.get("side") or "").lower(),
                thesis=thesis,
                invalidation=invalidation,
                qty=args.get("qty"),
                notional=args.get("notional"),
                order_type=str(args.get("order_type") or "market").lower(),
                limit_price=args.get("limit_price"),
                time_in_force=str(args.get("time_in_force") or "day").lower(),
            )
            data = proposal.to_dict()
            data["_note"] = (
                "Proposal created. It is PENDING the owner's approval in the Paper "
                "Trading workspace; it has not been submitted."
                if proposal.status == "pending_approval"
                else "Proposal was BLOCKED by risk rules — see risk.violations."
            )
            return ToolResult(ok=True, data=data)
        except _TOOL_FAULTS as exc:
            return _err(exc)


class PaperTradingListProposalsTool(Tool):
    name = "paper_trading.list_proposals"
    category = "paper_trading"
    description = "List trade proposals, optionally filtered by status."
    parameters = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Optional filter: pending_approval, approved, "
                "blocked_by_risk, rejected, submitted, filled",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            status = str(args.get("status") or "").strip() or None
            proposals = _engine().store.list_proposals(status=status)
            return ToolResult(ok=True, data=[p.to_dict() for p in proposals])
        except _TOOL_FAULTS as exc:
            return _err(exc)


class PaperTradingSubmitTool(Tool):
    name = "paper_trading.submit"
    category = "paper_trading"
    description = (
        "Submit a proposal that the owner has APPROVED to the paper broker. This "
        "refuses any proposal that is not in 'approved' status — you cannot bypass "
        "the human approval gate."
    )
    parameters = {
        "type": "object",
        "properties": {
            "proposal_id": {"type": "string", "description": "The approved proposal id"},
        },
        "required": ["proposal_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            proposal = await _engine().submit(str(args["proposal_id"]))
            return ToolResult(ok=True, data=proposal.to_dict())
        except ApprovalRequired as exc:
            return ToolResult(ok=False, error=str(exc))
        except (ProposalNotFound, PaperTradingError) as exc:
            return _err(exc)
        except _TOOL_FAULTS as exc:
            return _err(exc)


class PaperTradingReviewTool(Tool):
    name = "paper_trading.review"
    category = "paper_trading"
    description = (
        "Re-price open positions, score closed trades against their original "
        "thesis, and return your track record (win rate, P&L, validated vs "
        "invalidated theses). Use this to learn from past calls before proposing."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            engine = _engine()
            await engine.reconcile()
            return ToolResult(ok=True, data=engine.review())
        except _TOOL_FAULTS as exc:
            return _err(exc)


class PaperTradingRecallTool(Tool):
    name = "paper_trading.recall"
    category = "paper_trading"
    description = (
        "Review your own PRIOR trade outcomes and lessons before proposing — "
        "optionally filtered to a symbol. Call this first so past results inform "
        "the new thesis; the system is meant to learn from its track record over "
        "time. Note the small-sample caveat in the result."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Optional ticker to filter lessons (e.g. AAPL)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            data = _engine().recall(str(args.get("symbol") or ""))
            return ToolResult(ok=True, data=data)
        except _TOOL_FAULTS as exc:
            return _err(exc)


def register_paper_trading_tools(registry: Any) -> None:
    """Register all paper-trading tools. Called by tool_extensions at startup."""
    for tool_cls in (
        PaperTradingAccountTool,
        PaperTradingPositionsTool,
        PaperTradingQuoteTool,
        PaperTradingBarsTool,
        PaperTradingRecallTool,
        PaperTradingProposeTool,
        PaperTradingListProposalsTool,
        PaperTradingSubmitTool,
        PaperTradingReviewTool,
    ):
        registry.register(tool_cls())
