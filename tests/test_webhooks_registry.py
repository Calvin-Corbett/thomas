"""Tests for webhook registry functionality."""

import pytest

from thomas.marketplace.webhooks._exceptions import (
    EndpointNotFound,
    InvalidWebhookURL,
    SubscriptionNotFound,
)
from thomas.marketplace.webhooks._types import Filter
from thomas.marketplace.webhooks.registry import WebhookRegistry


class TestEventTypeManagement:
    """Test event type registration and querying."""

    def test_register_event_type(self):
        """Test registering a single event type."""
        registry = WebhookRegistry()
        registry.register_event_type("order.created")

        assert "order.created" in registry.list_event_types()

    def test_register_multiple_event_types(self):
        """Test registering multiple event types."""
        registry = WebhookRegistry()
        types = ["order.created", "order.updated", "payment.completed"]

        for t in types:
            registry.register_event_type(t)

        assert set(registry.list_event_types()) == set(types)

    def test_invalid_event_type_format(self):
        """Test that invalid event type format raises error."""
        registry = WebhookRegistry()

        with pytest.raises(ValueError):
            registry.register_event_type("INVALID_TYPE")

        with pytest.raises(ValueError):
            registry.register_event_type("order..created")

    def test_list_event_types_with_prefix(self):
        """Test filtering event types by prefix."""
        registry = WebhookRegistry()
        registry.register_event_type("order.created")
        registry.register_event_type("order.updated")
        registry.register_event_type("payment.completed")

        order_types = registry.list_event_types(prefix="order")
        assert len(order_types) == 2
        assert all(t.startswith("order") for t in order_types)

    def test_unregister_event_type(self):
        """Test unregistering an event type."""
        registry = WebhookRegistry()
        registry.register_event_type("order.created")
        registry.unregister_event_type("order.created")

        assert "order.created" not in registry.list_event_types()


class TestEndpointManagement:
    """Test endpoint registration and management."""

    def test_register_endpoint(self):
        """Test registering a webhook endpoint."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(
            url="https://example.com/webhooks",
            description="Test endpoint",
        )

        assert endpoint.url == "https://example.com/webhooks"
        assert endpoint.description == "Test endpoint"
        assert endpoint.is_active

    def test_register_endpoint_with_custom_headers(self):
        """Test registering endpoint with custom headers."""
        registry = WebhookRegistry()
        headers = {"Authorization": "Bearer token123"}

        endpoint = registry.register_endpoint(
            url="https://example.com/webhooks",
            headers=headers,
        )

        assert endpoint.headers == headers

    def test_invalid_webhook_url(self):
        """Test that invalid URLs raise error."""
        registry = WebhookRegistry()

        with pytest.raises(InvalidWebhookURL):
            registry.register_endpoint(url="http://example.com/webhooks")

        with pytest.raises(InvalidWebhookURL):
            registry.register_endpoint(url="not-a-url")

    def test_update_endpoint(self):
        """Test updating an endpoint."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")

        updated = registry.update_endpoint(
            endpoint.id,
            url="https://example.com/webhooks-v2",
            is_active=False,
        )

        assert updated.url == "https://example.com/webhooks-v2"
        assert not updated.is_active

    def test_get_endpoint(self):
        """Test retrieving an endpoint."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")

        retrieved = registry.get_endpoint(endpoint.id)
        assert retrieved.id == endpoint.id
        assert retrieved.url == endpoint.url

    def test_get_nonexistent_endpoint(self):
        """Test that getting nonexistent endpoint raises error."""
        registry = WebhookRegistry()

        with pytest.raises(EndpointNotFound):
            registry.get_endpoint("nonexistent")

    def test_list_endpoints(self):
        """Test listing endpoints."""
        registry = WebhookRegistry()
        ep1 = registry.register_endpoint(url="https://example1.com/webhooks")
        ep2 = registry.register_endpoint(url="https://example2.com/webhooks")

        endpoints = registry.list_endpoints()
        assert len(endpoints) == 2
        assert {e.id for e in endpoints} == {ep1.id, ep2.id}

    def test_list_active_endpoints_only(self):
        """Test listing only active endpoints."""
        registry = WebhookRegistry()
        ep1 = registry.register_endpoint(url="https://example1.com/webhooks")
        ep2 = registry.register_endpoint(url="https://example2.com/webhooks")

        registry.update_endpoint(ep2.id, is_active=False)

        active = registry.list_endpoints(active_only=True)
        assert len(active) == 1
        assert active[0].id == ep1.id

    def test_delete_endpoint(self):
        """Test deleting an endpoint."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")

        registry.delete_endpoint(endpoint.id)

        with pytest.raises(EndpointNotFound):
            registry.get_endpoint(endpoint.id)


class TestSubscriptionManagement:
    """Test subscription registration and management."""

    def test_register_subscription(self):
        """Test registering a subscription."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")
        registry.register_event_type("order.created")

        sub = registry.register_subscription(
            endpoint_id=endpoint.id,
            event_types=["order.created"],
        )

        assert sub.endpoint_id == endpoint.id
        assert "order.created" in sub.event_types
        assert sub.is_active

    def test_register_subscription_with_filters(self):
        """Test registering subscription with filters."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")
        registry.register_event_type("order.created")

        filters = [Filter(expression="$.total > 100", description="Large orders")]
        sub = registry.register_subscription(
            endpoint_id=endpoint.id,
            event_types=["order.created"],
            filters=filters,
        )

        assert len(sub.filters) == 1
        assert sub.filters[0].expression == "$.total > 100"

    def test_register_subscription_no_event_types(self):
        """Test that subscription requires at least one event type."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")

        with pytest.raises(ValueError):
            registry.register_subscription(
                endpoint_id=endpoint.id,
                event_types=[],
            )

    def test_update_subscription(self):
        """Test updating a subscription."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")
        registry.register_event_type("order.created")
        registry.register_event_type("order.updated")

        sub = registry.register_subscription(
            endpoint_id=endpoint.id,
            event_types=["order.created"],
        )

        updated = registry.update_subscription(
            sub.id,
            event_types=["order.created", "order.updated"],
        )

        assert "order.updated" in updated.event_types
        assert updated.version == 2

    def test_subscription_optimistic_locking(self):
        """Test optimistic concurrency control for subscriptions."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")
        registry.register_event_type("order.created")

        sub = registry.register_subscription(
            endpoint_id=endpoint.id,
            event_types=["order.created"],
        )

        with pytest.raises(ValueError):
            registry.update_subscription(
                sub.id,
                expected_version=99,
            )

    def test_get_subscription(self):
        """Test retrieving a subscription."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")
        registry.register_event_type("order.created")

        sub = registry.register_subscription(
            endpoint_id=endpoint.id,
            event_types=["order.created"],
        )

        retrieved = registry.get_subscription(sub.id)
        assert retrieved.id == sub.id

    def test_list_subscriptions_by_endpoint(self):
        """Test listing subscriptions for an endpoint."""
        registry = WebhookRegistry()
        ep1 = registry.register_endpoint(url="https://example1.com/webhooks")
        ep2 = registry.register_endpoint(url="https://example2.com/webhooks")
        registry.register_event_type("order.created")

        sub1 = registry.register_subscription(
            endpoint_id=ep1.id,
            event_types=["order.created"],
        )
        registry.register_subscription(
            endpoint_id=ep2.id,
            event_types=["order.created"],
        )

        subs = registry.list_subscriptions(endpoint_id=ep1.id)
        assert len(subs) == 1
        assert subs[0].id == sub1.id

    def test_list_subscriptions_by_event_type(self):
        """Test listing subscriptions by event type."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")
        registry.register_event_type("order.created")
        registry.register_event_type("order.updated")

        registry.register_subscription(
            endpoint_id=endpoint.id,
            event_types=["order.created"],
        )
        sub2 = registry.register_subscription(
            endpoint_id=endpoint.id,
            event_types=["order.created", "order.updated"],
        )

        subs = registry.list_subscriptions(event_type="order.updated")
        assert len(subs) == 1
        assert subs[0].id == sub2.id

    def test_delete_subscription(self):
        """Test deleting a subscription."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")
        registry.register_event_type("order.created")

        sub = registry.register_subscription(
            endpoint_id=endpoint.id,
            event_types=["order.created"],
        )

        registry.delete_subscription(sub.id)

        with pytest.raises(SubscriptionNotFound):
            registry.get_subscription(sub.id)


class TestSecretManagement:
    """Test secret generation and rotation."""

    def test_generate_secret(self):
        """Test generating a new secret."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")

        secret = registry.generate_secret(endpoint.id)

        assert secret.value
        assert secret.algorithm == "hmac-sha256"
        assert secret.is_active

    def test_rotate_secret(self):
        """Test secret rotation."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")

        secret1 = registry.generate_secret(endpoint.id)
        secret2 = registry.rotate_secret(endpoint.id)

        assert secret1.id != secret2.id
        assert secret1.rotated_at is not None

    def test_list_secrets_active_only(self):
        """Test listing active secrets."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")

        secret = registry.generate_secret(endpoint.id)

        secrets = registry.list_secrets(endpoint.id, active_only=True)
        assert len(secrets) >= 1
        assert secret.is_active


class TestBulkOperations:
    """Test bulk operations."""

    def test_bulk_update_subscriptions(self):
        """Test bulk migration of subscriptions."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")
        registry.register_event_type("order.created")

        sub1 = registry.register_subscription(
            endpoint_id=endpoint.id,
            event_types=["order.created"],
        )
        sub2 = registry.register_subscription(
            endpoint_id=endpoint.id,
            event_types=["order.created"],
        )

        result = registry.bulk_update_subscriptions(
            endpoint.id,
            "https://example.com/webhooks-v2",
        )

        assert len(result) == 2
        assert {sub1.id, sub2.id} == set(result)

        endpoint_updated = registry.get_endpoint(endpoint.id)
        assert endpoint_updated.url == "https://example.com/webhooks-v2"


class TestGetSubscriptionsForEvent:
    """Test querying subscriptions by event."""

    def test_get_subscriptions_for_event(self):
        """Test retrieving subscriptions for a specific event."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")
        registry.register_event_type("order.created")

        sub = registry.register_subscription(
            endpoint_id=endpoint.id,
            event_types=["order.created"],
        )

        subs = registry.get_subscriptions_for_event("order.created")
        assert len(subs) == 1
        assert subs[0].id == sub.id

    def test_get_subscriptions_for_event_inactive_excluded(self):
        """Test that inactive subscriptions are excluded."""
        registry = WebhookRegistry()
        endpoint = registry.register_endpoint(url="https://example.com/webhooks")
        registry.register_event_type("order.created")

        sub = registry.register_subscription(
            endpoint_id=endpoint.id,
            event_types=["order.created"],
        )

        registry.update_subscription(sub.id, is_active=False)

        subs = registry.get_subscriptions_for_event("order.created")
        assert len(subs) == 0
