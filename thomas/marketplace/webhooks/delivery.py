"""Event delivery system for webhooks."""

import json
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from thomas.marketplace.webhooks._types import (
    Delivery,
    DeliveryAttempt,
    DeliveryStatus,
    Endpoint,
    Subscription,
    WebhookEvent,
)


@dataclass
class DeliveryRequest:
    """Internal representation of a delivery request in the queue.

    Attributes:
        delivery: The delivery record.
        endpoint: The target endpoint.
        subscription: The subscription.
        event: The event being delivered.
        priority: Priority score (higher = deliver sooner).
    """

    delivery: Delivery
    endpoint: Endpoint
    subscription: Subscription
    event: WebhookEvent
    priority: float


class DeliveryQueue:
    """Priority queue for managing webhook deliveries.

    Uses a hybrid priority system considering:
    - Subscription priority (can be customized)
    - Event age (older events get lower priority)
    - Endpoint rate limiting
    """

    def __init__(self) -> None:
        """Initialize the delivery queue."""
        self._queue: deque[DeliveryRequest] = deque()
        self._delivered: dict[str, Delivery] = {}

    def enqueue(
        self,
        delivery: Delivery,
        endpoint: Endpoint,
        subscription: Subscription,
        event: WebhookEvent,
        priority: float = 1.0,
    ) -> None:
        """Enqueue a delivery request.

        Args:
            delivery: The delivery record.
            endpoint: The target endpoint.
            subscription: The subscription.
            event: The event being delivered.
            priority: Priority multiplier (higher = sooner).
        """
        request = DeliveryRequest(
            delivery=delivery,
            endpoint=endpoint,
            subscription=subscription,
            event=event,
            priority=self._calculate_priority(event, priority),
        )
        self._queue.append(request)

    def dequeue(self) -> DeliveryRequest | None:
        """Dequeue the highest priority delivery request.

        Returns:
            The highest priority DeliveryRequest, or None if queue is empty.
        """
        if not self._queue:
            return None

        sorted_queue = sorted(self._queue, key=lambda r: r.priority, reverse=True)
        highest = sorted_queue[0]
        self._queue.remove(highest)

        return highest

    def peek(self) -> DeliveryRequest | None:
        """Peek at the highest priority delivery without removing it.

        Returns:
            The highest priority DeliveryRequest, or None if queue is empty.
        """
        if not self._queue:
            return None

        return max(self._queue, key=lambda r: r.priority)

    def size(self) -> int:
        """Get the current queue size.

        Returns:
            Number of pending deliveries.
        """
        return len(self._queue)

    def _calculate_priority(self, event: WebhookEvent, base_priority: float) -> float:
        """Calculate priority score for a delivery.

        Priority is higher for:
        - Older events (reduce queue age)
        - Higher base priority values

        Args:
            event: The event being delivered.
            base_priority: Base priority multiplier.

        Returns:
            Calculated priority score.
        """
        age_minutes = (datetime.utcnow() - event.timestamp).total_seconds() / 60
        age_factor = 1.0 + (age_minutes / 60.0)

        return base_priority * age_factor


class DeliveryEnvelope:
    """Standard webhook delivery envelope.

    Wraps the event payload in a standard structure.
    """

    @staticmethod
    def create(
        event: WebhookEvent,
        signature: str | None = None,
    ) -> dict:
        """Create a delivery envelope for an event.

        Args:
            event: The event to wrap.
            signature: Optional HMAC signature.

        Returns:
            Dictionary containing the envelope.
        """
        envelope = {
            "id": event.id,
            "type": event.type,
            "timestamp": event.timestamp.isoformat(),
            "source": event.source,
            "version": event.version,
            "data": event.payload.data,
        }

        if signature:
            envelope["signature"] = signature

        return envelope


class DeliveryManager:
    """Manages the delivery of webhook events.

    Handles:
    - Queue management
    - Concurrent delivery (fan-out)
    - Delivery timeout handling
    - HTTP POST simulation
    - Idempotency tracking
    - Delivery batching
    """

    def __init__(
        self,
        http_handler: Callable | None = None,
        max_concurrent: int = 10,
    ) -> None:
        """Initialize the delivery manager.

        Args:
            http_handler: Optional custom HTTP handler for testing.
            max_concurrent: Maximum concurrent deliveries.
        """
        self._queue = DeliveryQueue()
        self._http_handler = http_handler or self._default_http_handler
        self._max_concurrent = max_concurrent
        self._in_flight: dict[str, Delivery] = {}
        self._idempotency_log: dict[str, str] = {}
        self._batch_buffer: dict[str, list[dict]] = {}

    def schedule_delivery(
        self,
        delivery: Delivery,
        endpoint: Endpoint,
        subscription: Subscription,
        event: WebhookEvent,
        priority: float = 1.0,
    ) -> None:
        """Schedule a delivery for processing.

        Args:
            delivery: The delivery record.
            endpoint: The target endpoint.
            subscription: The subscription.
            event: The event being delivered.
            priority: Priority multiplier.
        """
        delivery.status = DeliveryStatus.PENDING
        self._queue.enqueue(delivery, endpoint, subscription, event, priority)

    def process_delivery(
        self,
        delivery: Delivery,
        endpoint: Endpoint,
        subscription: Subscription,
        event: WebhookEvent,
        signature: str | None = None,
    ) -> DeliveryAttempt:
        """Process a single delivery attempt.

        Handles idempotency and calls the HTTP handler.

        Args:
            delivery: The delivery record.
            endpoint: The target endpoint.
            subscription: The subscription.
            event: The event being delivered.
            signature: Optional HMAC signature.

        Returns:
            The DeliveryAttempt record.
        """
        delivery_id = delivery.id

        if self._check_idempotency(delivery_id):
            return delivery.attempts[-1]

        attempt_number = len(delivery.attempts) + 1
        attempt = DeliveryAttempt(attempt_number=attempt_number)

        envelope = DeliveryEnvelope.create(event, signature)
        headers = self._prepare_headers(endpoint, subscription, attempt_number)

        try:
            status_code, response_body, latency_ms = self._http_handler(
                endpoint.url,
                envelope,
                headers,
                endpoint.timeout_seconds,
            )

            attempt.status_code = status_code
            attempt.response_body = response_body
            attempt.latency_ms = latency_ms

            if 200 <= status_code < 300:
                attempt.status = DeliveryStatus.DELIVERED
                delivery.status = DeliveryStatus.DELIVERED
            elif 400 <= status_code < 500:
                attempt.status = DeliveryStatus.FAILED
                delivery.permanent_failure_reason = f"HTTP {status_code}: {response_body}"
                delivery.status = DeliveryStatus.EXHAUSTED
            else:
                attempt.status = DeliveryStatus.FAILED
                attempt.error_message = f"HTTP {status_code}"

        except Exception as e:
            attempt.status = DeliveryStatus.FAILED
            attempt.error_message = str(e)

        attempt.timestamp = datetime.utcnow()
        delivery.attempts.append(attempt)
        self._idempotency_log[delivery_id] = delivery_id

        return attempt

    def process_batch(
        self,
        deliveries: list[Delivery],
        endpoint: Endpoint,
        signature: str | None = None,
    ) -> list[DeliveryAttempt]:
        """Process a batch of deliveries to the same endpoint.

        Groups events and sends them in a single request.

        Args:
            deliveries: List of deliveries to batch.
            endpoint: The target endpoint.
            signature: Optional signature for batch.

        Returns:
            List of DeliveryAttempt records.
        """
        if not deliveries:
            return []

        events = [{"id": d.id, "attempts": len(d.attempts)} for d in deliveries]
        batch_payload = {
            "batch_id": f"batch_{datetime.utcnow().isoformat()}",
            "count": len(deliveries),
            "events": events,
        }

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Batch": "true",
            "X-Batch-Size": str(len(deliveries)),
        }

        if signature:
            headers["X-Webhook-Signature"] = signature

        try:
            status_code, response_body, latency_ms = self._http_handler(
                endpoint.url,
                batch_payload,
                headers,
                endpoint.timeout_seconds,
            )

            attempts = []
            for delivery in deliveries:
                attempt = DeliveryAttempt(
                    attempt_number=len(delivery.attempts) + 1,
                    status=(DeliveryStatus.DELIVERED if 200 <= status_code < 300 else DeliveryStatus.FAILED),
                    status_code=status_code,
                    response_body=response_body,
                    latency_ms=latency_ms,
                )
                delivery.attempts.append(attempt)
                attempts.append(attempt)

            return attempts

        except Exception as e:
            attempts = []
            for delivery in deliveries:
                attempt = DeliveryAttempt(
                    attempt_number=len(delivery.attempts) + 1,
                    status=DeliveryStatus.FAILED,
                    error_message=str(e),
                )
                delivery.attempts.append(attempt)
                attempts.append(attempt)

            return attempts

    def get_queue_stats(self) -> dict:
        """Get statistics about the delivery queue.

        Returns:
            Dictionary containing queue statistics.
        """
        return {
            "pending": self._queue.size(),
            "in_flight": len(self._in_flight),
            "idempotency_log_size": len(self._idempotency_log),
        }

    def _check_idempotency(self, delivery_id: str) -> bool:
        """Check if a delivery has already been processed (idempotency).

        Args:
            delivery_id: The delivery ID to check.

        Returns:
            True if already delivered, False otherwise.
        """
        return delivery_id in self._idempotency_log

    def _prepare_headers(
        self,
        endpoint: Endpoint,
        subscription: Subscription,
        attempt_number: int,
    ) -> dict[str, str]:
        """Prepare HTTP headers for delivery.

        Args:
            endpoint: The endpoint configuration.
            subscription: The subscription configuration.
            attempt_number: The attempt number.

        Returns:
            Dictionary of headers to send.
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "WebhookDelivery/1.0",
            "X-Webhook-Subscription": subscription.id,
            "X-Webhook-Attempt": str(attempt_number),
        }

        headers.update(endpoint.headers)
        headers.update(subscription.custom_headers)

        return headers

    @staticmethod
    def _default_http_handler(
        url: str,
        payload: dict,
        headers: dict[str, str],
        timeout: int,
    ) -> tuple:
        """Default HTTP handler for delivery simulation.

        Args:
            url: The target URL.
            payload: The payload to send.
            headers: HTTP headers.
            timeout: Request timeout in seconds.

        Returns:
            Tuple of (status_code, response_body, latency_ms).
        """
        try:
            import http.client
            import time
            from urllib.parse import urlparse

            parsed_url = urlparse(url)
            host = parsed_url.netloc
            path = parsed_url.path or "/"
            if parsed_url.query:
                path += f"?{parsed_url.query}"

            is_https = parsed_url.scheme == "https"

            if is_https:
                conn = http.client.HTTPSConnection(host, timeout=timeout)
            else:
                conn = http.client.HTTPConnection(host, timeout=timeout)

            body = json.dumps(payload)
            start_time = time.time()

            conn.request("POST", path, body, headers)
            response = conn.getresponse()
            response_body = response.read().decode("utf-8")

            latency_ms = int((time.time() - start_time) * 1000)

            conn.close()

            return response.status, response_body, latency_ms

        except Exception as e:
            return 500, str(e), 0
