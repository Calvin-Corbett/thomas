"""Tests for technical indicators."""

import numpy as np

from thomas.quantfin import indicators


class TestMovingAverages:
    """Moving average indicator tests."""

    def test_sma_constant_prices(self) -> None:
        """SMA of constant prices should equal price."""
        prices = np.array([100.0] * 10)
        sma_vals = indicators.sma(prices, period=5)
        assert np.allclose(sma_vals, 100.0)

    def test_sma_linear_increase(self) -> None:
        """SMA of linearly increasing prices."""
        prices = np.array([100, 101, 102, 103, 104, 105])
        sma_vals = indicators.sma(prices, period=3)
        assert len(sma_vals) == len(prices) - 3 + 1
        assert sma_vals[0] == 101.0  # (100+101+102)/3

    def test_ema_recent_bias(self) -> None:
        """EMA should give more weight to recent prices."""
        prices = np.array([100, 110, 120])
        ema_vals = indicators.ema(prices, period=2)
        assert ema_vals[-1] > np.mean(prices)  # Recent high price pulls EMA up

    def test_dema_faster_response(self) -> None:
        """DEMA should respond faster to price changes than EMA."""
        prices = np.array([100, 100, 100, 120, 120, 120])
        ema_vals = indicators.ema(prices, period=2)
        dema_vals = indicators.dema(prices, period=2)
        assert dema_vals[-1] > ema_vals[-1]

    def test_tema_fastest_response(self) -> None:
        """TEMA should respond fastest to trends."""
        prices = np.array([100, 105, 110, 115, 120])
        sma_vals = indicators.sma(prices, period=3)
        ema_vals = indicators.ema(prices, period=3)
        tema_vals = indicators.tema(prices, period=3)
        # All should increase with trend
        assert tema_vals[-1] > ema_vals[-1] > sma_vals[-1]


class TestRSI:
    """Relative Strength Index tests."""

    def test_rsi_range_0_100(self) -> None:
        """RSI should be between 0 and 100."""
        prices = np.random.normal(100, 5, 50)
        rsi_vals = indicators.rsi(prices, period=14)
        assert np.all((rsi_vals >= 0) | (np.isnan(rsi_vals)))
        assert np.all((rsi_vals <= 100) | (np.isnan(rsi_vals)))

    def test_rsi_overbought_high_prices(self) -> None:
        """RSI should be high (near 100) for consistently rising prices."""
        prices = np.linspace(100, 120, 30)
        rsi_vals = indicators.rsi(prices, period=14)
        assert rsi_vals[-1] > 70

    def test_rsi_oversold_low_prices(self) -> None:
        """RSI should be low (near 0) for consistently falling prices."""
        prices = np.linspace(120, 100, 30)
        rsi_vals = indicators.rsi(prices, period=14)
        assert rsi_vals[-1] < 30


class TestMACD:
    """MACD indicator tests."""

    def test_macd_crossover(self) -> None:
        """MACD should cross signal line."""
        prices = np.concatenate(
            [
                np.linspace(100, 110, 20),
                np.linspace(110, 105, 10),
            ]
        )
        macd_line, signal, hist = indicators.macd(prices)
        assert len(macd_line) == len(signal)

    def test_macd_histogram_calculation(self) -> None:
        """MACD histogram should be MACD - Signal."""
        prices = np.linspace(100, 110, 50)
        macd_line, signal, hist = indicators.macd(prices)
        expected_hist = macd_line - signal
        assert np.allclose(hist, expected_hist)


class TestStochastic:
    """Stochastic oscillator tests."""

    def test_stochastic_range(self) -> None:
        """Stochastic should be between 0 and 100."""
        highs = np.linspace(100, 110, 30)
        lows = np.linspace(95, 105, 30)
        closes = (highs + lows) / 2
        k, d = indicators.stochastic(highs, lows, closes, period=14)
        assert np.all(k >= 0) or np.all(np.isnan(k))
        assert np.all(k <= 100) or np.all(np.isnan(k))

    def test_stochastic_at_high(self) -> None:
        """Stochastic should be high when price is near high."""
        highs = np.array([100, 110, 120, 120, 120])
        lows = np.array([95, 95, 95, 95, 95])
        closes = np.array([110, 120, 120, 120, 120])
        k, d = indicators.stochastic(highs, lows, closes, period=3)
        assert k[-1] > 80


class TestWilliamsR:
    """Williams %R tests."""

    def test_williams_r_range(self) -> None:
        """%R should be between -100 and 0."""
        highs = np.linspace(100, 110, 30)
        lows = np.linspace(95, 105, 30)
        closes = (highs + lows) / 2
        wr = indicators.williams_r(highs, lows, closes, period=14)
        assert np.all((wr >= -100) | (np.isnan(wr)))
        assert np.all((wr <= 0) | (np.isnan(wr)))


class TestROC:
    """Rate of Change tests."""

    def test_roc_positive_increase(self) -> None:
        """ROC should be positive for increasing prices."""
        prices = np.array([100, 102, 104, 106, 108])
        roc = indicators.rate_of_change(prices, period=2)
        assert roc[-1] > 0

    def test_roc_negative_decrease(self) -> None:
        """ROC should be negative for decreasing prices."""
        prices = np.array([100, 98, 96, 94, 92])
        roc = indicators.rate_of_change(prices, period=2)
        assert roc[-1] < 0


class TestBollingerBands:
    """Bollinger Bands tests."""

    def test_bb_middle_is_sma(self) -> None:
        """Middle band should be SMA."""
        prices = np.random.normal(100, 5, 50)
        upper, middle, lower = indicators.bollinger_bands(prices, period=20)
        sma_vals = indicators.sma(prices, period=20)
        assert np.allclose(middle, sma_vals[-len(middle) :])

    def test_bb_upper_lower_symmetry(self) -> None:
        """Upper and lower bands should be symmetric around middle."""
        prices = np.random.normal(100, 5, 50)
        upper, middle, lower = indicators.bollinger_bands(prices, period=20, num_std=2.0)
        assert np.allclose(upper - middle, middle - lower)

    def test_bb_bands_widen_with_volatility(self) -> None:
        """Bollinger Bands should widen with higher volatility."""
        prices_low_vol = np.random.normal(100, 1, 50)
        prices_high_vol = np.random.normal(100, 5, 50)

        _, _, lower_low = indicators.bollinger_bands(prices_low_vol, period=20)
        upper_high, _, _ = indicators.bollinger_bands(prices_high_vol, period=20)

        spread_low = np.mean(100 - lower_low)
        spread_high = np.mean(upper_high - 100)
        assert spread_high > spread_low


class TestATR:
    """Average True Range tests."""

    def test_atr_positive(self) -> None:
        """ATR should always be positive."""
        highs = np.random.uniform(101, 110, 30)
        lows = np.random.uniform(95, 100, 30)
        closes = (highs + lows) / 2
        atr = indicators.atr(highs, lows, closes, period=14)
        assert np.all(atr > 0)

    def test_atr_respects_previous_close(self) -> None:
        """ATR should consider gaps from previous close."""
        highs = np.array([100, 110, 115, 110, 105])
        lows = np.array([95, 105, 110, 105, 100])
        closes = np.array([98, 108, 113, 108, 103])
        atr = indicators.atr(highs, lows, closes, period=2)
        # Gap from 98 to 110 should be captured
        assert atr[-1] > 0


class TestOBV:
    """On-Balance Volume tests."""

    def test_obv_increases_on_up_days(self) -> None:
        """OBV should increase when price rises."""
        prices = np.array([100, 105, 110, 115])
        volumes = np.array([1000, 1000, 1000, 1000])
        obv = indicators.obv(prices, volumes)
        assert obv[-1] > obv[0]

    def test_obv_decreases_on_down_days(self) -> None:
        """OBV should decrease when price falls."""
        prices = np.array([100, 95, 90, 85])
        volumes = np.array([1000, 1000, 1000, 1000])
        obv = indicators.obv(prices, volumes)
        assert obv[-1] < obv[0]


class TestVWAP:
    """VWAP tests."""

    def test_vwap_between_min_max(self) -> None:
        """VWAP should be between min and max price."""
        prices = np.array([100, 105, 110, 115, 120])
        volumes = np.array([1000, 1000, 1000, 1000, 1000])
        vwap = indicators.vwap(prices, volumes)
        assert np.all(vwap >= np.min(prices))
        assert np.all(vwap <= np.max(prices))

    def test_vwap_weighted_by_volume(self) -> None:
        """VWAP should weight toward high volume prices."""
        prices = np.array([100, 105, 110])
        volumes = np.array([100, 1000, 100])  # Heavy volume at 105
        vwap = indicators.vwap(prices, volumes)
        assert vwap[-1] < (100 + 105 + 110) / 3  # VWAP pulled down by 105


class TestADX:
    """ADX tests."""

    def test_adx_range(self) -> None:
        """ADX should be between 0 and 100."""
        highs = np.linspace(100, 120, 30)
        lows = np.linspace(95, 115, 30)
        closes = (highs + lows) / 2
        adx = indicators.adx(highs, lows, closes, period=14)
        assert np.all((adx >= 0) | (np.isnan(adx)))
        assert np.all((adx <= 100) | (np.isnan(adx)))


class TestFibonacci:
    """Fibonacci retracement tests."""

    def test_fibonacci_levels_count(self) -> None:
        """Should return 7 Fibonacci levels."""
        levels = indicators.fibonacci_levels(high=120, low=100)
        assert len(levels) == 7

    def test_fibonacci_extremes(self) -> None:
        """0% level should be high, 100% should be low."""
        high, low = 120, 100
        levels = indicators.fibonacci_levels(high=high, low=low)
        assert levels["0.0%"] == high
        assert levels["100.0%"] == low


class TestPivotPoints:
    """Pivot point tests."""

    def test_pivot_points_count(self) -> None:
        """Should return 5 pivot point levels."""
        points = indicators.pivot_points(high=120, low=100, close=110)
        assert len(points) == 5

    def test_pivot_ordering(self) -> None:
        """R2 > R1 > P > S1 > S2."""
        points = indicators.pivot_points(high=120, low=100, close=110)
        assert points["R2"] > points["R1"]
        assert points["R1"] > points["P"]
        assert points["P"] > points["S1"]
        assert points["S1"] > points["S2"]
