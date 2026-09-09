"""Type definitions for webhook management system.

This module defines all core data types used throughout the webhook platform,
including webhook subscriptions, events, deliveries, and configuration.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class DeliveryStatus(str, Enum):
    """Status of a webhook delivery attempt."""

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"
    SKIPPED = "skipped"


class EventType(str, Enum):
    """Hierarchical event types in dotted notation.

    Examples:
        - order.created
        - order.updated
        - order.cancelled
        - payment.completed
        - payment.failed
    """

    ORDER_CREATED = "order.created"
    ORDER_UPDATED = "order.updated"
    ORDER_CANCELLED = "order.cancelled"
    ORDER_COMPLETED = "order.completed"
    PAYMENT_COMPLETED = "payment.completed"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"
    USER_REGISTERED = "user.registered"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    INVOICE_CREATED = "invoice.created"
    INVOICE_PAID = "invoice.paid"


@dataclass
class EventPayload:
    """Payload of a webhook event.

    Attributes:
        data: The event data as a dictionary.
        metadata: Optional metadata about the event.
    """

    data: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert payload to dictionary."""
        return {"data": self.data, "metadata": self.metadata}


@dataclass
class Signature:
    """HMAC signature for webhook payload.

    Attributes:
        algorithm: Signature algorithm (e.g., "hmac-sha256").
        value: Hexadecimal signature value.
        timestamp: When the signature was generated.
    """

    algorithm: str
    value: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convert signature to dictionary."""
        return {
            "algorithm": self.algorithm,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Secret:
    """Webhook secret for HMAC signature generation.

    Attributes:
        id: Unique identifier for the secret.
        value: The secret key (kept confidential).
        algorithm: HMAC algorithm (default: hmac-sha256).
        created_at: When the secret was created.
        rotated_at: When the secret was last rotated.
        is_active: Whether this secret is currently active.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    value: str = field(default_factory=lambda: str(uuid4()).replace("-", ""))
    algorithm: str = "hmac-sha256"
    created_at: datetime = field(default_factory=datetime.utcnow)
    rotated_at: datetime | None = None
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding secret value."""
        return {
            "id": self.id,
            "algorithm": self.algorithm,
            "created_at": self.created_at.isoformat(),
            "rotated_at": self.rotated_at.isoformat() if self.rotated_at else None,
            "is_active": self.is_active,
        }


@dataclass
class Filter:
    """Event filter for subscription content-based routing.

    Supports JSONPath-like expressions and logical combinators.

    Attributes:
        expression: Filter expression (e.g., "$.order.total > 100").
        description: Human-readable description of the filter.
        enabled: Whether this filter is active.
    """

    expression: str
    description: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert filter to dictionary."""
        return {
            "expression": self.expression,
            "description": self.description,
            "enabled": self.enabled,
        }


@dataclass
class RetryPolicy:
    """Retry configuration for failed deliveries.

    Attributes:
        strategy: Retry strategy (fixed, exponential, fibonacci).
        max_attempts: Maximum number of retry attempts.
        base_delay_seconds: Base delay for first retry.
        max_delay_seconds: Maximum delay between retries.
        multiplier: Multiplier for exponential backoff.
        jitter: Whether to add random jitter to delays.
    """

    strategy: str = "exponential"  # fixed, exponential, fibonacci
    max_attempts: int = 5
    base_delay_seconds: int = 2
    max_delay_seconds: int = 3600  # 1 hour
    multiplier: float = 2.0
    jitter: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert retry policy to dictionary."""
        return {
            "strategy": self.strategy,
            "max_attempts": self.max_attempts,
            "base_delay_seconds": self.base_delay_seconds,
            "max_delay_seconds": self.max_delay_seconds,
            "multiplier": self.multiplier,
            "jitter": self.jitter,
        }


@dataclass
class RateLimit:
    """Rate limiting configuration per endpoint.

    Uses token bucket algorithm.

    Attributes:
        max_requests: Maximum requests per window.
        window_seconds: Time window in seconds.
        enabled: Whether rate limiting is enabled.
    """

    max_requests: int = 100
    window_seconds: int = 60
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert rate limit to dictionary."""
        return {
            "max_requests": self.max_requests,
            "window_seconds": self.window_seconds,
            "enabled": self.enabled,
        }


@dataclass
class Endpoint:
    """Webhook endpoint configuration.

    Attributes:
        id: Unique endpoint identifier.
        url: HTTPS URL where webhooks are delivered.
        description: Human-readable endpoint description.
        headers: Custom HTTP headers to include in requests.
        timeout_seconds: Request timeout in seconds.
        retry_policy: Retry configuration.
        rate_limit: Rate limiting configuration.
        created_at: When the endpoint was created.
        updated_at: When the endpoint was last updated.
        is_active: Whether the endpoint is active.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    url: str = ""
    description: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 30
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    rate_limit: RateLimit = field(default_factory=RateLimit)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert endpoint to dictionary."""
        return {
            "id": self.id,
            "url": self.url,
            "description": self.description,
            "headers": self.headers,
            "timeout_seconds": self.timeout_seconds,
            "retry_policy": self.retry_policy.to_dict(),
            "rate_limit": self.rate_limit.to_dict(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
        }


@dataclass
class Subscription:
    """Webhook subscription.

    Attributes:
        id: Unique subscription identifier.
        endpoint_id: ID of the endpoint receiving webhooks.
        event_types: List of event types this subscription receives.
        filters: Optional filters for content-based routing.
        custom_headers: Custom headers for this subscription.
        version: Subscription version for optimistic concurrency.
        created_at: When the subscription was created.
        updated_at: When the subscription was last updated.
        is_active: Whether the subscription is active.
        description: Human-readable subscription description.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    endpoint_id: str = ""
    event_types: list[str] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    custom_headers: dict[str, str] = field(default_factory=dict)
    version: int = 1
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert subscription to dictionary."""
        return {
            "id": self.id,
            "endpoint_id": self.endpoint_id,
            "event_types": self.event_types,
            "filters": [f.to_dict() for f in self.filters],
            "custom_headers": self.custom_headers,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
            "description": self.description,
        }


@dataclass
class WebhookEvent:
    """Webhook event to be delivered.

    Attributes:
        id: Unique event identifier.
        type: Event type (hierarchical, e.g., "order.created").
        payload: Event payload data.
        timestamp: When the event occurred.
        source: Source system that generated the event.
        version: Event schema version.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    type: str = ""
    payload: EventPayload = field(default_factory=lambda: EventPayload({}))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = ""
    version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload.to_dict(),
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "version": self.version,
        }


@dataclass
class DeliveryAttempt:
    """Single delivery attempt record.

    Attributes:
        attempt_number: Which attempt this is (1-based).
        status: Delivery status.
        status_code: HTTP status code if applicable.
        error_message: Error message if delivery failed.
        response_body: Response body from endpoint.
        latency_ms: Request latency in milliseconds.
        timestamp: When this attempt was made.
    """

    attempt_number: int = 1
    status: DeliveryStatus = DeliveryStatus.PENDING
    status_code: int | None = None
    error_message: str | None = None
    response_body: str | None = None
    latency_ms: int | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert attempt to dictionary."""
        return {
            "attempt_number": self.attempt_number,
            "status": self.status.value,
            "status_code": self.status_code,
            "error_message": self.error_message,
            "response_body": self.response_body,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Delivery:
    """Webhook delivery record.

    Attributes:
        id: Unique delivery identifier.
        subscription_id: Subscription this delivery is for.
        event_id: Event being delivered.
        status: Current delivery status.
        attempts: List of delivery attempts.
        next_retry_at: When next retry is scheduled.
        permanent_failure_reason: Reason if permanently failed.
        created_at: When delivery was initiated.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    subscription_id: str = ""
    event_id: str = ""
    status: DeliveryStatus = DeliveryStatus.PENDING
    attempts: list[DeliveryAttempt] = field(default_factory=list)
    next_retry_at: datetime | None = None
    permanent_failure_reason: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert delivery to dictionary."""
        return {
            "id": self.id,
            "subscription_id": self.subscription_id,
            "event_id": self.event_id,
            "status": self.status.value,
            "attempts": [a.to_dict() for a in self.attempts],
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "permanent_failure_reason": self.permanent_failure_reason,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class WebhookLog:
    """Log entry for webhook activities.

    Attributes:
        id: Unique log entry identifier.
        event_id: Associated event ID.
        subscription_id: Associated subscription ID.
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        message: Log message.
        details: Additional structured details.
        timestamp: When the log entry was created.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    event_id: str = ""
    subscription_id: str = ""
    level: str = "INFO"
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert log to dictionary."""
        return {
            "id": self.id,
            "event_id": self.event_id,
            "subscription_id": self.subscription_id,
            "level": self.level,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }
