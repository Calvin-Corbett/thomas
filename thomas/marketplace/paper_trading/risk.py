"""Pre-trade risk checks. Every proposal is evaluated here BEFORE a human sees it.

A proposal that fails any hard limit is stored as BLOCKED_BY_RISK and is not
eligible for approval — the human gate never even gets the chance to wave it
through. This is the "discipline beats IQ" layer: the rules are mechanical and
unemotional.
"""

from __future__ import annotations

from thomas.marketplace.paper_trading._types import (
    AccountSnapshot,
    PositionSnapshot,
    RiskCheck,
    RiskRules,
    Side,
)


def estimate_order_value(
    *,
    qty: float | None,
    notional: float | None,
    reference_price: float,
) -> float:
    """Best-effort dollar value of the order for sizing checks."""
    if notional and notional > 0:
        return float(notional)
    if qty and qty > 0 and reference_price > 0:
        return float(qty) * float(reference_price)
    return 0.0


def evaluate_risk(
    *,
    symbol: str,
    side: str,
    order_type: str,
    qty: float | None,
    notional: float | None,
    reference_price: float,
    rules: RiskRules,
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    trades_today: int,
    market_open: bool,
) -> RiskCheck:
    violations: list[str] = []
    notes: list[str] = []

    symbol = (symbol or "").upper().strip()
    if not symbol:
        violations.append("symbol is required")

    if qty is None and notional is None:
        violations.append("either qty or notional is required")
    if qty is not None and qty <= 0:
        violations.append("qty must be positive")
    if notional is not None and notional <= 0:
        violations.append("notional must be positive")

    if order_type not in rules.allowed_order_types:
        violations.append(f"order_type {order_type!r} not allowed (allowed: {', '.join(rules.allowed_order_types)})")

    if rules.symbol_allowlist and symbol not in rules.symbol_allowlist:
        violations.append(f"{symbol} not in symbol allow-list ({', '.join(rules.symbol_allowlist)})")

    if reference_price > 0 and reference_price < rules.min_price:
        violations.append(
            f"price ${reference_price:.2f} is below the ${rules.min_price:.2f} minimum (penny-stock guard)"
        )
    elif reference_price <= 0:
        notes.append("no reference price available; size check is approximate")
        # Fail closed: a share-quantity order can't be sized without a price.
        if notional is None and qty is not None:
            violations.append("cannot size a share-quantity order without a current price")

    order_value = estimate_order_value(qty=qty, notional=notional, reference_price=reference_price)
    if order_value > 0 and order_value > rules.max_order_usd:
        violations.append(f"order value ${order_value:,.0f} exceeds the ${rules.max_order_usd:,.0f} per-order cap")

    # Position concentration check (buys grow exposure).
    if side == Side.BUY.value and account.equity > 0:
        existing = 0.0
        for p in positions:
            if p.symbol.upper() == symbol:
                existing = abs(p.market_value)
                break
        projected = existing + order_value
        pct = (projected / account.equity) * 100.0 if account.equity else 0.0
        if pct > rules.max_position_pct:
            violations.append(
                f"position in {symbol} would be {pct:.0f}% of the account, over the {rules.max_position_pct:.0f}% cap"
            )

    if rules.regular_hours_only and not market_open:
        violations.append("market is closed and regular-hours-only is enabled")

    if rules.max_trades_per_day > 0 and trades_today >= rules.max_trades_per_day:
        violations.append(f"daily trade cap reached ({trades_today}/{rules.max_trades_per_day} trades today)")

    return RiskCheck(passed=not violations, violations=violations, notes=notes)
