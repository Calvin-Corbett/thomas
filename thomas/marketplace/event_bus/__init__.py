"""
Thomas Event Bus Module

A complete typed pub/sub event system with event sourcing support.

Features:
- Typed event definitions with metadata
- Publish/subscribe with handler priorities
- Event store for event sourcing
- Projections for read models
- Event-sourced aggregates
- Sagas for long-running workflows
- Event replay engine
- Comprehensive middleware support
- Dead letter queues and retry logic
- Metrics collection
- Graceful shutdown

Example:
    from event_bus import EventBus, Event, AggregateRoot

    # Define an event
    class UserCreated(Event):
        def __init__(self, user_id: str, email: str):
            super().__init__('UserCreated', f'user-{user_id}')
            self.user_id = user_id
            self.email = email

    # Subscribe to events
    async def on_user_created(event: UserCreated):
        print(f"User created: {event.email}")

    # Use the bus
    async with EventBusContext() as bus:
        await bus.start()

        handler_id = bus.subscribe(
            on_user_created,
            event_types={'UserCreated'}
        )

        event = UserCreated('123', 'user@example.com')
        await bus.publish(event)

        await bus.shutdown()
"""

from ._exceptions import (
    ConcurrencyError,
    EventBusError,
    EventStoreError,
    HandlerError,
    ReplayError,
    SubscriptionError,
)
from ._types import (
    DeliveryGuarantee,
    Event,
    EventEnvelope,
    EventFilter,
    EventHandler,
    HandlerPriority,
    Subscription,
)
from .aggregate import AggregateCommand, AggregateRepository, AggregateRoot, CommandHandler
from .bus import EventBus, EventBusContext
from .dispatcher import (
    AsynchronousDispatcher,
    CircuitBreaker,
    CircuitBreakerState,
    DispatchStrategy,
    EventDispatcher,
    SynchronousDispatcher,
)
from .middleware import (
    CausationTrackingMiddleware,
    CorrelationIdMiddleware,
    DeduplicationMiddleware,
    EventEnrichmentMiddleware,
    LoggingMiddleware,
    MetricsMiddleware,
    Middleware,
    MiddlewareChain,
)
from .projections import (
    AggregateProjection,
    CatchUpProjection,
    InMemoryProjection,
    LiveProjection,
    Projection,
    ProjectionManager,
    ProjectionStatus,
)
from .replay import (
    EventReplayer,
    ReplayFilter,
    ReplayMode,
    ReplayProgress,
    ReplayStatus,
)
from .sagas import (
    EventTriggeredSaga,
    Saga,
    SagaBuilder,
    SagaExecutor,
    SagaState,
    SagaStatus,
    SagaStep,
)
from .serialization import (
    EventSerializer,
    TypeRegistry,
    get_registry,
    get_serializer,
    register_event_type,
)
from .store import EventStore, StreamMetadata, StreamSnapshot

__all__ = [
    # Core types
    "Event",
    "EventHandler",
    "EventEnvelope",
    "EventFilter",
    "Subscription",
    "DeliveryGuarantee",
    "HandlerPriority",
    # Exceptions
    "EventBusError",
    "HandlerError",
    "EventStoreError",
    "ConcurrencyError",
    "ReplayError",
    "SubscriptionError",
    # Bus
    "EventBus",
    "EventBusContext",
    # Dispatcher
    "DispatchStrategy",
    "EventDispatcher",
    "SynchronousDispatcher",
    "AsynchronousDispatcher",
    "CircuitBreaker",
    "CircuitBreakerState",
    # Middleware
    "Middleware",
    "MiddlewareChain",
    "LoggingMiddleware",
    "MetricsMiddleware",
    "CorrelationIdMiddleware",
    "CausationTrackingMiddleware",
    "EventEnrichmentMiddleware",
    "DeduplicationMiddleware",
    # Store
    "EventStore",
    "StreamSnapshot",
    "StreamMetadata",
    # Aggregates
    "AggregateRoot",
    "AggregateRepository",
    "AggregateCommand",
    "CommandHandler",
    # Projections
    "Projection",
    "InMemoryProjection",
    "AggregateProjection",
    "CatchUpProjection",
    "LiveProjection",
    "ProjectionManager",
    "ProjectionStatus",
    # Replay
    "EventReplayer",
    "ReplayFilter",
    "ReplayMode",
    "ReplayStatus",
    "ReplayProgress",
    # Sagas
    "Saga",
    "SagaStep",
    "SagaState",
    "SagaStatus",
    "SagaExecutor",
    "EventTriggeredSaga",
    "SagaBuilder",
    # Serialization
    "EventSerializer",
    "TypeRegistry",
    "register_event_type",
    "get_serializer",
    "get_registry",
]

__version__ = "1.0.0"
