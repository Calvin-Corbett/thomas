"""
Message queue module for Thomas - everything assistant.

A complete in-process message queue with pluggable backends,
supporting multiple delivery semantics, consumer groups, and
various persistence/monitoring strategies.
"""

from ._exceptions import (
    BackpressureError,
    ConsumerGroupError,
    DeadLetterError,
    OffsetError,
    PartitionError,
    PersistenceError,
    QueueError,
    SerializationError,
    TimeoutError,
    TopicAlreadyExistsError,
    TopicNotFoundError,
)
from ._types import (
    AckMode,
    ConsumerGroup,
    DeliveryMode,
    Message,
    QueueConfig,
    TopicConfig,
)
from .backpressure import BackpressureConfig, BackpressureManager
from .broker import Broker
from .consumer import Consumer, ConsumerConfig
from .dead_letter import DeadLetterConfig, DeadLetterQueue
from .middleware import (
    FilterMiddleware,
    HeaderMiddleware,
    LoggingMiddleware,
    MetricsMiddleware,
    Middleware,
    MiddlewarePipeline,
    RetryMiddleware,
    TimingMiddleware,
    TransformationMiddleware,
)
from .monitoring import QueueMonitor
from .persistence import PersistenceManager
from .producer import Producer, ProducerConfig
from .topic import Topic

__version__ = "1.0.0"

__all__ = [
    # Core types
    "Message",
    "DeliveryMode",
    "AckMode",
    "ConsumerGroup",
    "QueueConfig",
    "TopicConfig",
    # Exceptions
    "QueueError",
    "TopicNotFoundError",
    "TopicAlreadyExistsError",
    "ConsumerGroupError",
    "BackpressureError",
    "DeadLetterError",
    "SerializationError",
    "PartitionError",
    "OffsetError",
    "PersistenceError",
    "TimeoutError",
    # Core components
    "Broker",
    "Topic",
    "Producer",
    "Consumer",
    # Configuration
    "ProducerConfig",
    "ConsumerConfig",
    "BackpressureConfig",
    "DeadLetterConfig",
    # Advanced features
    "DeadLetterQueue",
    "BackpressureManager",
    "PersistenceManager",
    "QueueMonitor",
    # Middleware
    "Middleware",
    "MiddlewarePipeline",
    "LoggingMiddleware",
    "MetricsMiddleware",
    "TransformationMiddleware",
    "FilterMiddleware",
    "RetryMiddleware",
    "HeaderMiddleware",
    "TimingMiddleware",
]
