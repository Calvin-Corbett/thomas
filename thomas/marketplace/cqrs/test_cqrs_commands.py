"""
Tests for command bus and command handling.

Tests command execution, validation, middleware, retry logic,
timeouts, and deduplication.
"""

import asyncio

import pytest

from . import (
    Command,
    CommandBus,
    CommandDeduplicator,
    CommandExecutionException,
    CommandResult,
    CommandTimeoutException,
    CommandTimeoutMiddleware,
    CommandValidationException,
    CommandValidator,
    Metadata,
    RetryMiddleware,
    RetryPolicy,
    ValidatingMiddleware,
)


class TestCommand(Command):
    """Test command."""

    def __init__(self, value: str = "test"):
        super().__init__()
        self.value = value


class FailingCommand(Command):
    """Command that fails."""

    def __init__(self):
        super().__init__()


class SlowCommand(Command):
    """Command that takes time."""

    def __init__(self, delay: float = 1.0):
        super().__init__()
        self.delay = delay


class TestCommandBus:
    """Tests for CommandBus."""

    @pytest.mark.asyncio
    async def test_register_and_execute_handler(self):
        """Test basic command registration and execution."""
        bus = CommandBus()
        executed = False

        async def handle_test(cmd: TestCommand) -> CommandResult:
            nonlocal executed
            executed = True
            return CommandResult.ok()

        bus.register_handler(TestCommand, handle_test)
        result = await bus.execute(TestCommand())

        assert executed
        assert result.success

    @pytest.mark.asyncio
    async def test_handler_not_registered(self):
        """Test error when handler not registered."""
        bus = CommandBus()

        with pytest.raises(CommandExecutionException):
            await bus.execute(TestCommand())

    @pytest.mark.asyncio
    async def test_handler_with_events(self):
        """Test handler that produces events."""
        bus = CommandBus()

        async def handle_test(cmd: TestCommand) -> CommandResult:
            from . import Event

            class TestEvent(Event):
                pass

            return CommandResult.ok([TestEvent()])

        bus.register_handler(TestCommand, handle_test)
        result = await bus.execute(TestCommand())

        assert result.success
        assert len(result.events) == 1

    @pytest.mark.asyncio
    async def test_get_handler(self):
        """Test retrieving registered handler."""
        bus = CommandBus()

        async def handler(cmd: TestCommand) -> CommandResult:
            return CommandResult.ok()

        bus.register_handler(TestCommand, handler)
        retrieved = bus.get_handler(TestCommand)

        assert retrieved is handler

    @pytest.mark.asyncio
    async def test_handlers_dict(self):
        """Test getting all handlers."""
        bus = CommandBus()

        async def handler1(cmd: TestCommand) -> CommandResult:
            return CommandResult.ok()

        async def handler2(cmd: FailingCommand) -> CommandResult:
            return CommandResult.ok()

        bus.register_handler(TestCommand, handler1)
        bus.register_handler(FailingCommand, handler2)

        handlers = bus.handlers()
        assert len(handlers) == 2


class TestMiddleware:
    """Tests for command middleware."""

    @pytest.mark.asyncio
    async def test_timeout_middleware_success(self):
        """Test timeout middleware with successful execution."""
        bus = CommandBus()
        bus.add_middleware(CommandTimeoutMiddleware(timeout_seconds=2.0))

        async def handler(cmd: TestCommand) -> CommandResult:
            await asyncio.sleep(0.1)
            return CommandResult.ok()

        bus.register_handler(TestCommand, handler)
        result = await bus.execute(TestCommand())

        assert result.success

    @pytest.mark.asyncio
    async def test_timeout_middleware_exceeds_timeout(self):
        """Test timeout middleware when timeout is exceeded."""
        bus = CommandBus()
        bus.add_middleware(CommandTimeoutMiddleware(timeout_seconds=0.1))

        async def handler(cmd: SlowCommand) -> CommandResult:
            await asyncio.sleep(1.0)
            return CommandResult.ok()

        bus.register_handler(SlowCommand, handler)

        with pytest.raises(CommandTimeoutException):
            await bus.execute(SlowCommand(delay=1.0))

    @pytest.mark.asyncio
    async def test_retry_middleware_success_on_retry(self):
        """Test retry middleware succeeds after failures."""
        bus = CommandBus()
        policy = RetryPolicy(max_retries=2, initial_delay_ms=10)
        bus.add_middleware(RetryMiddleware(policy=policy))

        attempt_count = 0

        async def handler(cmd: TestCommand) -> CommandResult:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise ValueError("Temporary failure")
            return CommandResult.ok()

        bus.register_handler(TestCommand, handler)
        result = await bus.execute(TestCommand())

        assert result.success
        assert attempt_count == 2

    @pytest.mark.asyncio
    async def test_retry_middleware_exhausts_retries(self):
        """Test retry middleware gives up after max retries."""
        bus = CommandBus()
        policy = RetryPolicy(max_retries=2, initial_delay_ms=10)
        bus.add_middleware(RetryMiddleware(policy=policy))

        async def handler(cmd: FailingCommand) -> CommandResult:
            raise ValueError("Always fails")

        bus.register_handler(FailingCommand, handler)

        with pytest.raises(ValueError):
            await bus.execute(FailingCommand())

    @pytest.mark.asyncio
    async def test_idempotency_middleware_detects_duplicate(self):
        """Test idempotency middleware detects duplicates."""
        bus = CommandBus()
        CommandDeduplicator(window_seconds=60)
        bus.add_middleware(ValidatingMiddleware([]))

        async def handler(cmd: TestCommand) -> CommandResult:
            return CommandResult.ok()

        bus.register_handler(TestCommand, handler)

        cmd = TestCommand()
        # First execution should succeed
        result1 = await bus.execute(cmd)
        assert result1.success

        # Second execution of same command should fail
        with pytest.raises(CommandExecutionException):
            await bus.execute(cmd)

    @pytest.mark.asyncio
    async def test_middleware_chaining(self):
        """Test multiple middleware applied in order."""
        bus = CommandBus()
        bus.add_middleware(CommandTimeoutMiddleware(timeout_seconds=5.0))
        bus.add_middleware(RetryMiddleware(RetryPolicy(max_retries=1, initial_delay_ms=10)))

        async def handler(cmd: TestCommand) -> CommandResult:
            return CommandResult.ok()

        bus.register_handler(TestCommand, handler)
        result = await bus.execute(TestCommand())

        assert result.success

    @pytest.mark.asyncio
    async def test_get_middleware(self):
        """Test retrieving middleware."""
        bus = CommandBus()
        middleware1 = CommandTimeoutMiddleware()
        middleware2 = RetryMiddleware()

        bus.add_middleware(middleware1)
        bus.add_middleware(middleware2)

        middleware_list = bus.middleware()
        assert len(middleware_list) == 2
        assert middleware_list[0] is middleware1
        assert middleware_list[1] is middleware2


class TestCommandValidator:
    """Tests for command validation."""

    @pytest.mark.asyncio
    async def test_validation_middleware(self):
        """Test validation middleware."""
        bus = CommandBus()

        class TestValidator(CommandValidator):
            async def validate(self, command: Command) -> None:
                if isinstance(command, TestCommand):
                    if not command.value:
                        raise CommandValidationException("value required")

        bus.add_middleware(ValidatingMiddleware([TestValidator()]))

        async def handler(cmd: TestCommand) -> CommandResult:
            return CommandResult.ok()

        bus.register_handler(TestCommand, handler)

        # Valid command should succeed
        result = await bus.execute(TestCommand("valid"))
        assert result.success

        # Invalid command should fail
        with pytest.raises(CommandValidationException):
            await bus.execute(TestCommand(""))


class TestCommandResult:
    """Tests for CommandResult."""

    def test_ok_result(self):
        """Test creating successful result."""
        from . import Event

        class TestEvent(Event):
            pass

        from . import AggregateId

        agg_id = AggregateId("123", "TestAggregate")
        event = TestEvent()

        result = CommandResult.ok([event], agg_id, data={"key": "value"})

        assert result.success
        assert len(result.events) == 1
        assert result.aggregate_id == agg_id
        assert result.data == {"key": "value"}
        assert result.error is None

    def test_fail_result(self):
        """Test creating failed result."""
        result = CommandResult.fail("Error message", error_code="ERR_001")

        assert not result.success
        assert result.error == "Error message"
        assert result.error_code == "ERR_001"
        assert len(result.events) == 0


class TestCommandDeduplicator:
    """Tests for command deduplicator."""

    @pytest.mark.asyncio
    async def test_duplicate_detection(self):
        """Test duplicate detection."""
        dedup = CommandDeduplicator(window_seconds=60)
        cmd = TestCommand()
        metadata = Metadata()

        # First call should not be duplicate
        is_dup = await dedup.is_duplicate(cmd, metadata)
        assert not is_dup

        # Second call with same ID should be duplicate
        is_dup = await dedup.is_duplicate(cmd, metadata)
        assert is_dup

    @pytest.mark.asyncio
    async def test_duplicate_expiration(self):
        """Test duplicates expire."""
        dedup = CommandDeduplicator(window_seconds=0)
        cmd = TestCommand()
        metadata = Metadata()

        # Record first
        is_dup = await dedup.is_duplicate(cmd, metadata)
        assert not is_dup

        # Wait for window to pass
        await asyncio.sleep(0.1)

        # Should not be duplicate anymore
        is_dup = await dedup.is_duplicate(cmd, metadata)
        assert not is_dup
