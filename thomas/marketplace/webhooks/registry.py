"""Webhook registry for managing subscriptions and event types."""

import re
from datetime import datetime
from urllib.parse import urlparse

from thomas.marketplace.webhooks._exceptions import (
    EndpointNotFound,
    InvalidWebhookURL,
    SubscriptionNotFound,
)
from thomas.marketplace.webhooks._types import (
    Endpoint,
    Filter,
    RateLimit,
    RetryPolicy,
    Secret,
    Subscription,
)


class WebhookRegistry:
    """Central registry for webhook subscriptions and endpoints.

    Manages:
    - Endpoint registration and lifecycle
    - Subscription management
    - Event type hierarchy
    - Secret management
    - Subscription versioning
    """

    def __init__(self) -> None:
        """Initialize the webhook registry."""
        self._endpoints: dict[str, Endpoint] = {}
        self._subscriptions: dict[str, Subscription] = {}
        self._event_types: set[str] = set()
        self._secrets: dict[str, Secret] = {}
        self._subscription_by_endpoint: dict[str, list[str]] = {}
        self._subscription_versions: dict[str, int] = {}

    def register_event_type(self, event_type: str) -> None:
        """Register a new event type.

        Supports hierarchical event types in dot notation (e.g., order.created).

        Args:
            event_type: The event type string to register.

        Raises:
            ValueError: If event type format is invalid.
        """
        if not event_type or not isinstance(event_type, str):
            raise ValueError("Event type must be a non-empty string")

        if not re.match(r"^[a-z]+(\.[a-z]+)*$", event_type):
            raise ValueError(
                f"Invalid event type format: {event_type}. " "Must be lowercase with dots (e.g., order.created)"
            )

        self._event_types.add(event_type)

    def unregister_event_type(self, event_type: str) -> None:
        """Unregister an event type.

        Args:
            event_type: The event type to unregister.
        """
        self._event_types.discard(event_type)

    def list_event_types(self, prefix: str | None = None) -> list[str]:
        """List registered event types.

        Args:
            prefix: Optional prefix to filter event types (e.g., "order" returns "order.*").

        Returns:
            List of event types, optionally filtered by prefix.
        """
        types = sorted(self._event_types)
        if prefix:
            types = [t for t in types if t.startswith(prefix)]
        return types

    def register_endpoint(
        self,
        url: str,
        description: str = "",
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 30,
        retry_policy: RetryPolicy | None = None,
        rate_limit: RateLimit | None = None,
    ) -> Endpoint:
        """Register a new webhook endpoint.

        Args:
            url: HTTPS URL for the endpoint.
            description: Optional description of the endpoint.
            headers: Optional custom HTTP headers.
            timeout_seconds: Request timeout in seconds.
            retry_policy: Retry configuration.
            rate_limit: Rate limiting configuration.

        Returns:
            The registered Endpoint object.

        Raises:
            InvalidWebhookURL: If URL is invalid.
        """
        self._validate_webhook_url(url)

        endpoint = Endpoint(
            url=url,
            description=description,
            headers=headers or {},
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy or RetryPolicy(),
            rate_limit=rate_limit or RateLimit(),
        )

        self._endpoints[endpoint.id] = endpoint
        self._subscription_by_endpoint[endpoint.id] = []
        return endpoint

    def update_endpoint(
        self,
        endpoint_id: str,
        url: str | None = None,
        description: str | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
        retry_policy: RetryPolicy | None = None,
        rate_limit: RateLimit | None = None,
        is_active: bool | None = None,
    ) -> Endpoint:
        """Update an existing endpoint.

        Args:
            endpoint_id: ID of the endpoint to update.
            url: New URL (optional).
            description: New description (optional).
            headers: New headers (optional).
            timeout_seconds: New timeout (optional).
            retry_policy: New retry policy (optional).
            rate_limit: New rate limit (optional).
            is_active: Active status (optional).

        Returns:
            The updated Endpoint object.

        Raises:
            EndpointNotFound: If endpoint doesn't exist.
            InvalidWebhookURL: If new URL is invalid.
        """
        endpoint = self._get_endpoint(endpoint_id)

        if url is not None:
            self._validate_webhook_url(url)
            endpoint.url = url

        if description is not None:
            endpoint.description = description
        if headers is not None:
            endpoint.headers = headers
        if timeout_seconds is not None:
            endpoint.timeout_seconds = timeout_seconds
        if retry_policy is not None:
            endpoint.retry_policy = retry_policy
        if rate_limit is not None:
            endpoint.rate_limit = rate_limit
        if is_active is not None:
            endpoint.is_active = is_active

        endpoint.updated_at = datetime.utcnow()
        return endpoint

    def get_endpoint(self, endpoint_id: str) -> Endpoint:
        """Get an endpoint by ID.

        Args:
            endpoint_id: ID of the endpoint.

        Returns:
            The Endpoint object.

        Raises:
            EndpointNotFound: If endpoint doesn't exist.
        """
        return self._get_endpoint(endpoint_id)

    def list_endpoints(self, active_only: bool = False) -> list[Endpoint]:
        """List all endpoints.

        Args:
            active_only: If True, only return active endpoints.

        Returns:
            List of Endpoint objects.
        """
        endpoints = list(self._endpoints.values())
        if active_only:
            endpoints = [e for e in endpoints if e.is_active]
        return sorted(endpoints, key=lambda e: e.created_at)

    def delete_endpoint(self, endpoint_id: str) -> None:
        """Delete an endpoint.

        Also deactivates all subscriptions for this endpoint.

        Args:
            endpoint_id: ID of the endpoint to delete.

        Raises:
            EndpointNotFound: If endpoint doesn't exist.
        """
        if endpoint_id not in self._endpoints:
            raise EndpointNotFound(endpoint_id)

        subscription_ids = self._subscription_by_endpoint.pop(endpoint_id, [])
        for sub_id in subscription_ids:
            if sub_id in self._subscriptions:
                self._subscriptions[sub_id].is_active = False

        del self._endpoints[endpoint_id]

    def register_subscription(
        self,
        endpoint_id: str,
        event_types: list[str],
        filters: list[Filter] | None = None,
        custom_headers: dict[str, str] | None = None,
        description: str = "",
    ) -> Subscription:
        """Register a new webhook subscription.

        Args:
            endpoint_id: ID of the endpoint to subscribe.
            event_types: List of event types to subscribe to.
            filters: Optional content-based filters.
            custom_headers: Optional custom headers for this subscription.
            description: Optional description.

        Returns:
            The registered Subscription object.

        Raises:
            EndpointNotFound: If endpoint doesn't exist.
            ValueError: If event types list is empty.
        """
        if not event_types:
            raise ValueError("At least one event type must be specified")

        self._get_endpoint(endpoint_id)

        subscription = Subscription(
            endpoint_id=endpoint_id,
            event_types=list(event_types),
            filters=filters or [],
            custom_headers=custom_headers or {},
            description=description,
        )

        self._subscriptions[subscription.id] = subscription
        self._subscription_by_endpoint[endpoint_id].append(subscription.id)
        self._subscription_versions[subscription.id] = 1

        return subscription

    def update_subscription(
        self,
        subscription_id: str,
        event_types: list[str] | None = None,
        filters: list[Filter] | None = None,
        custom_headers: dict[str, str] | None = None,
        description: str | None = None,
        is_active: bool | None = None,
        expected_version: int | None = None,
    ) -> Subscription:
        """Update a subscription with optimistic concurrency control.

        Args:
            subscription_id: ID of the subscription to update.
            event_types: New event types (optional).
            filters: New filters (optional).
            custom_headers: New custom headers (optional).
            description: New description (optional).
            is_active: New active status (optional).
            expected_version: Expected version for optimistic concurrency.

        Returns:
            The updated Subscription object.

        Raises:
            SubscriptionNotFound: If subscription doesn't exist.
            ValueError: If version mismatch (optimistic lock).
        """
        subscription = self._get_subscription(subscription_id)

        if expected_version is not None:
            current_version = self._subscription_versions.get(subscription_id, 1)
            if current_version != expected_version:
                raise ValueError(f"Version mismatch: expected {expected_version}, got {current_version}")

        if event_types is not None:
            if not event_types:
                raise ValueError("At least one event type must be specified")
            subscription.event_types = list(event_types)

        if filters is not None:
            subscription.filters = filters
        if custom_headers is not None:
            subscription.custom_headers = custom_headers
        if description is not None:
            subscription.description = description
        if is_active is not None:
            subscription.is_active = is_active

        subscription.updated_at = datetime.utcnow()
        subscription.version += 1
        self._subscription_versions[subscription_id] = subscription.version

        return subscription

    def get_subscription(self, subscription_id: str) -> Subscription:
        """Get a subscription by ID.

        Args:
            subscription_id: ID of the subscription.

        Returns:
            The Subscription object.

        Raises:
            SubscriptionNotFound: If subscription doesn't exist.
        """
        return self._get_subscription(subscription_id)

    def list_subscriptions(
        self,
        endpoint_id: str | None = None,
        event_type: str | None = None,
        active_only: bool = False,
    ) -> list[Subscription]:
        """List subscriptions with optional filtering.

        Args:
            endpoint_id: Filter by endpoint ID.
            event_type: Filter by event type.
            active_only: If True, only return active subscriptions.

        Returns:
            List of Subscription objects.

        Raises:
            EndpointNotFound: If endpoint_id is specified but doesn't exist.
        """
        subscriptions = list(self._subscriptions.values())

        if endpoint_id is not None:
            self._get_endpoint(endpoint_id)
            subscriptions = [s for s in subscriptions if s.endpoint_id == endpoint_id]

        if event_type is not None:
            subscriptions = [s for s in subscriptions if event_type in s.event_types]

        if active_only:
            subscriptions = [s for s in subscriptions if s.is_active]

        return sorted(subscriptions, key=lambda s: s.created_at)

    def delete_subscription(self, subscription_id: str) -> None:
        """Delete a subscription.

        Args:
            subscription_id: ID of the subscription to delete.

        Raises:
            SubscriptionNotFound: If subscription doesn't exist.
        """
        subscription = self._get_subscription(subscription_id)
        endpoint_id = subscription.endpoint_id

        del self._subscriptions[subscription_id]
        self._subscription_by_endpoint[endpoint_id].remove(subscription_id)
        self._subscription_versions.pop(subscription_id, None)

    def bulk_update_subscriptions(
        self,
        endpoint_id: str,
        new_url: str,
    ) -> list[str]:
        """Bulk migrate subscriptions to a new endpoint URL.

        Args:
            endpoint_id: ID of the endpoint to migrate.
            new_url: New URL for the endpoint.

        Returns:
            List of subscription IDs that were updated.

        Raises:
            EndpointNotFound: If endpoint doesn't exist.
            InvalidWebhookURL: If new URL is invalid.
        """
        self.update_endpoint(endpoint_id, url=new_url)
        subscription_ids = self._subscription_by_endpoint.get(endpoint_id, [])
        return subscription_ids

    def generate_secret(self, endpoint_id: str) -> Secret:
        """Generate a new HMAC secret for an endpoint.

        Args:
            endpoint_id: ID of the endpoint.

        Returns:
            The generated Secret object.

        Raises:
            EndpointNotFound: If endpoint doesn't exist.
        """
        self._get_endpoint(endpoint_id)

        secret = Secret()
        if endpoint_id not in self._secrets:
            self._secrets[endpoint_id] = []

        self._secrets[endpoint_id].append(secret)
        return secret

    def rotate_secret(self, endpoint_id: str) -> Secret:
        """Rotate the secret for an endpoint (new secret with grace period).

        Args:
            endpoint_id: ID of the endpoint.

        Returns:
            The new Secret object.

        Raises:
            EndpointNotFound: If endpoint doesn't exist.
        """
        self._get_endpoint(endpoint_id)

        if endpoint_id not in self._secrets:
            self._secrets[endpoint_id] = []

        old_secret = self.generate_secret(endpoint_id)
        old_secret.rotated_at = datetime.utcnow()

        return old_secret

    def list_secrets(self, endpoint_id: str, active_only: bool = True) -> list[Secret]:
        """List secrets for an endpoint.

        Args:
            endpoint_id: ID of the endpoint.
            active_only: If True, only return active secrets.

        Returns:
            List of Secret objects.

        Raises:
            EndpointNotFound: If endpoint doesn't exist.
        """
        self._get_endpoint(endpoint_id)

        secrets = self._secrets.get(endpoint_id, [])
        if active_only:
            secrets = [s for s in secrets if s.is_active]

        return sorted(secrets, key=lambda s: s.created_at)

    def get_subscriptions_for_event(self, event_type: str) -> list[Subscription]:
        """Get all active subscriptions for a specific event type.

        Args:
            event_type: The event type to find subscriptions for.

        Returns:
            List of active Subscription objects matching the event type.
        """
        return self.list_subscriptions(event_type=event_type, active_only=True)

    def _get_endpoint(self, endpoint_id: str) -> Endpoint:
        """Get an endpoint, raising EndpointNotFound if it doesn't exist."""
        if endpoint_id not in self._endpoints:
            raise EndpointNotFound(endpoint_id)
        return self._endpoints[endpoint_id]

    def _get_subscription(self, subscription_id: str) -> Subscription:
        """Get a subscription, raising SubscriptionNotFound if it doesn't exist."""
        if subscription_id not in self._subscriptions:
            raise SubscriptionNotFound(subscription_id)
        return self._subscriptions[subscription_id]

    def _validate_webhook_url(self, url: str) -> None:
        """Validate webhook URL format and protocol.

        Args:
            url: URL to validate.

        Raises:
            InvalidWebhookURL: If URL is invalid.
        """
        if not url:
            raise InvalidWebhookURL(url, "URL cannot be empty")

        try:
            parsed = urlparse(url)
        except Exception as e:
            raise InvalidWebhookURL(url, f"Failed to parse URL: {e}")

        if parsed.scheme not in ("http", "https"):
            raise InvalidWebhookURL(url, f"Invalid scheme: {parsed.scheme} (must be http or https)")

        if not parsed.netloc:
            raise InvalidWebhookURL(url, "URL missing hostname")

        if parsed.scheme == "http":
            raise InvalidWebhookURL(url, "HTTPS is required (not HTTP)")
