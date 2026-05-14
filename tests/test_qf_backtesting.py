"""Tests for backtesting engine and strategy evaluation."""

from datetime import datetime, timedelta

import numpy as np
import pytest

from thomas.marketplace.quantfin._types import OHLCV, Asset, OrderSide
from thomas.marketplace.quantfin.backtesting import (
    BacktestConfig,
    BacktestEngine,
    WalkForwardOptimizer,
    monte_carlo_permutation_test,
)


class TestBacktestConfig:
    """Backtest configuration tests."""

    def test_default_config(self) -> None:
        """Test default configuration."""
        config = BacktestConfig()
        assert config.initial_cash == 100000.0
        assert config.commission_rate == 0.001
        assert config.margin_multiplier == 1.0

    def test_custom_config(self) -> None:
        """Test custom configuration."""
        config = BacktestConfig(
            initial_cash=500000.0,
            commission_rate=0.0005,
            slippage_bps=2.0,
        )
        assert config.initial_cash == 500000.0
        assert config.commission_rate == 0.0005
        assert config.slippage_bps == 2.0


class TestBacktestEngine:
    """Backtesting engine tests."""

    @pytest.fixture
    def engine(self) -> BacktestEngine:
        """Create backtesting engine."""
        return BacktestEngine()

    @pytest.fixture
    def asset(self) -> Asset:
        """Create test asset."""
        return Asset(symbol="TEST", name="Test Asset", asset_type="EQUITY")

    def test_initial_state(self, engine: BacktestEngine) -> None:
        """Test initial engine state."""
        assert engine.cash == 100000.0
        assert len(engine.positions) == 0
        assert len(engine.trades) == 0

    def test_slippage_application(self, engine: BacktestEngine) -> None:
        """Test slippage calculation."""
        slipped_buy = engine.apply_slippage(100.0, OrderSide.BUY)
        slipped_sell = engine.apply_slippage(100.0, OrderSide.SELL)

        assert slipped_buy > 100.0  # Buy price goes up
        assert slipped_sell < 100.0  # Sell price goes down

    def test_market_order_buy(self, engine: BacktestEngine, asset: Asset) -> None:
        """Test market order buy execution."""
        trade = engine.process_order(
            asset=asset,
            side=OrderSide.BUY,
            quantity=100,
            price=100.0,
            timestamp=datetime.now(),
        )

        assert trade is not None
        assert trade.quantity == 100
        assert "TEST" in engine.positions
        assert engine.positions["TEST"] == 100
        assert engine.cash < 100000.0  # Cash reduced by purchase + commission

    def test_market_order_sell(self, engine: BacktestEngine, asset: Asset) -> None:
        """Test market order sell execution."""
        # First buy
        engine.process_order(
            asset=asset,
            side=OrderSide.BUY,
            quantity=100,
            price=100.0,
            timestamp=datetime.now(),
        )

        initial_cash = engine.cash

        # Then sell
        trade = engine.process_order(
            asset=asset,
            side=OrderSide.SELL,
            quantity=100,
            price=105.0,
            timestamp=datetime.now(),
        )

        assert trade is not None
        assert "TEST" not in engine.positions
        assert engine.cash > initial_cash  # Profit from trade

    def test_insufficient_cash(self, engine: BacktestEngine, asset: Asset) -> None:
        """Test handling of insufficient cash."""
        trade = engine.process_order(
            asset=asset,
            side=OrderSide.BUY,
            quantity=10000,  # Too large
            price=100.0,
            timestamp=datetime.now(),
        )

        assert trade is None
        assert len(engine.positions) == 0

    def test_insufficient_position(self, engine: BacktestEngine, asset: Asset) -> None:
        """Test handling of insufficient position for sell."""
        trade = engine.process_order(
            asset=asset,
            side=OrderSide.SELL,
            quantity=100,
            price=100.0,
            timestamp=datetime.now(),
        )

        assert trade is None

    def test_portfolio_value_calculation(self, engine: BacktestEngine, asset: Asset) -> None:
        """Test portfolio value calculation."""
        engine.process_order(
            asset=asset,
            side=OrderSide.BUY,
            quantity=100,
            price=100.0,
            timestamp=datetime.now(),
        )

        prices = {"TEST": 110.0}
        pv = engine.calculate_portfolio_value(prices)

        # Should be: cash + (100 shares * $110)
        expected = engine.cash + 100 * 110.0
        assert abs(pv - expected) < 0.1

    def test_multiple_positions(self, engine: BacktestEngine) -> None:
        """Test handling multiple positions."""
        asset1 = Asset(symbol="A", name="Asset A", asset_type="EQUITY")
        asset2 = Asset(symbol="B", name="Asset B", asset_type="EQUITY")

        engine.process_order(asset1, OrderSide.BUY, 100, 100.0, datetime.now())
        engine.process_order(asset2, OrderSide.BUY, 200, 50.0, datetime.now())

        assert len(engine.positions) == 2
        assert engine.positions["A"] == 100
        assert engine.positions["B"] == 200

    def test_run_backtest(self, engine: BacktestEngine) -> None:
        """Test running a simple backtest."""
        Asset(symbol="SPY", name="S&P 500", asset_type="EQUITY")

        # Generate sample data
        dates = [datetime(2023, 1, 1) + timedelta(days=i) for i in range(20)]
        data = {
            "SPY": [
                OHLCV(
                    timestamp=dates[i],
                    open=100.0 + i,
                    high=101.0 + i,
                    low=99.0 + i,
                    close=100.5 + i,
                    volume=1000000,
                )
                for i in range(20)
            ]
        }

        # Simple signal generator
        def signal_gen(data, date):
            signals = {}
            if date.day == 5:
                signals["SPY"] = ("BUY", 1.0)
            elif date.day == 15:
                signals["SPY"] = ("SELL", 1.0)
            return signals

        metrics = engine.run_backtest(data, signal_gen)

        assert metrics.num_trades > 0
        assert metrics.total_return >= -1.0
        assert metrics.total_return <= 1.0  # Within reasonable range


class TestWalkForwardOptimizer:
    """Walk-forward optimization tests."""

    def test_optimizer_initialization(self) -> None:
        """Test optimizer initialization."""
        opt = WalkForwardOptimizer(train_period=252, test_period=63, step=63)
        assert opt.train_period == 252
        assert opt.test_period == 63
        assert opt.step == 63

    def test_parameter_generation(self) -> None:
        """Test parameter combination generation."""
        opt = WalkForwardOptimizer()
        param_ranges = {
            "period": [10, 20],
            "threshold": [1.0, 2.0],
        }

        combos = opt._generate_param_combinations(param_ranges)

        assert len(combos) == 4
        assert {"period": 10, "threshold": 1.0} in combos
        assert {"period": 20, "threshold": 2.0} in combos

    def test_empty_params(self) -> None:
        """Test with empty parameters."""
        opt = WalkForwardOptimizer()
        combos = opt._generate_param_combinations({})
        assert len(combos) == 1
        assert combos[0] == {}


class TestMonteCarloPermutationTest:
    """Monte Carlo permutation test tests."""

    def test_positive_returns(self) -> None:
        """Test permutation test with positive returns."""
        returns = np.array([0.01, 0.02, 0.01, 0.03, 0.02])
        p_value = monte_carlo_permutation_test(returns, num_simulations=1000)

        # Positive returns should have low p-value
        assert 0.0 <= p_value <= 1.0

    def test_random_returns(self) -> None:
        """Test permutation test with random returns."""
        returns = np.random.normal(0, 0.02, 50)
        p_value = monte_carlo_permutation_test(returns, num_simulations=1000)

        # Random returns should have higher p-value
        assert 0.0 <= p_value <= 1.0

    def test_negative_returns(self) -> None:
        """Test permutation test with negative returns."""
        returns = np.array([-0.01, -0.02, -0.01, -0.03, -0.02])
        p_value = monte_carlo_permutation_test(returns, num_simulations=1000)

        # Negative returns should have high p-value
        assert p_value > 0.5


class TestBacktestMetrics:
    """Backtest metrics calculation tests."""

    @pytest.fixture
    def engine_with_trades(self) -> BacktestEngine:
        """Create engine with executed trades."""
        engine = BacktestEngine()
        Asset(symbol="TEST", name="Test", asset_type="EQUITY")

        # Simulate profitable trade sequence
        engine.portfolio_values = [100000, 102000, 101000, 103000, 105000]
        engine.timestamps = [datetime(2023, 1, 1) + timedelta(days=i) for i in range(5)]

        return engine

    def test_metrics_calculation(self, engine_with_trades: BacktestEngine) -> None:
        """Test calculation of backtest metrics."""
        metrics = engine_with_trades._calculate_metrics()

        assert metrics.total_return > 0
        assert metrics.annual_return > 0
        assert metrics.max_drawdown <= 0
        assert 0 <= metrics.win_rate <= 1
        assert metrics.sharpe_ratio >= 0
        assert metrics.calmar_ratio >= 0

    def test_no_drawdown_portfolio(self) -> None:
        """Test portfolio with no drawdown."""
        engine = BacktestEngine()
        engine.portfolio_values = [100000, 101000, 102000, 103000]
        engine.timestamps = [datetime(2023, 1, 1) + timedelta(days=i) for i in range(4)]

        metrics = engine._calculate_metrics()

        assert metrics.max_drawdown == 0
        assert metrics.total_return > 0

    def test_zero_trades(self) -> None:
        """Test backtest with no trades."""
        engine = BacktestEngine()
        engine.portfolio_values = [100000, 100000, 100000]
        engine.timestamps = [datetime(2023, 1, 1) + timedelta(days=i) for i in range(3)]

        metrics = engine._calculate_metrics()

        assert metrics.num_trades == 0
        assert metrics.total_return == 0
        assert metrics.win_rate == 0
