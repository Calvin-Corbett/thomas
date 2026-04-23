"""
Tests for backpressure mechanisms.

Tests rate limiting, buffer overflow, producer throttling,
and consumer lag monitoring.
"""

import asyncio

import pytest

from thomas.marketplace.message_queue.backpressure import (
    BackpressureConfig,
    BackpressureManager,
    SlidingWindow,
    TokenBucket,
)


@pytest.mark.asyncio
async def test_token_bucket_basic():
    """Test basic token bucket operation."""
    bucket = TokenBucket(capacity=10, refill_rate=10.0)

    # Should have tokens
    assert await bucket.acquire(5, timeout_ms=100)

    # Acquire more
    assert await bucket.acquire(5, timeout_ms=100)

    # Should be empty
    assert not await bucket.acquire(1, timeout_ms=100)


@pytest.mark.asyncio
async def test_token_bucket_refill():
    """Test token bucket refill."""
    bucket = TokenBucket(capacity=5, refill_rate=10.0)

    # Drain bucket
    await bucket.acquire(5, timeout_ms=100)

    # Wait for refill
    await asyncio.sleep(0.6)

    # Should have tokens again
    assert await bucket.acquire(1, timeout_ms=100)


@pytest.mark.asyncio
async def test_token_bucket_timeout():
    """Test token bucket timeout."""
    bucket = TokenBucket(capacity=1, refill_rate=1.0)

    # Acquire single token
    await bucket.acquire(1, timeout_ms=100)

    # Try to acquire more with short timeout
    result = await bucket.acquire(1, timeout_ms=10)

    assert result is False


@pytest.mark.asyncio
async def test_token_bucket_reset():
    """Test token bucket reset."""
    bucket = TokenBucket(capacity=10, refill_rate=1.0)

    # Drain bucket
    await bucket.acquire(10, timeout_ms=100)

    # Reset
    await bucket.reset()

    # Should have tokens again
    assert await bucket.acquire(5, timeout_ms=100)


@pytest.mark.asyncio
async def test_sliding_window_basic():
    """Test basic sliding window operation."""
    window = SlidingWindow(window_size_ms=1000)

    # Record events
    for _ in range(5):
        await window.record()

    count = await window.get_count()
    assert count == 5


@pytest.mark.asyncio
async def test_sliding_window_expiry():
    """Test sliding window expiry."""
    window = SlidingWindow(window_size_ms=100)

    # Record events
    for _ in range(5):
        await window.record()

    # Wait for window to expire
    await asyncio.sleep(0.15)

    # Should be expired
    count = await window.get_count()
    assert count == 0


@pytest.mark.asyncio
async def test_sliding_window_partial_expiry():
    """Test partial sliding window expiry."""
    window = SlidingWindow(window_size_ms=200)

    # Record initial events
    for _ in range(5):
        await window.record()

    # Wait for partial expiry
    await asyncio.sleep(0.15)

    # Record more events
    for _ in range(3):
        await window.record()

    count = await window.get_count()
    assert count == 8


@pytest.mark.asyncio
async def test_backpressure_manager_init():
    """Test backpressure manager initialization."""
    config = BackpressureConfig(enable_rate_limiting=True)
    manager = BackpressureManager(config)

    assert manager.config.enable_rate_limiting


@pytest.mark.asyncio
async def test_backpressure_rate_limiting():
    """Test rate limiting."""
    config = BackpressureConfig(
        enable_rate_limiting=True,
        rate_limit_msgs_per_sec=100,
    )
    manager = BackpressureManager(config)

    # Should allow publish
    can_publish = await manager.check_can_publish(timeout_ms=100)
    assert can_publish is True


@pytest.mark.asyncio
async def test_backpressure_buffer_tracking():
    """Test buffer usage tracking."""
    config = BackpressureConfig(enable_buffer_limits=True)
    manager = BackpressureManager(config)

    # Update buffer usage
    await manager.update_buffer_usage("producer-1", 5000)

    # Check if full
    is_full = await manager.is_buffer_full("producer-1")
    assert is_full is False


@pytest.mark.asyncio
async def test_backpressure_buffer_overflow():
    """Test buffer overflow detection."""
    config = BackpressureConfig(
        enable_buffer_limits=True,
        max_buffer_size=1000,
    )
    manager = BackpressureManager(config)

    # Update with overflow
    await manager.update_buffer_usage("producer-1", 1500)

    # Should detect overflow
    is_full = await manager.is_buffer_full("producer-1")
    assert is_full is True


@pytest.mark.asyncio
async def test_backpressure_consumer_lag():
    """Test consumer lag tracking."""
    config = BackpressureConfig(enable_lag_monitoring=True)
    manager = BackpressureManager(config)

    # Update lag
    await manager.update_consumer_lag("consumer-1", 5000)

    # Get lag
    lag = await manager.get_consumer_lag("consumer-1")
    assert lag == 5000


@pytest.mark.asyncio
async def test_backpressure_throttle_decision():
    """Test producer throttle decision based on lag."""
    config = BackpressureConfig(
        enable_lag_monitoring=True,
        max_consumer_lag=1000,
    )
    manager = BackpressureManager(config)

    # Low lag
    await manager.update_consumer_lag("consumer-1", 500)
    should_throttle = await manager.should_throttle_producer()
    assert should_throttle is False

    # High lag
    await manager.update_consumer_lag("consumer-1", 5000)
    should_throttle = await manager.should_throttle_producer()
    assert should_throttle is True


@pytest.mark.asyncio
async def test_backpressure_throughput_tracking():
    """Test throughput metrics."""
    manager = BackpressureManager()

    # Record publishes
    for _ in range(10):
        await manager.record_publish()

    # Get throughput
    throughput = await manager.get_throughput_msgs_per_sec()
    assert throughput > 0


@pytest.mark.asyncio
async def test_backpressure_stats():
    """Test getting backpressure stats."""
    config = BackpressureConfig(enable_buffer_limits=True)
    manager = BackpressureManager(config)

    # Setup some metrics
    await manager.update_buffer_usage("producer-1", 5000)
    await manager.update_consumer_lag("consumer-1", 3000)

    stats = await manager.get_stats()

    assert stats["total_buffer_usage"] == 5000
    assert stats["producers_tracked"] == 1
    assert stats["consumers_tracked"] == 1


@pytest.mark.asyncio
async def test_backpressure_reset():
    """Test resetting backpressure state."""
    manager = BackpressureManager()

    # Add some metrics
    await manager.update_buffer_usage("producer-1", 5000)
    await manager.update_consumer_lag("consumer-1", 3000)
    await manager.record_publish()

    # Reset
    await manager.reset()

    # Metrics should be cleared
    stats = await manager.get_stats()
    assert stats["total_buffer_usage"] == 0
    assert stats["producers_tracked"] == 0
    assert stats["consumers_tracked"] == 0


@pytest.mark.asyncio
async def test_backpressure_disabled():
    """Test that disabled backpressure allows all operations."""
    config = BackpressureConfig(
        enable_rate_limiting=False,
        enable_buffer_limits=False,
        enable_lag_monitoring=False,
    )
    manager = BackpressureManager(config)

    # All checks should pass
    assert await manager.check_can_publish() is True

    await manager.update_buffer_usage("producer-1", 999999)
    assert await manager.is_buffer_full("producer-1") is False

    await manager.update_consumer_lag("consumer-1", 999999)
    assert await manager.should_throttle_producer() is False


@pytest.mark.asyncio
async def test_backpressure_multiple_producers():
    """Test backpressure with multiple producers."""
    config = BackpressureConfig(enable_buffer_limits=True)
    manager = BackpressureManager(config)

    # Multiple producers with different buffer sizes
    await manager.update_buffer_usage("producer-1", 5000)
    await manager.update_buffer_usage("producer-2", 3000)
    await manager.update_buffer_usage("producer-3", 2000)

    stats = await manager.get_stats()
    assert stats["total_buffer_usage"] == 10000
    assert stats["producers_tracked"] == 3
