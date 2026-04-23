"""
CQRS and Event Sourcing framework.

Complete implementation of Command Query Responsibility Segregation (CQRS)
and Event Sourcing patterns with distributed saga support, projections,
and process management.

Core Components:
- Command Bus: Routes commands to handlers with middleware support
- Query Bus: Routes queries to handlers with caching and middleware
- Event Store: Persistent event storage with optimistic concurrency control
- Aggregates: Domain object base class with event sourcing support
- Projections: Event-driven denormalized view building
- Sagas: Distributed transaction coordination with compensation
- Read Models: Denormalized data store with querying
- Process Manager: Long-running process orchestration

Example Usage:

    from thomas.marketplace.cqrs import (
        Command, Query, Event, CommandBus, QueryBus,
        EventStore, AggregateRepository, CommandResult, QueryResult
    )

    # Define domain objects
    class CreateAccount(Command):
        def __init__(self, account_id: str, name: str):
            super().__init__()
            self.account_id = account_id
            self.name = name

    class GetAccount(Query):
        def __init__(self, account_id: str):
            super().__init__()
            self.account_id = account_id

    class AccountCreated(Event):
        def __init__(self, account_id: str, name: str):
            super().__init__()
            self.account_id = account_id
            self.name = name

    # Set up infrastructure
    event_store = EventStore()
    command_bus = CommandBus()
    query_bus = QueryBus()

    # Register handlers
    async def handle_create_account(cmd: CreateAccount):
        # Business logic
        return CommandResult.ok([AccountCreated(cmd.account_id, cmd.name)])

    command_bus.register_handler(CreateAccount, handle_create_account)

    # Execute
    result = await command_bus.execute(CreateAccount("123", "Alice"))
    assert result.success

Features:

- **Type Safety**: Full type annotations for IDE support and static analysis
- **Async/Await**: Non-blocking async/await pattern throughout
- **Middleware**: Command and query middleware for cross-cutting concerns
- **Caching**: Query result caching with TTL
- **Snapshots**: Aggregate snapshots for performance optimization
- **Schema Evolution**: Event upcasting for schema version management
- **Idempotency**: Duplicate command detection
- **Retry Logic**: Automatic retry with exponential backoff
- **Authorization**: Policy-based authorization middleware
- **Metrics**: Built-in metrics collection
"""

# Core types
# Exceptions
from ._exceptions import (
    AggregateNotFoundException,
    CommandExecutionException,
    CommandTimeoutException,
    CommandValidationException,
    ConcurrencyException,
    CQRSException,
    DeserializationException,
    DuplicateCommandException,
    EventStoreException,
    InvalidEventTypeException,
    MiddlewareException,
    ProcessManagerException,
    ProjectionException,
    QueryExecutionException,
    QueryTimeoutException,
    ReadModelException,
    SagaCompensationException,
    SagaException,
    SagaTimeoutException,
    SerializationException,
    SnapshotException,
    UpcastingException,
)
from ._types import (
    AggregateId,
    Command,
    CommandResult,
    Event,
    EventEnvelope,
    EventPriority,
    Metadata,
    Query,
    QueryResult,
    SnapshotData,
)

# Aggregates
from .aggregates import (
    AggregateRepository,
    AggregateRoot,
)

# Commands
from .commands import (
    CommandBus,
    CommandDeduplicator,
    CommandHandler,
    CommandMiddleware,
    CommandValidator,
    RetryMiddleware,
    RetryPolicy,
    ValidatingMiddleware,
)
from .commands import (
    IdempotencyMiddleware as CommandIdempotencyMiddleware,
)
from .commands import (
    LoggingMiddleware as CommandLoggingMiddleware,
)
from .commands import (
    TimeoutMiddleware as CommandTimeoutMiddleware,
)

# Events
from .events import (
    EventStore,
    StoredEvent,
)

# Middleware
from .middleware import (
    AuthorizationPolicy,
    AuthorizingMiddleware,
    IdempotencyMiddleware,
    MetricsCollector,
    MetricsMiddleware,
    MetricsSnapshot,
    ValidationMiddleware,
)

# Process Manager
from .process_manager import (
    ProcessDefinition,
    ProcessInstance,
    ProcessManager,
    ProcessStep,
)

# Projections
from .projections import (
    InMemoryProjection,
    Projection,
    ProjectionCheckpoint,
    ProjectionManager,
)

# Queries
from .queries import (
    CachingMiddleware,
    PaginationParams,
    QueryBus,
    QueryCache,
    QueryHandler,
    QueryMiddleware,
)
from .queries import (
    LoggingMiddleware as QueryLoggingMiddleware,
)
from .queries import (
    TimeoutMiddleware as QueryTimeoutMiddleware,
)
from .read_models import (
    QueryBuilder as ReadModelQueryBuilder,
)

# Read Models
from .read_models import (
    QueryFilter,
    ReadModelDocument,
    ReadModelStore,
)

# Sagas
from .sagas import (
    SagaBase,
    SagaInstance,
    SagaManager,
    SagaStep,
    SagaStepResult,
)

# Serialization
from .serialization import (
    EventSerializer,
    EventTypeRegistry,
    EventUpCaster,
    SimpleEventUpCaster,
)

__version__ = "1.0.0"

__all__ = [
    # Core types
    "Command",
    "Query",
    "Event",
    "AggregateId",
    "Metadata",
    "EventEnvelope",
    "CommandResult",
    "QueryResult",
    "SnapshotData",
    "EventPriority",
    # Exceptions
    "CQRSException",
    "CommandExecutionException",
    "CommandValidationException",
    "CommandTimeoutException",
    "QueryExecutionException",
    "QueryTimeoutException",
    "AggregateNotFoundException",
    "ConcurrencyException",
    "EventStoreException",
    "SnapshotException",
    "ProjectionException",
    "SagaException",
    "SagaTimeoutException",
    "SagaCompensationException",
    "MiddlewareException",
    "SerializationException",
    "DeserializationException",
    "DuplicateCommandException",
    "ReadModelException",
    "ProcessManagerException",
    "InvalidEventTypeException",
    "UpcastingException",
    # Commands
    "CommandBus",
    "CommandHandler",
    "CommandValidator",
    "CommandMiddleware",
    "RetryPolicy",
    "CommandDeduplicator",
    "CommandLoggingMiddleware",
    "ValidatingMiddleware",
    "CommandIdempotencyMiddleware",
    "RetryMiddleware",
    "CommandTimeoutMiddleware",
    # Queries
    "QueryBus",
    "QueryHandler",
    "QueryMiddleware",
    "QueryCache",
    "PaginationParams",
    "CachingMiddleware",
    "QueryTimeoutMiddleware",
    "QueryLoggingMiddleware",
    # Events
    "EventStore",
    "StoredEvent",
    # Aggregates
    "AggregateRoot",
    "AggregateRepository",
    # Projections
    "Projection",
    "ProjectionManager",
    "ProjectionCheckpoint",
    "InMemoryProjection",
    # Sagas
    "SagaBase",
    "SagaStep",
    "SagaManager",
    "SagaInstance",
    "SagaStepResult",
    # Read Models
    "ReadModelStore",
    "ReadModelDocument",
    "ReadModelQueryBuilder",
    "QueryFilter",
    # Middleware
    "MetricsCollector",
    "MetricsSnapshot",
    "AuthorizationPolicy",
    "AuthorizingMiddleware",
    "IdempotencyMiddleware",
    "ValidationMiddleware",
    "MetricsMiddleware",
    # Serialization
    "EventSerializer",
    "EventTypeRegistry",
    "EventUpCaster",
    "SimpleEventUpCaster",
    # Process Manager
    "ProcessManager",
    "ProcessInstance",
    "ProcessStep",
    "ProcessDefinition",
]
