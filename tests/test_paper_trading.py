"""Tests for the paper-trading marketplace module.

Covers the safety guards (paper-only, human-approval gate, risk rules), the
store, scoring, the full propose->approve->submit->score loop (offline sim), the
agent tools, and pack/catalog validity.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from thomas.marketplace.paper_trading import (
    PaperTradingEngine,
    load_paper_trading_config,
    register_paper_trading_tools,
)
from thomas.marketplace.paper_trading._exceptions import (
    ApprovalRequired,
    BrokerError,
    LiveTradingBlocked,
    PaperTradingError,
    RiskRejected,
)
from thomas.marketplace.paper_trading._types import (
    AccountSnapshot,
    JournalEntry,
    PositionSnapshot,
    ProposalStatus,
    RiskRules,
    ThesisOutcome,
)
from thomas.marketplace.paper_trading.config import assert_paper
from thomas.marketplace.paper_trading.engine import PaperTradingEngine as _Engine
from thomas.marketplace.paper_trading.risk import evaluate_risk
from thomas.marketplace.paper_trading.scoring import (
    score_open_entry,
    summarize_track_record,
)
from thomas.marketplace.paper_trading.store import PaperTradingStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """Isolate data dir and ensure no real credentials leak in (forces sim broker)."""
    monkeypatch.setenv("THOMAS_PAPER_TRADING_DIR", str(tmp_path))
    for var in (
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
        "ALPACA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.fixture
def engine(clean_env):
    return PaperTradingEngine.build()


# --- safety: paper-only -----------------------------------------------------
def test_assert_paper_blocks_live_endpoint():
    assert assert_paper("https://paper-api.alpaca.markets") is None
    assert assert_paper("https://data.alpaca.markets") is None
    with pytest.raises(LiveTradingBlocked):
        assert_paper("https://api.alpaca.markets")
    with pytest.raises(LiveTradingBlocked):
        assert_paper("http://paper-api.alpaca.markets")  # non-https
    with pytest.raises(LiveTradingBlocked):
        assert_paper("https://evil.example.com")


def test_config_is_paper_locked(clean_env):
    cfg = load_paper_trading_config()
    assert cfg.paper_base_url == "https://paper-api.alpaca.markets"
    assert "paper" in cfg.paper_base_url
    cfg.validate_paper()  # must not raise
    assert cfg.has_credentials is False


def test_simulator_used_without_credentials(engine):
    assert getattr(engine.broker, "is_simulated", False) is True


# --- risk engine ------------------------------------------------------------
def _account(equity=100_000.0):
    return AccountSnapshot(equity=equity, cash=equity, buying_power=equity * 2)


def test_risk_passes_reasonable_order():
    check = evaluate_risk(
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=2,
        notional=None,
        reference_price=150.0,
        rules=RiskRules(),
        account=_account(),
        positions=[],
        trades_today=0,
        market_open=True,
    )
    assert check.passed, check.violations


def test_risk_blocks_oversized_order():
    check = evaluate_risk(
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=None,
        notional=5000.0,
        reference_price=150.0,
        rules=RiskRules(),
        account=_account(),
        positions=[],
        trades_today=0,
        market_open=True,
    )
    assert not check.passed
    assert any("per-order cap" in v for v in check.violations)


def test_risk_blocks_penny_stock():
    check = evaluate_risk(
        symbol="PENNY",
        side="buy",
        order_type="market",
        qty=10,
        notional=None,
        reference_price=0.50,
        rules=RiskRules(),
        account=_account(),
        positions=[],
        trades_today=0,
        market_open=True,
    )
    assert not check.passed
    assert any("minimum" in v for v in check.violations)


def test_risk_blocks_position_concentration():
    pos = PositionSnapshot(
        symbol="AAPL",
        qty=130,
        avg_entry_price=150,
        current_price=150,
        market_value=19_500,
        unrealized_pl=0,
        unrealized_plpc=0,
    )
    check = evaluate_risk(
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=None,
        notional=900.0,
        reference_price=150.0,
        rules=RiskRules(),
        account=_account(),
        positions=[pos],
        trades_today=0,
        market_open=True,
    )
    assert not check.passed
    assert any("of the account" in v for v in check.violations)


def test_risk_blocks_when_market_closed():
    check = evaluate_risk(
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=1,
        notional=None,
        reference_price=150.0,
        rules=RiskRules(),
        account=_account(),
        positions=[],
        trades_today=0,
        market_open=False,
    )
    assert not check.passed
    assert any("market is closed" in v for v in check.violations)


def test_risk_blocks_daily_trade_cap():
    check = evaluate_risk(
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=1,
        notional=None,
        reference_price=150.0,
        rules=RiskRules(max_trades_per_day=3),
        account=_account(),
        positions=[],
        trades_today=3,
        market_open=True,
    )
    assert not check.passed


def test_risk_respects_symbol_allowlist():
    rules = RiskRules(symbol_allowlist=("SPY", "QQQ"))
    blocked = evaluate_risk(
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=1,
        notional=None,
        reference_price=150.0,
        rules=rules,
        account=_account(),
        positions=[],
        trades_today=0,
        market_open=True,
    )
    assert not blocked.passed
    allowed = evaluate_risk(
        symbol="SPY",
        side="buy",
        order_type="market",
        qty=1,
        notional=None,
        reference_price=150.0,
        rules=rules,
        account=_account(),
        positions=[],
        trades_today=0,
        market_open=True,
    )
    assert allowed.passed, allowed.violations


# --- scoring ----------------------------------------------------------------
def test_score_open_then_close_validates_winning_long():
    e = JournalEntry(
        id="j1",
        proposal_id="p1",
        symbol="AAPL",
        side="buy",
        qty=10,
        entry_price=100.0,
        thesis="up",
        invalidation="down",
    )
    score_open_entry(e, current_price=110.0, still_open=True)
    assert e.thesis_outcome == ThesisOutcome.OPEN.value
    assert e.unrealized_pl == pytest.approx(100.0)
    score_open_entry(e, current_price=110.0, still_open=False)
    assert e.thesis_outcome == ThesisOutcome.VALIDATED.value
    assert e.realized_pl == pytest.approx(100.0)
    assert e.closed_at


def test_score_invalidates_losing_long():
    e = JournalEntry(
        id="j2",
        proposal_id="p2",
        symbol="AAPL",
        side="buy",
        qty=10,
        entry_price=100.0,
        thesis="up",
        invalidation="down",
    )
    score_open_entry(e, current_price=90.0, still_open=False)
    assert e.thesis_outcome == ThesisOutcome.INVALIDATED.value
    assert e.realized_pl < 0


def test_score_short_direction_aware():
    e = JournalEntry(
        id="j3",
        proposal_id="p3",
        symbol="AAPL",
        side="sell",
        qty=10,
        entry_price=100.0,
        thesis="down",
        invalidation="up",
    )
    # Price falls -> a short wins.
    score_open_entry(e, current_price=90.0, still_open=False)
    assert e.thesis_outcome == ThesisOutcome.VALIDATED.value
    assert e.realized_pl > 0


def test_track_record_summary():
    entries = [
        JournalEntry(
            id="a",
            proposal_id="p",
            symbol="X",
            side="buy",
            qty=1,
            entry_price=10,
            thesis="t",
            invalidation="i",
            realized_pl=5,
            closed_at="2026-01-01T00:00:00Z",
            thesis_outcome="validated",
        ),
        JournalEntry(
            id="b",
            proposal_id="p",
            symbol="Y",
            side="buy",
            qty=1,
            entry_price=10,
            thesis="t",
            invalidation="i",
            realized_pl=-3,
            closed_at="2026-01-01T00:00:00Z",
            thesis_outcome="invalidated",
        ),
    ]
    tr = summarize_track_record(entries)
    assert tr.closed_count == 2
    assert tr.wins == 1 and tr.losses == 1
    assert tr.win_rate == 50.0
    assert tr.total_realized_pl == pytest.approx(2.0)


# --- the full loop ----------------------------------------------------------
def test_full_loop_propose_approve_submit_score(engine):
    proposal = run(
        engine.propose(
            symbol="MSFT",
            side="buy",
            thesis="earnings beat",
            invalidation="breaks below support",
            notional=500,
        )
    )
    assert proposal.status == ProposalStatus.PENDING_APPROVAL.value

    approved = engine.approve(proposal.id, approver="owner")
    assert approved.status == ProposalStatus.APPROVED.value

    submitted = run(engine.submit(proposal.id))
    assert submitted.status in (
        ProposalStatus.SUBMITTED.value,
        ProposalStatus.FILLED.value,
    )
    assert submitted.broker_order_id

    entries = run(engine.reconcile())
    assert len(entries) == 1
    assert entries[0].symbol == "MSFT"

    review = engine.review()
    assert review["track_record"]["total"] == 1


def test_submit_refused_without_approval(engine):
    proposal = run(
        engine.propose(
            symbol="AAPL",
            side="buy",
            thesis="t",
            invalidation="i",
            notional=300,
        )
    )
    with pytest.raises(ApprovalRequired):
        run(engine.submit(proposal.id))


def test_blocked_by_risk_cannot_be_approved(engine):
    proposal = run(
        engine.propose(
            symbol="AAPL",
            side="buy",
            thesis="t",
            invalidation="i",
            notional=999_999,
        )
    )
    assert proposal.status == ProposalStatus.BLOCKED_BY_RISK.value
    with pytest.raises(ApprovalRequired):
        engine.approve(proposal.id)


def test_daily_trade_cap_enforced_across_proposals(clean_env, monkeypatch):
    monkeypatch.setenv("THOMAS_PAPER_MAX_TRADES_PER_DAY", "2")
    eng = PaperTradingEngine.build()
    assert eng.config.risk.max_trades_per_day == 2
    for _ in range(2):
        p = run(eng.propose(symbol="SPY", side="buy", thesis="t", invalidation="i", notional=200))
        eng.approve(p.id)
        run(eng.submit(p.id))
    blocked = run(eng.propose(symbol="SPY", side="buy", thesis="t", invalidation="i", notional=200))
    assert blocked.status == ProposalStatus.BLOCKED_BY_RISK.value


# --- agent tools ------------------------------------------------------------
def test_tools_register_and_expose_paper_category(clean_env):
    from thomas.tools.registry import ToolRegistry

    reg = ToolRegistry()
    register_paper_trading_tools(reg)
    names = {t.name for t in reg.list_tools(category="paper_trading")}
    assert {
        "paper_trading.account",
        "paper_trading.quote",
        "paper_trading.propose",
        "paper_trading.submit",
        "paper_trading.review",
    }.issubset(names)


def test_propose_tool_requires_thesis_and_invalidation(clean_env):
    from thomas.marketplace.paper_trading.tools import PaperTradingProposeTool

    tool = PaperTradingProposeTool()
    res = run(tool.execute({"symbol": "AAPL", "side": "buy", "notional": 100}))
    assert res.ok is False
    assert "thesis" in (res.error or "").lower()


def test_account_tool_returns_data(clean_env):
    from thomas.marketplace.paper_trading.tools import PaperTradingAccountTool

    res = run(PaperTradingAccountTool().execute({}))
    assert res.ok is True
    assert "equity" in res.data


def test_submit_tool_refuses_unapproved(clean_env):
    from thomas.marketplace.paper_trading.tools import (
        PaperTradingProposeTool,
        PaperTradingSubmitTool,
    )

    proposed = run(
        PaperTradingProposeTool().execute(
            {
                "symbol": "AAPL",
                "side": "buy",
                "thesis": "t",
                "invalidation": "i",
                "notional": 200,
            }
        )
    )
    assert proposed.ok
    res = run(PaperTradingSubmitTool().execute({"proposal_id": proposed.data["id"]}))
    assert res.ok is False
    assert "approved" in (res.error or "").lower()


# --- pack + catalog validity ------------------------------------------------
def test_manifest_has_required_keys_and_healthcheck():
    manifest = json.loads((REPO_ROOT / "extensions" / "paper-trading" / "manifest.json").read_text(encoding="utf-8"))
    for key in ("id", "name", "version", "entrypoint", "capabilities"):
        assert key in manifest, f"missing manifest key {key}"
    assert manifest["id"] == "paper-trading"
    assert "healthcheck" in manifest["capabilities"]


def test_pack_files_exist():
    base = REPO_ROOT / "extensions" / "paper-trading"
    for rel in ("manifest.json", "hooks.py", "README.md", "web/index.html"):
        assert (base / rel).exists(), f"missing {rel}"


def test_catalog_contains_paper_trading():
    catalog = json.loads((REPO_ROOT / "extensions" / "catalog.json").read_text(encoding="utf-8"))
    ids = {p.get("id") for p in catalog.get("packs", [])}
    assert "paper-trading" in ids


def test_hooks_healthcheck_reports_paper_only():
    import importlib.util

    path = REPO_ROOT / "extensions" / "paper-trading" / "hooks.py"
    spec = importlib.util.spec_from_file_location("paper_trading_hooks", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    health = mod.healthcheck()
    assert health["ok"] is True
    assert health["paper_only"] is True


# --- hardening fixes from the adversarial review ----------------------------
class _FailBroker:
    """Broker whose every call raises — to exercise fail-closed behavior."""

    is_simulated = False

    async def get_latest_quote(self, symbol):
        raise BrokerError("data feed down")

    async def get_account(self):
        raise BrokerError("broker down")

    async def list_positions(self):
        raise BrokerError("broker down")

    async def is_market_open(self):
        raise BrokerError("clock down")

    async def submit_order(self, **kwargs):
        raise BrokerError("broker down")


def test_propose_fails_closed_on_broker_outage(clean_env):
    cfg = load_paper_trading_config()
    eng = _Engine(cfg, PaperTradingStore(cfg.state_path), _FailBroker())
    # Even a notional order (otherwise within the cap) must be blocked when the
    # data needed to risk-check it is unavailable.
    p = run(eng.propose(symbol="AAPL", side="buy", thesis="t", invalidation="i", notional=200))
    assert p.status == ProposalStatus.BLOCKED_BY_RISK.value


def test_invalid_symbol_rejected(engine):
    with pytest.raises(PaperTradingError):
        run(
            engine.propose(
                symbol="<img src=x onerror=alert(1)>", side="buy", thesis="t", invalidation="i", notional=100
            )
        )


def test_invalid_side_and_order_type_rejected(engine):
    with pytest.raises(PaperTradingError):
        run(engine.propose(symbol="AAPL", side="hodl", thesis="t", invalidation="i", notional=100))


def test_reject_refused_on_filled_proposal(engine):
    p = run(engine.propose(symbol="AAPL", side="buy", thesis="t", invalidation="i", notional=200))
    engine.approve(p.id)
    run(engine.submit(p.id))
    with pytest.raises(ApprovalRequired):
        engine.reject(p.id)


def test_daily_cap_enforced_at_submit_even_if_preapproved(clean_env, monkeypatch):
    # The bypass the review found: propose many BEFORE submitting any (each sees
    # trades_today=0), approve all, then try to submit past the cap.
    monkeypatch.setenv("THOMAS_PAPER_MAX_TRADES_PER_DAY", "2")
    eng = PaperTradingEngine.build()
    props = [run(eng.propose(symbol="SPY", side="buy", thesis="t", invalidation="i", notional=150)) for _ in range(3)]
    assert all(p.status == ProposalStatus.PENDING_APPROVAL.value for p in props)
    for p in props:
        eng.approve(p.id)
    run(eng.submit(props[0].id))
    run(eng.submit(props[1].id))
    with pytest.raises(RiskRejected):
        run(eng.submit(props[2].id))
    assert eng.store.get_proposal(props[2].id).status == ProposalStatus.BLOCKED_BY_RISK.value


def test_env_override_cannot_disable_guard(clean_env, monkeypatch):
    monkeypatch.setenv("THOMAS_PAPER_MAX_ORDER_USD", "0")
    monkeypatch.setenv("THOMAS_PAPER_MAX_TRADES_PER_DAY", "-5")
    cfg = load_paper_trading_config()
    assert cfg.risk.max_order_usd == 1000.0
    assert cfg.risk.max_trades_per_day == 10


def test_recall_returns_structure_with_small_sample_caveat(engine):
    out = engine.recall("AAPL")
    assert "lessons" in out
    assert "small_sample_caveat" in out
    assert out["closed_trades"] == 0
    assert out["small_sample_caveat"]  # non-empty when under 10 closed trades
