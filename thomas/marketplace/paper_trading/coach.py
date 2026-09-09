"""The Coach: designs training scenarios and GRADES runs.

Grading is deliberately mechanical (return vs. a buy-and-hold benchmark, win
rate, drawdown, thesis hit-rate, risk discipline) rather than an LLM judging
itself — that avoids the self-preference trap. Every grade carries an explicit
"sandbox, not skill" caveat because results on historical data can be inflated
by the model having seen that history in training.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from thomas.marketplace.paper_trading._types import JournalEntry, ThesisOutcome

# Curated starting scenarios across different market "regimes". The Coach can
# pick from these (or a caller can supply a custom symbol+range).
SCENARIOS: list[dict[str, str]] = [
    {
        "name": "Broad market, calm",
        "symbol": "SPY",
        "range": "2y",
        "description": "Trade the S&P 500 ETF over a relatively steady stretch.",
    },
    {
        "name": "Big-tech momentum",
        "symbol": "MSFT",
        "range": "2y",
        "description": "A large-cap tech name with sustained trends.",
    },
    {
        "name": "High volatility",
        "symbol": "NVDA",
        "range": "2y",
        "description": "Sharp run-ups and drawdowns — tests risk discipline.",
    },
    {
        "name": "Index, long horizon",
        "symbol": "QQQ",
        "range": "5y",
        "description": "Nasdaq-100 ETF across multiple regimes incl. a bear year.",
    },
]


@dataclass
class Grade:
    scenario: str
    symbol: str
    starting_cash: float
    final_equity: float
    return_pct: float
    benchmark_return_pct: float  # buy-and-hold the symbol over the same window
    alpha_pct: float  # return minus benchmark (the only number that means anything)
    trades: int
    closed_trades: int
    win_rate: float
    max_drawdown_pct: float
    thesis_validated: int
    thesis_invalidated: int
    risk_blocks: int
    grade_letter: str
    summary: str
    sandbox_caveat: str = (
        "Sandbox score on historical data — NOT proof of skill. The model may "
        "have seen this history in training. Real skill only counts forward on "
        "live paper."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def max_drawdown_pct(equity_curve: list[dict[str, Any]]) -> float:
    """Largest peak-to-trough drop in equity, as a positive percentage."""
    peak = float("-inf")
    worst = 0.0
    for point in equity_curve:
        eq = float(point.get("equity", 0.0))
        peak = max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak * 100.0
            worst = max(worst, dd)
    return round(worst, 2)


def _letter(alpha_pct: float, max_dd: float) -> str:
    """A coarse grade: reward beating buy-and-hold without ruinous drawdowns."""
    if alpha_pct >= 5 and max_dd <= 25:
        return "A"
    if alpha_pct >= 0 and max_dd <= 35:
        return "B"
    if alpha_pct >= -5:
        return "C"
    if alpha_pct >= -15:
        return "D"
    return "F"


def grade_run(
    *,
    scenario: str,
    symbol: str,
    starting_cash: float,
    final_equity: float,
    benchmark_return_pct: float,
    journal: list[JournalEntry],
    equity_curve: list[dict[str, Any]],
    risk_blocks: int = 0,
) -> Grade:
    return_pct = round((final_equity - starting_cash) / starting_cash * 100.0, 2) if starting_cash else 0.0
    alpha = round(return_pct - benchmark_return_pct, 2)
    closed = [e for e in journal if e.closed_at]
    wins = sum(1 for e in closed if e.realized_pl > 0)
    decided = sum(1 for e in closed if e.realized_pl != 0)
    win_rate = round(wins / decided * 100.0, 1) if decided else 0.0
    max_dd = max_drawdown_pct(equity_curve)
    validated = sum(1 for e in closed if e.thesis_outcome == ThesisOutcome.VALIDATED.value)
    invalidated = sum(1 for e in closed if e.thesis_outcome == ThesisOutcome.INVALIDATED.value)
    letter = _letter(alpha, max_dd)

    if alpha >= 0:
        verdict = f"beat buy-and-hold by {alpha:+.1f}%"
    else:
        verdict = f"trailed buy-and-hold by {alpha:.1f}%"
    summary = (
        f"{return_pct:+.1f}% vs {benchmark_return_pct:+.1f}% benchmark ({verdict}); "
        f"{len(journal)} trades, {win_rate:.0f}% win rate, "
        f"max drawdown {max_dd:.0f}%. Grade {letter}."
    )
    return Grade(
        scenario=scenario,
        symbol=symbol,
        starting_cash=round(starting_cash, 2),
        final_equity=round(final_equity, 2),
        return_pct=return_pct,
        benchmark_return_pct=round(benchmark_return_pct, 2),
        alpha_pct=alpha,
        trades=len(journal),
        closed_trades=len(closed),
        win_rate=win_rate,
        max_drawdown_pct=max_dd,
        thesis_validated=validated,
        thesis_invalidated=invalidated,
        risk_blocks=risk_blocks,
        grade_letter=letter,
        summary=summary,
    )


@dataclass
class CoachLesson:
    """A short, mechanical takeaway the Coach derives from a graded run."""

    headline: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def derive_lessons(grade: Grade) -> CoachLesson:
    """Turn a grade into concrete, mechanical coaching notes (no LLM needed)."""
    details: list[str] = []
    if grade.alpha_pct < 0:
        details.append(
            "Underperformed simply holding the asset — the strategy added churn, "
            "not edge. Trade less or improve entry timing."
        )
    if grade.max_drawdown_pct > 30:
        details.append(f"Drawdown hit {grade.max_drawdown_pct:.0f}% — position sizing or stop discipline is too loose.")
    if grade.closed_trades and grade.win_rate < 40:
        details.append(
            f"Win rate {grade.win_rate:.0f}% — many theses were invalidated; tighten the criteria for proposing."
        )
    if grade.risk_blocks:
        details.append(
            f"{grade.risk_blocks} proposals were blocked by risk rules — the "
            "strategy keeps trying trades outside its mandate."
        )
    if not details:
        details.append("Solid run within risk limits. Push to a harder scenario.")
    headline = f"Grade {grade.grade_letter}: {grade.summary}"
    return CoachLesson(headline=headline, details=details)
