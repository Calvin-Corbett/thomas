"""
Command bus and command handling infrastructure.

Implements CommandBus for dispatching commands to handlers, support for
validation, middleware, retry logic, timeouts, and deduplication.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol, TypeVar

from ._exceptions import (
    CommandExecutionException,
    CommandTimeoutException,
    DuplicateCommandException,
)
from ._types import Command, CommandResult, Metadata

TCommand = TypeVar("TCommand", bound=Command)
TResult = TypeVar("TResult")


class CommandHandler(Protocol[TCommand, TResult]):
    """
    Protocol for command handlers.

    Handlers receive a command and produce a result.
    """

    async def handle(self, command: TCommand) -> CommandResult[TResult]:
        """
        Handle a command.

        Args:
            command: Command to handle

        Returns:
            CommandResult with outcome
        """
        ...


class CommandValidator(ABC):
    """
    Base class for command validators.

    Validators check command invariants before execution.
    """

    @abstractmethod
    async def validate(self, command: Command) -> None:
        """
        Validate a command.

        Args:
            command: Command to validate

        Raises:
            CommandValidationException: If validation fails
        """
        pass


class CommandMiddleware(ABC):
    """
    Base class for command middleware.

    Middleware can intercept commands for logging, security,
    modification, or other cross-cutting concerns.
    """

    @abstractmethod
    async def handle(
        self,
        command: Command,
        next_handler: Callable[[Command], Awaitable[CommandResult[Any]]],
    ) -> CommandResult[Any]:
        """
        Process a command through middleware.

        Args:
            command: The command to process
            next_handler: Next middleware in chain

        Returns:
            CommandResult from handler
        """
        pass


@dataclass
class RetryPolicy:
    """Configuration for command retry behavior."""

    max_retries: int = 3
    initial_delay_ms: int = 100
    max_delay_ms: int = 5000
    backoff_multiplier: float = 2.0


@dataclass
class CommandDeduplicationKey:
    """Key for detecting duplicate commands."""

    command_type: str
    aggregate_id: str | None
    user_id: str | None
    command_hash: str


class CommandDeduplicator:
    """
    Detects and prevents duplicate command execution.

    Tracks recently processed commands to prevent re-execution.
    """

    def __init__(self, window_seconds: int = 300) -> None:
        """
        Initialize deduplicator.

        Args:
            window_seconds: How long to track command IDs
        """
        self.window_seconds = window_seconds
        self._processed: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    async def is_duplicate(self, command: Command, metadata: Metadata) -> bool:
        """
        Check if command is a duplicate.

        Args:
            command: Command to check
            metadata: Command metadata

        Returns:
            True if command appears to be duplicate
        """
        async with self._lock:
            key = command.command_id
            now = datetime.utcnow()

            # Clean old entries
            cutoff = now - timedelta(seconds=self.window_seconds)
            self._processed = {k: v for k, v in self._processed.items() if v > cutoff}

            if key in self._processed:
                return True

            self._processed[key] = now
            return False


class LoggingMiddleware(CommandMiddleware):
    """Middleware that logs command execution."""

    async def handle(
        self,
        command: Command,
        next_handler: Callable[[Command], Awaitable[CommandResult[Any]]],
    ) -> CommandResult[Any]:
        """Log command and pass to next handler."""
        start_time = time.time()
        result = await next_handler(command)
        duration = time.time() - start_time
        return result


class ValidatingMiddleware(CommandMiddleware):
    """
    Middleware that validates commands.

    Runs registered validators before command execution.
    """

    def __init__(self, validators: list[CommandValidator] | None = None) -> None:
        """
        Initialize validating middleware.

        Args:
            validators: Validators to apply
        """
        self.validators = validators or []

    async def handle(
        self,
        command: Command,
        next_handler: Callable[[Command], Awaitable[CommandResult[Any]]],
    ) -> CommandResult[Any]:
        """Validate and pass to next handler."""
        for validator in self.validators:
            await validator.validate(command)
        return await next_handler(command)


class IdempotencyMiddleware(CommandMiddleware):
    """
    Middleware that prevents duplicate command execution.

    Uses deduplication to ensure commands only execute once.
    """

    def __init__(self, deduplicator: CommandDeduplicator | None = None) -> None:
        """
        Initialize idempotency middleware.

        Args:
            deduplicator: Deduplicator instance
        """
        self.deduplicator = deduplicator or CommandDeduplicator()

    async def handle(
        self,
        command: Command,
        next_handler: Callable[[Command], Awaitable[CommandResult[Any]]],
    ) -> CommandResult[Any]:
        """Check for duplicates and pass to handler."""
        metadata = getattr(command, "metadata", Metadata())
        if await self.deduplicator.is_duplicate(command, metadata):
            raise DuplicateCommandException(command.command_id)
        return await next_handler(command)


class RetryMiddleware(CommandMiddleware):
    """
    Middleware that retries failed commands.

    Implements exponential backoff retry logic.
    """

    def __init__(self, policy: RetryPolicy | None = None) -> None:
        """
        Initialize retry middleware.

        Args:
            policy: Retry policy configuration
        """
        self.policy = policy or RetryPolicy()

    async def handle(
        self,
        command: Command,
        next_handler: Callable[[Command], Awaitable[CommandResult[Any]]],
    ) -> CommandResult[Any]:
        """Execute with retry logic."""
        last_exception: Exception | None = None
        delay = self.policy.initial_delay_ms

        for attempt in range(self.policy.max_retries + 1):
            try:
                return await next_handler(command)
            except Exception as e:
                last_exception = e
                if attempt < self.policy.max_retries:
                    await asyncio.sleep(delay / 1000.0)
                    delay = min(
                        int(delay * self.policy.backoff_multiplier),
                        self.policy.max_delay_ms,
                    )
                continue

        if last_exception:
            raise last_exception
        raise CommandExecutionException("Unknown error during retry")


class TimeoutMiddleware(CommandMiddleware):
    """
    Middleware that enforces execution timeouts.

    Cancels command execution if it exceeds timeout.
    """

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        """
        Initialize timeout middleware.

        Args:
            timeout_seconds: Timeout limit
        """
        self.timeout_seconds = timeout_seconds

    async def handle(
        self,
        command: Command,
        next_handler: Callable[[Command], Awaitable[CommandResult[Any]]],
    ) -> CommandResult[Any]:
        """Execute with timeout."""
        try:
            return await asyncio.wait_for(
                next_handler(command),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise CommandTimeoutException(f"Command execution exceeded {self.timeout_seconds}s timeout")


class CommandBus:
    """
    Central dispatcher for command handling.

    Routes commands to registered handlers, applies middleware,
    and manages command execution lifecycle.
    """

    def __init__(self) -> None:
        """Initialize command bus."""
        self._handlers: dict[type, Callable[[Any], Awaitable[CommandResult[Any]]]] = {}
        self._middleware: list[CommandMiddleware] = []

    def register_handler(
        self,
        command_type: type[TCommand],
        handler: Callable[[TCommand], Awaitable[CommandResult[TResult]]],
    ) -> None:
        """
        Register command handler.

        Args:
            command_type: Type of command to handle
            handler: Handler function
        """
        self._handlers[command_type] = handler

    def add_middleware(self, middleware: CommandMiddleware) -> None:
        """
        Add middleware to command pipeline.

        Middleware is applied in registration order.

        Args:
            middleware: Middleware to add
        """
        self._middleware.append(middleware)

    async def execute(self, command: Command) -> CommandResult[Any]:
        """
        Execute a command.

        Routes to registered handler and applies middleware chain.

        Args:
            command: Command to execute

        Returns:
            CommandResult with outcome

        Raises:
            CommandExecutionException: If no handler registered
        """
        handler = self._handlers.get(type(command))
        if not handler:
            raise CommandExecutionException(f"No handler registered for {type(command).__name__}")

        # Build middleware chain
        async def final_handler(cmd: Command) -> CommandResult[Any]:
            return await handler(cmd)

        async def apply_middleware(
            cmd: Command,
            middleware_list: list[CommandMiddleware],
        ) -> CommandResult[Any]:
            if not middleware_list:
                return await final_handler(cmd)

            current_middleware = middleware_list[0]
            remaining = middleware_list[1:]

            async def next_handler(c: Command) -> CommandResult[Any]:
                return await apply_middleware(c, remaining)

            return await current_middleware.handle(cmd, next_handler)

        return await apply_middleware(command, self._middleware)

    def get_handler(self, command_type: type) -> Callable | None:
        """
        Get handler for command type.

        Args:
            command_type: Type to look up

        Returns:
            Handler or None
        """
        return self._handlers.get(command_type)

    def handlers(self) -> dict[type, Callable]:
        """
        Get all registered handlers.

        Returns:
            Dictionary of command type to handler
        """
        return self._handlers.copy()

    def middleware(self) -> list[CommandMiddleware]:
        """
        Get all registered middleware.

        Returns:
            List of middleware in order
        """
        return self._middleware.copy()
