"""The paper-trading engine: the propose -> approve -> submit -> score loop.

Safety properties enforced here:
* The model can only create proposals (PENDING_APPROVAL / BLOCKED_BY_RISK).
* ``approve()`` is the human gate — only the route calls it, in response to an
  authenticated owner action. There is no agent tool that approves.
* ``submit()`` refuses anything that is not APPROVED, so an un-approved proposal
  can never reach the broker.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from thomas.marketplace.paper_trading._exceptions import (
    ApprovalRequired,
    BrokerError,
    PaperTradingError,
    RiskRejected,
)

# Tickers: letters/digits plus dot and dash (e.g. BRK.B, RDS-A). Anything else is
# rejected — both as input hygiene and as defense-in-depth against a crafted
# "symbol" being rendered into the owner's workspace (stored-XSS guard).
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")


def _valid_symbol(symbol: str) -> bool:
    return bool(_SYMBOL_RE.match(symbol or ""))


from thomas.marketplace.paper_trading._types import (
    AccountSnapshot,
    JournalEntry,
    OrderType,
    Proposal,
    ProposalStatus,
    Quote,
    RiskCheck,
    Side,
    TimeInForce,
    new_id,
)
from thomas.marketplace.paper_trading.alpaca_client import make_broker
from thomas.marketplace.paper_trading.config import (
    PaperTradingConfig,
    load_paper_trading_config,
)
from thomas.marketplace.paper_trading.risk import evaluate_risk
from thomas.marketplace.paper_trading.scoring import (
    record_lesson,
    score_open_entry,
    summarize_track_record,
)
from thomas.marketplace.paper_trading.store import PaperTradingStore


class PaperTradingEngine:
    def __init__(
        self,
        config: PaperTradingConfig,
        store: PaperTradingStore,
        broker: Any,
        *,
        memory_engine: Any = None,
    ) -> None:
        self.config = config
        self.store = store
        self.broker = broker
        self.memory_engine = memory_engine

    @classmethod
    def build(
        cls,
        *,
        data_dir: Path | str | None = None,
        memory_engine: Any = None,
        key_id: str = "",
        secret_key: str = "",
    ) -> PaperTradingEngine:
        config = load_paper_trading_config(data_dir=data_dir, key_id=key_id, secret_key=secret_key)
        store = PaperTradingStore(config.state_path)
        broker = make_broker(config)
        return cls(config, store, broker, memory_engine=memory_engine)

    # --- read-through to broker --------------------------------------------
    async def account(self) -> AccountSnapshot:
        return await self.broker.get_account()

    async def positions(self):
        return await self.broker.list_positions()

    async def quote(self, symbol: str) -> Quote:
        return await self.broker.get_latest_quote(symbol)

    async def bars(self, symbol: str, *, timeframe: str = "1Day", limit: int = 30):
        return await self.broker.get_bars(symbol, timeframe=timeframe, limit=limit)

    # --- the loop -----------------------------------------------------------
    async def propose(
        self,
        *,
        symbol: str,
        side: str,
        thesis: str,
        invalidation: str,
        qty: float | None = None,
        notional: float | None = None,
        order_type: str = OrderType.MARKET.value,
        limit_price: float | None = None,
        time_in_force: str = TimeInForce.DAY.value,
    ) -> Proposal:
        """Build, risk-check, and store a proposal. Never submits."""
        symbol = (symbol or "").upper().strip()
        side = (side or "").lower().strip()
        order_type = (order_type or "market").lower().strip()

        if not _valid_symbol(symbol):
            raise PaperTradingError(f"invalid symbol: {symbol!r}")
        if side not in (Side.BUY.value, Side.SELL.value):
            raise PaperTradingError(f"invalid side: {side!r} (expected buy or sell)")
        if order_type not in (OrderType.MARKET.value, OrderType.LIMIT.value):
            raise PaperTradingError(f"invalid order_type: {order_type!r}")

        reference_price = 0.0
        account = AccountSnapshot()
        positions: list = []
        market_open = False  # fail closed: only True if the clock fetch succeeds
        data_ok = True
        broker_note = ""
        try:
            q = await self.broker.get_latest_quote(symbol)
            reference_price = q.price
            account = await self.broker.get_account()
            positions = await self.broker.list_positions()
            market_open = await self.broker.is_market_open()
        except BrokerError as exc:
            data_ok = False
            broker_note = f"broker/market data unavailable ({exc})"

        check = evaluate_risk(
            symbol=symbol,
            side=side,
            order_type=order_type,
            qty=qty,
            notional=notional,
            reference_price=reference_price,
            rules=self.config.risk,
            account=account,
            positions=positions,
            trades_today=self.store.count_trades_today(),
            market_open=market_open,
        )
        if not data_ok:
            # Without live data we cannot honestly risk-check -> fail closed.
            check.passed = False
            check.violations.append(broker_note + " - cannot risk-check, blocking the proposal")

        status = ProposalStatus.PENDING_APPROVAL.value if check.passed else ProposalStatus.BLOCKED_BY_RISK.value
        proposal = Proposal(
            id=new_id("prop"),
            symbol=symbol,
            side=side,
            order_type=order_type,
            qty=qty,
            notional=notional,
            limit_price=limit_price,
            time_in_force=time_in_force,
            thesis=str(thesis or "").strip(),
            invalidation=str(invalidation or "").strip(),
            status=status,
            risk=check.to_dict(),
            reference_price=reference_price,
        )
        return self.store.add_proposal(proposal)

    async def _risk_recheck(self, proposal: Proposal) -> RiskCheck:
        """Re-evaluate risk against fresh data at submit time. Fails closed."""
        reference_price = proposal.reference_price or 0.0
        account = AccountSnapshot()
        positions: list = []
        market_open = False
        data_ok = True
        try:
            q = await self.broker.get_latest_quote(proposal.symbol)
            reference_price = q.price
            account = await self.broker.get_account()
            positions = await self.broker.list_positions()
            market_open = await self.broker.is_market_open()
        except BrokerError:
            data_ok = False
        check = evaluate_risk(
            symbol=proposal.symbol,
            side=proposal.side,
            order_type=proposal.order_type,
            qty=proposal.qty,
            notional=proposal.notional,
            reference_price=reference_price,
            rules=self.config.risk,
            account=account,
            positions=positions,
            trades_today=self.store.count_trades_today(),
            market_open=market_open,
        )
        if not data_ok:
            check.passed = False
            check.violations.append("market data unavailable at submit; blocked")
        return check

    def approve(self, proposal_id: str, *, approver: str = "owner") -> Proposal:
        """HUMAN GATE. Promote a pending proposal to APPROVED."""
        proposal = self.store.get_proposal(proposal_id)
        if proposal.status != ProposalStatus.PENDING_APPROVAL.value:
            raise ApprovalRequired(f"proposal {proposal_id} is {proposal.status}, not pending_approval")
        import time

        proposal.status = ProposalStatus.APPROVED.value
        proposal.decided_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        proposal.decided_by = approver
        return self.store.update_proposal(proposal)

    def reject(self, proposal_id: str, *, note: str = "") -> Proposal:
        proposal = self.store.get_proposal(proposal_id)
        if proposal.status not in (
            ProposalStatus.PENDING_APPROVAL.value,
            ProposalStatus.BLOCKED_BY_RISK.value,
        ):
            # Cannot reject a submitted/filled trade — that would orphan its
            # journal entry and reset the daily-trade count.
            raise ApprovalRequired(f"proposal {proposal_id} is {proposal.status} and cannot be rejected")
        import time

        proposal.status = ProposalStatus.REJECTED.value
        proposal.decided_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        proposal.decision_note = str(note or "").strip()
        return self.store.update_proposal(proposal)

    async def submit(self, proposal_id: str) -> Proposal:
        """Execute an APPROVED proposal against the (paper) broker.

        Refuses anything not in APPROVED state — the model cannot bypass the
        human gate because it has no way to set APPROVED.
        """
        proposal = self.store.get_proposal(proposal_id)
        # APPROVED is the normal path; ERROR is allowed so a transient broker
        # failure on a still-owner-approved order can be retried (the human gate
        # is intact — ERROR is only reachable after a prior approval).
        if proposal.status not in (
            ProposalStatus.APPROVED.value,
            ProposalStatus.ERROR.value,
        ):
            raise ApprovalRequired(f"refusing to submit {proposal_id}: status is {proposal.status}, not approved")

        # Re-check risk against FRESH data right before execution. Closes the
        # propose-time vs submit-time gap (e.g. many proposals approved while
        # under the daily cap, then all submitted past it) and refuses anything
        # that now violates the rules. Fails closed if data is unavailable.
        recheck = await self._risk_recheck(proposal)
        if not recheck.passed:
            import time

            proposal.status = ProposalStatus.BLOCKED_BY_RISK.value
            proposal.risk = recheck.to_dict()
            proposal.decision_note = "blocked at submit: " + "; ".join(recheck.violations)
            proposal.decided_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self.store.update_proposal(proposal)
            raise RiskRejected(recheck.violations)

        try:
            order = await self.broker.submit_order(
                symbol=proposal.symbol,
                side=proposal.side,
                qty=proposal.qty,
                notional=proposal.notional,
                order_type=proposal.order_type,
                limit_price=proposal.limit_price,
                time_in_force=proposal.time_in_force,
            )
        except BrokerError as exc:
            import time

            proposal.status = ProposalStatus.ERROR.value
            proposal.decision_note = f"submit failed: {exc}"
            proposal.decided_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self.store.update_proposal(proposal)
            raise

        import time

        fill_price = float(order.get("filled_avg_price") or 0.0) or proposal.reference_price
        fill_qty = float(order.get("filled_qty") or 0.0) or float(proposal.qty or 0.0)
        if fill_qty == 0 and proposal.notional and fill_price > 0:
            fill_qty = round(float(proposal.notional) / fill_price, 6)

        proposal.broker_order_id = str(order.get("id") or "")
        proposal.submitted_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        proposal.status = (
            ProposalStatus.FILLED.value if str(order.get("status")) == "filled" else ProposalStatus.SUBMITTED.value
        )
        self.store.update_proposal(proposal)

        entry = JournalEntry(
            id=new_id("jrnl"),
            proposal_id=proposal.id,
            symbol=proposal.symbol,
            side=proposal.side,
            qty=fill_qty,
            entry_price=round(fill_price, 4),
            thesis=proposal.thesis,
            invalidation=proposal.invalidation,
            last_price=round(fill_price, 4),
        )
        self.store.append_journal(entry)
        return proposal

    async def reconcile(self) -> list[JournalEntry]:
        """Re-price open journal entries against live positions and score them."""
        try:
            positions = await self.broker.list_positions()
        except BrokerError:
            positions = []
        by_symbol = {p.symbol.upper(): p for p in positions}

        updated: list[JournalEntry] = []
        for entry in self.store.list_journal():
            if entry.closed_at:
                updated.append(entry)
                continue
            pos = by_symbol.get(entry.symbol.upper())
            if pos is not None:
                # Backfill an entry written before its fill price/qty were known
                # (e.g. async notional fill with no propose-time quote), else its
                # P&L would be stuck at 0 forever.
                if entry.qty == 0 and pos.qty:
                    entry.qty = abs(pos.qty)
                if entry.entry_price == 0 and pos.avg_entry_price:
                    entry.entry_price = pos.avg_entry_price
                score_open_entry(entry, current_price=pos.current_price, still_open=True)
            else:
                # No open position -> treat as closed at last known price.
                price = entry.last_price or entry.entry_price
                score_open_entry(entry, current_price=price, still_open=False)
                record_lesson(self.memory_engine, entry)
            self.store.update_journal(entry)
            updated.append(entry)
        return updated

    def review(self) -> dict[str, Any]:
        entries = self.store.list_journal()
        tr = summarize_track_record(entries)
        from thomas.marketplace.paper_trading.scoring import build_lesson

        return {
            "track_record": tr.to_dict(),
            "recent": [build_lesson(e) for e in entries[-5:]],
            "simulated": getattr(self.broker, "is_simulated", False),
        }

    def recall(self, symbol: str = "", *, limit: int = 8) -> dict[str, Any]:
        """Surface prior outcomes so the agent READS its record before proposing.

        Closes the learning loop (research finding: the journal was write-only).
        Returns past lessons (optionally filtered to a symbol) plus a small-sample
        caveat so a couple of lucky trades are not over-trusted.
        """
        from thomas.marketplace.paper_trading.scoring import build_lesson

        entries = self.store.list_journal()
        sym = (symbol or "").upper().strip()
        relevant = [e for e in entries if (not sym or e.symbol.upper() == sym)]
        closed = [e for e in relevant if e.closed_at]
        wins = sum(1 for e in closed if e.realized_pl > 0)
        return {
            "symbol": sym or "(all symbols)",
            "closed_trades": len(closed),
            "wins": wins,
            "losses": len(closed) - wins,
            "lessons": [build_lesson(e) for e in relevant[-limit:]],
            "small_sample_caveat": (
                "Fewer than 10 closed trades — treat these outcomes as weak signal." if len(closed) < 10 else ""
            ),
        }

    # --- convenience for UI bootstrap --------------------------------------
    async def bootstrap(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "has_credentials": self.config.has_credentials,
            "simulated": getattr(self.broker, "is_simulated", False),
            "risk_rules": self.config.risk.to_dict(),
            "proposals": [p.to_dict() for p in self.store.list_proposals()],
            "review": self.review(),
        }
        try:
            out["account"] = (await self.broker.get_account()).to_dict()
            out["positions"] = [p.to_dict() for p in await self.broker.list_positions()]
            out["market_open"] = await self.broker.is_market_open()
        except BrokerError as exc:
            out["account"] = None
            out["positions"] = []
            out["broker_error"] = str(exc)
        return out


_SIDES = {Side.BUY.value, Side.SELL.value}


def normalize_side(value: str) -> str:
    v = (value or "").lower().strip()
    return v if v in _SIDES else ""
