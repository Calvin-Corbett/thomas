"""Technical indicators for trading."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class IndicatorValue:
    """Single indicator value with optional signal line.

    Attributes:
        value: Main indicator value
        signal: Optional signal line (e.g., MACD signal line)
        histogram: Optional histogram (e.g., MACD histogram)
    """

    value: float
    signal: float | None = None
    histogram: float | None = None


def sma(prices: np.ndarray, period: int = 20) -> np.ndarray:
    """Simple moving average.

    Args:
        prices: Price series
        period: Period (default: 20)

    Returns:
        SMA values
    """
    if len(prices) < period:
        raise ValueError("Series too short for period")

    return np.convolve(prices, np.ones(period) / period, mode="valid")


def ema(prices: np.ndarray, period: int = 20) -> np.ndarray:
    """Exponential moving average.

    Args:
        prices: Price series
        period: Period (default: 20)

    Returns:
        EMA values
    """
    if len(prices) < period:
        raise ValueError("Series too short for period")

    alpha = 2.0 / (period + 1)
    ema_values = np.zeros(len(prices))
    ema_values[0] = np.mean(prices[:period])

    for i in range(1, len(prices)):
        ema_values[i] = alpha * prices[i] + (1 - alpha) * ema_values[i - 1]

    return ema_values


def wma(prices: np.ndarray, period: int = 20) -> np.ndarray:
    """Weighted moving average (linearly weighted).

    Args:
        prices: Price series
        period: Period

    Returns:
        WMA values
    """
    if len(prices) < period:
        raise ValueError("Series too short for period")

    weights = np.arange(1, period + 1)
    wma_values = np.zeros(len(prices) - period + 1)

    for i in range(len(wma_values)):
        wma_values[i] = np.average(prices[i : i + period], weights=weights)

    return wma_values


def dema(prices: np.ndarray, period: int = 20) -> np.ndarray:
    """Double exponential moving average.

    DEMA = 2*EMA - EMA(EMA)

    Args:
        prices: Price series
        period: Period

    Returns:
        DEMA values
    """
    ema1 = ema(prices, period)
    ema2 = ema(ema1, period)
    dema_values = 2 * ema1 - ema2

    return dema_values


def tema(prices: np.ndarray, period: int = 20) -> np.ndarray:
    """Triple exponential moving average.

    TEMA = 3*EMA - 3*EMA(EMA) + EMA(EMA(EMA))

    Args:
        prices: Price series
        period: Period

    Returns:
        TEMA values
    """
    ema1 = ema(prices, period)
    ema2 = ema(ema1, period)
    ema3 = ema(ema2, period)
    tema_values = 3 * ema1 - 3 * ema2 + ema3

    return tema_values


def rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index.

    RSI = 100 * (1 - 1/(1 + RS)) where RS = avg_gain / avg_loss

    Args:
        prices: Price series
        period: Period (default: 14)

    Returns:
        RSI values (0-100)
    """
    if len(prices) < period + 1:
        raise ValueError("Series too short for period")

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.zeros(len(prices))
    avg_loss = np.zeros(len(prices))

    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])

    for i in range(period + 1, len(prices)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period

    rs = np.where(avg_loss != 0, avg_gain / avg_loss, 0)
    rsi_values = 100 - 100 / (1 + rs)

    return rsi_values


def macd(
    prices: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD (Moving Average Convergence Divergence).

    Args:
        prices: Price series
        fast: Fast EMA period (default: 12)
        slow: Slow EMA period (default: 26)
        signal_period: Signal line EMA period (default: 9)

    Returns:
        Tuple of (MACD line, signal line, histogram)
    """
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)

    # Trim to same length
    min_len = min(len(ema_fast), len(ema_slow))
    macd_line = ema_fast[-min_len:] - ema_slow[-min_len:]

    signal_line = ema(macd_line, signal_period)
    histogram = macd_line[-len(signal_line) :] - signal_line

    return macd_line[-len(signal_line) :], signal_line, histogram


def stochastic(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
    smooth_k: int = 3,
    smooth_d: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Stochastic oscillator.

    Args:
        highs: High prices
        lows: Low prices
        closes: Close prices
        period: Period (default: 14)
        smooth_k: Smoothing for %K (default: 3)
        smooth_d: Smoothing for %D (default: 3)

    Returns:
        Tuple of (%K line, %D line)
    """
    if len(closes) < period:
        raise ValueError("Series too short for period")

    stoch_raw = np.zeros(len(closes))

    for i in range(period - 1, len(closes)):
        high_max = np.max(highs[i - period + 1 : i + 1])
        low_min = np.min(lows[i - period + 1 : i + 1])

        if high_max == low_min:
            stoch_raw[i] = 50
        else:
            stoch_raw[i] = 100 * (closes[i] - low_min) / (high_max - low_min)

    # Smooth %K
    percent_k = sma(stoch_raw[period - 1 :], smooth_k)
    percent_d = sma(percent_k, smooth_d)

    return percent_k, percent_d


def williams_r(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Williams %R oscillator.

    %R = -100 * (H - C) / (H - L)

    Args:
        highs: High prices
        lows: Low prices
        closes: Close prices
        period: Period

    Returns:
        Williams %R values (-100 to 0)
    """
    if len(closes) < period:
        raise ValueError("Series too short for period")

    williams_r_values = np.zeros(len(closes))

    for i in range(period - 1, len(closes)):
        high_max = np.max(highs[i - period + 1 : i + 1])
        low_min = np.min(lows[i - period + 1 : i + 1])

        if high_max == low_min:
            williams_r_values[i] = -50
        else:
            williams_r_values[i] = -100 * (high_max - closes[i]) / (high_max - low_min)

    return williams_r_values


def rate_of_change(prices: np.ndarray, period: int = 12) -> np.ndarray:
    """Rate of change (momentum).

    ROC = 100 * (price - price_n_periods_ago) / price_n_periods_ago

    Args:
        prices: Price series
        period: Period

    Returns:
        ROC values
    """
    if len(prices) < period + 1:
        raise ValueError("Series too short for period")

    roc = np.zeros(len(prices))
    for i in range(period, len(prices)):
        roc[i] = 100 * (prices[i] - prices[i - period]) / prices[i - period]

    return roc


def bollinger_bands(
    prices: np.ndarray,
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands.

    Args:
        prices: Price series
        period: Period (default: 20)
        num_std: Number of standard deviations (default: 2.0)

    Returns:
        Tuple of (upper band, middle band, lower band)
    """
    middle = sma(prices, period)
    std_dev = np.zeros(len(prices) - period + 1)

    for i in range(len(std_dev)):
        std_dev[i] = np.std(prices[i : i + period])

    upper = middle + num_std * std_dev
    lower = middle - num_std * std_dev

    return upper, middle, lower


def atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Average True Range.

    Args:
        highs: High prices
        lows: Low prices
        closes: Close prices
        period: Period

    Returns:
        ATR values
    """
    if len(closes) < period:
        raise ValueError("Series too short for period")

    tr = np.zeros(len(closes))

    tr[0] = highs[0] - lows[0]
    for i in range(1, len(closes)):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    atr_values = np.zeros(len(closes))
    atr_values[period - 1] = np.mean(tr[:period])

    for i in range(period, len(closes)):
        atr_values[i] = (atr_values[i - 1] * (period - 1) + tr[i]) / period

    return atr_values


def obv(prices: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    """On-Balance Volume.

    OBV = sum of volume * sign(price_change)

    Args:
        prices: Price series
        volumes: Volume series

    Returns:
        OBV values
    """
    if len(prices) != len(volumes):
        raise ValueError("Price and volume series must be same length")

    obv_values = np.zeros(len(prices))
    obv_values[0] = volumes[0]

    for i in range(1, len(prices)):
        if prices[i] > prices[i - 1]:
            obv_values[i] = obv_values[i - 1] + volumes[i]
        elif prices[i] < prices[i - 1]:
            obv_values[i] = obv_values[i - 1] - volumes[i]
        else:
            obv_values[i] = obv_values[i - 1]

    return obv_values


def vwap(prices: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    """Volume Weighted Average Price.

    Args:
        prices: Price series
        volumes: Volume series

    Returns:
        VWAP values
    """
    if len(prices) != len(volumes):
        raise ValueError("Price and volume series must be same length")

    cumsum_pv = np.cumsum(prices * volumes)
    cumsum_v = np.cumsum(volumes)

    return cumsum_pv / cumsum_v


def adx(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Average Directional Index.

    Args:
        highs: High prices
        lows: Low prices
        closes: Close prices
        period: Period

    Returns:
        ADX values
    """
    if len(closes) < period:
        raise ValueError("Series too short for period")

    # True Range
    tr = np.zeros(len(closes))
    tr[0] = highs[0] - lows[0]
    for i in range(1, len(closes)):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    # Directional movements
    up_move = np.zeros(len(highs))
    down_move = np.zeros(len(highs))

    for i in range(1, len(highs)):
        if highs[i] - highs[i - 1] > lows[i - 1] - lows[i]:
            up_move[i] = max(highs[i] - highs[i - 1], 0)
        if lows[i - 1] - lows[i] > highs[i] - highs[i - 1]:
            down_move[i] = max(lows[i - 1] - lows[i], 0)

    # Positive and negative DI
    pos_di = 100 * np.cumsum(up_move) / np.cumsum(tr)
    neg_di = 100 * np.cumsum(down_move) / np.cumsum(tr)

    # ADX
    di_sum = np.abs(pos_di - neg_di) / (pos_di + neg_di + 1e-8)
    adx_values = sma(100 * di_sum, period)

    return adx_values


def fibonacci_levels(high: float, low: float) -> dict:
    """Calculate Fibonacci retracement levels.

    Args:
        high: High price
        low: Low price

    Returns:
        Dictionary with Fibonacci levels (0.236, 0.382, 0.5, 0.618, 0.786)
    """
    diff = high - low

    return {
        "0.0%": high,
        "23.6%": high - 0.236 * diff,
        "38.2%": high - 0.382 * diff,
        "50.0%": high - 0.5 * diff,
        "61.8%": high - 0.618 * diff,
        "78.6%": high - 0.786 * diff,
        "100.0%": low,
    }


def pivot_points(high: float, low: float, close: float) -> dict:
    """Calculate pivot point levels.

    Args:
        high: Period high
        low: Period low
        close: Period close

    Returns:
        Dictionary with pivot levels (P, S1, S2, R1, R2)
    """
    pivot = (high + low + close) / 3.0

    return {
        "R2": pivot + (high - low),
        "R1": 2 * pivot - low,
        "P": pivot,
        "S1": 2 * pivot - high,
        "S2": pivot - (high - low),
    }
