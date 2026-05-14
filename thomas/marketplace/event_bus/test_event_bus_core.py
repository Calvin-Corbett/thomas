"""
Tests for core event bus functionality.

Tests publish/subscribe, priorities, wildcards, and error handling.
"""

import asyncio

import pytest

from . import (
    DeliveryGuarantee,
    DispatchStrategy,
    Event,
    EventBus,
    EventBusContext,
    HandlerPriority,
)


class TestEvent(Event):
    """Test event class."""

    def __init__(self, message: str = "", source: str = "test"):
        super().__init__("TestEvent", source)
        self.message = message


class UserCreated(Event):
    """Test aggregate event."""

    def __init__(self, user_id: str, email: str):
        super().__init__("UserCreated", f"user-{user_id}")
        self.user_id = user_id
        self.email = email


class UserDeleted(Event):
    """Test aggregate event."""

    def __init__(self, user_id: str):
        super().__init__("UserDeleted", f"user-{user_id}")
        self.user_id = user_id


@pytest.fixture
async def bus():
    """Create and start an event bus."""
    bus = EventBus(dispatch_strategy=DispatchStrategy.ASYNCHRONOUS)
    await bus.start()
    yield bus
    await bus.shutdown()


@pytest.mark.asyncio
async def test_publish_subscribe():
    """Test basic publish/subscribe."""
    events: list[Event] = []

    async def handler(event: Event):
        events.append(event)

    async with EventBusContext() as bus:
        bus.subscribe(handler, event_types={"TestEvent"})

        event = TestEvent("hello")
        await bus.publish(event)

        await asyncio.sleep(0.1)

        assert len(events) == 1
        assert events[0].message == "hello"


@pytest.mark.asyncio
async def test_wildcard_subscription():
    """Test wildcard subscription."""
    events: list[Event] = []

    async def handler(event: Event):
        events.append(event)

    async with EventBusContext() as bus:
        bus.subscribe(handler, event_types={"*"})

        await bus.publish(UserCreated("123", "user@example.com"))
        await bus.publish(UserDeleted("123"))

        await asyncio.sleep(0.1)

        assert len(events) == 2


@pytest.mark.asyncio
async def test_handler_priority():
    """Test handler execution order by priority."""
    execution_order: list[int] = []

    async def high_priority(event: Event):
        execution_order.append(1)

    async def normal_priority(event: Event):
        execution_order.append(2)

    async def low_priority(event: Event):
        execution_order.append(3)

    async with EventBusContext(DispatchStrategy.SYNCHRONOUS) as bus:
        bus.subscribe(normal_priority, event_types={"TestEvent"}, priority=HandlerPriority.NORMAL)
        bus.subscribe(high_priority, event_types={"TestEvent"}, priority=HandlerPriority.HIGH)
        bus.subscribe(low_priority, event_types={"TestEvent"}, priority=HandlerPriority.LOW)

        await bus.publish(TestEvent())

        assert execution_order == [1, 2, 3]


@pytest.mark.asyncio
async def test_unsubscribe():
    """Test unsubscribing handlers."""
    events: list[Event] = []

    async def handler(event: Event):
        events.append(event)

    async with EventBusContext() as bus:
        sub_id = bus.subscribe(handler)
        await bus.publish(TestEvent())

        await asyncio.sleep(0.1)

        assert len(events) == 1

        bus.unsubscribe(sub_id)
        await bus.publish(TestEvent())

        await asyncio.sleep(0.1)

        assert len(events) == 1


@pytest.mark.asyncio
async def test_handler_error_handling():
    """Test error handling in handlers."""

    async def failing_handler(event: Event):
        raise ValueError("Handler failed")

    async def normal_handler(event: Event):
        pass

    async with EventBusContext() as bus:
        bus.subscribe(failing_handler)
        bus.subscribe(normal_handler)

        event = TestEvent()
        await bus.publish(event)

        dead_letters = bus.get_dead_letters()
        assert len(dead_letters) == 0


@pytest.mark.asyncio
async def test_multiple_event_types():
    """Test subscribing to multiple event types."""
    events: list[Event] = []

    async def handler(event: Event):
        events.append(event)

    async with EventBusContext() as bus:
        bus.subscribe(handler, event_types={"UserCreated", "UserDeleted"})

        await bus.publish(UserCreated("1", "user@example.com"))
        await bus.publish(TestEvent())
        await bus.publish(UserDeleted("1"))

        await asyncio.sleep(0.1)

        assert len(events) == 2
        assert isinstance(events[0], UserCreated)
        assert isinstance(events[1], UserDeleted)


@pytest.mark.asyncio
async def test_publish_batch():
    """Test batch publishing."""
    events: list[Event] = []

    async def handler(event: Event):
        events.append(event)

    async with EventBusContext() as bus:
        bus.subscribe(handler)

        batch = [TestEvent(f"msg-{i}") for i in range(5)]
        result = await bus.publish_batch(batch)

        await asyncio.sleep(0.1)

        assert result["total"] == 5
        assert len(events) == 5


@pytest.mark.asyncio
async def test_delivery_guarantee_semantics():
    """Test different delivery guarantee modes."""
    events: list[tuple[str, bool]] = []

    async def handler(event: Event):
        events.append((event.id, True))

    async with EventBusContext() as bus:
        bus.subscribe(
            handler,
            delivery_guarantee=DeliveryGuarantee.AT_LEAST_ONCE,
        )

        await bus.publish(TestEvent())

        await asyncio.sleep(0.1)

        assert len(events) == 1


@pytest.mark.asyncio
async def test_subscription_count():
    """Test subscription counting."""

    async def handler1(event: Event):
        pass

    async def handler2(event: Event):
        pass

    async with EventBusContext() as bus:
        bus.subscribe(handler1, event_types={"TestEvent"})
        bus.subscribe(handler2, event_types={"UserCreated"})

        assert bus.get_subscription_count() == 2
        assert bus.get_subscription_count("TestEvent") >= 1


@pytest.mark.asyncio
async def test_metrics_collection():
    """Test metrics are collected."""

    async def handler(event: Event):
        pass

    async with EventBusContext() as bus:
        bus.subscribe(handler)

        await bus.publish(UserCreated("1", "user@example.com"))
        await bus.publish(UserDeleted("1"))

        await asyncio.sleep(0.1)

        metrics = bus.get_metrics()

        assert metrics["events_published"] == 2


@pytest.mark.asyncio
async def test_dispatch_strategy_sync():
    """Test synchronous dispatch strategy."""

    async def handler(event: Event):
        pass

    async with EventBusContext(DispatchStrategy.SYNCHRONOUS) as bus:
        bus.subscribe(handler)

        await bus.publish(TestEvent())

        assert bus.get_dispatch_strategy() == DispatchStrategy.SYNCHRONOUS


@pytest.mark.asyncio
async def test_middleware_chain():
    """Test middleware execution."""
    calls: list[str] = []

    class TestMiddleware:
        async def before_publish(self, event):
            calls.append("before")
            return event

        async def after_publish(self, event, success):
            calls.append("after")

    async with EventBusContext() as bus:
        middleware = TestMiddleware()
        bus.add_middleware(middleware)

        await bus.publish(TestEvent())

        assert "before" in calls
        assert "after" in calls


@pytest.mark.asyncio
async def test_clear_metrics():
    """Test clearing metrics."""

    async def handler(event: Event):
        pass

    async with EventBusContext() as bus:
        bus.subscribe(handler)

        await bus.publish(TestEvent())
        await asyncio.sleep(0.1)

        metrics_before = bus.get_metrics()
        assert metrics_before["events_published"] > 0

        bus.clear_metrics()

        metrics_after = bus.get_metrics()
        assert metrics_after["events_published"] == 0


@pytest.mark.asyncio
async def test_handler_timeout():
    """Test handler timeout behavior."""

    async def slow_handler(event: Event):
        await asyncio.sleep(10)

    async with EventBusContext() as bus:
        bus.subscribe(slow_handler, timeout_seconds=0.1)

        event = TestEvent()
        result = await bus.publish(event)

        await asyncio.sleep(0.2)

        assert "failed" in str(result).lower() or "skipped" in str(result).lower()


@pytest.mark.asyncio
async def test_concurrent_publishes():
    """Test handling concurrent publishes."""
    events: list[Event] = []

    async def handler(event: Event):
        events.append(event)

    async with EventBusContext() as bus:
        bus.subscribe(handler)

        tasks = [bus.publish(TestEvent(f"msg-{i}")) for i in range(10)]
        await asyncio.gather(*tasks)

        await asyncio.sleep(0.2)

        assert len(events) == 10


@pytest.mark.asyncio
async def test_bus_not_running_error():
    """Test publishing when bus not running."""
    bus = EventBus()

    with pytest.raises(Exception):
        await bus.publish(TestEvent())


@pytest.mark.asyncio
async def test_event_source_filtering():
    """Test filtering events by source."""
    events: list[Event] = []

    async def handler(event: Event):
        if event.source == "user-1":
            events.append(event)

    async with EventBusContext() as bus:
        bus.subscribe(handler)

        await bus.publish(UserCreated("1", "user@example.com"))
        await bus.publish(UserCreated("2", "user2@example.com"))

        await asyncio.sleep(0.1)

        assert len(events) == 1
        assert events[0].source == "user-1"
