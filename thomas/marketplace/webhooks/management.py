"""Management and administration APIs for webhooks."""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from thomas.marketplace.webhooks._types import (
    Delivery,
    DeliveryStatus,
    Subscription,
)


class WebhookAdmin:
    """Administrative API for webhook management.

    Provides:
    - Subscription lifecycle management
    - Event replay
    - Bulk operations
    - Usage reporting
    """

    def __init__(self, registry: Any = None, delivery_manager: Any = None) -> None:
        """Initialize webhook admin.

        Args:
            registry: Webhook registry instance.
            delivery_manager: Delivery manager instance.
        """
        self.registry = registry
        self.delivery_manager = delivery_manager
        self._delivery_history: list[Delivery] = []
        self._pause_status: dict[str, bool] = {}

    def pause_subscription(self, subscription_id: str) -> bool:
        """Pause a subscription (stop receiving events).

        Args:
            subscription_id: ID of subscription to pause.

        Returns:
            True if successfully paused.
        """
        if self.registry:
            try:
                subscription = self.registry.get_subscription(subscription_id)
                subscription.is_active = False
                self._pause_status[subscription_id] = True
                return True
            except Exception:  # REVIEWED: broad catch
                return False

        return False

    def resume_subscription(self, subscription_id: str) -> bool:
        """Resume a paused subscription.

        Args:
            subscription_id: ID of subscription to resume.

        Returns:
            True if successfully resumed.
        """
        if self.registry:
            try:
                subscription = self.registry.get_subscription(subscription_id)
                subscription.is_active = True
                self._pause_status[subscription_id] = False
                return True
            except Exception:  # REVIEWED: broad catch
                return False

        return False

    def is_paused(self, subscription_id: str) -> bool:
        """Check if subscription is paused.

        Args:
            subscription_id: ID of subscription.

        Returns:
            True if paused.
        """
        return self._pause_status.get(subscription_id, False)

    def list_all_subscriptions(self) -> list[Subscription]:
        """List all subscriptions across all endpoints.

        Returns:
            List of Subscription objects.
        """
        if self.registry:
            return self.registry.list_subscriptions()

        return []

    def force_retry_delivery(
        self,
        delivery_id: str,
        reset_attempts: bool = False,
    ) -> bool:
        """Force retry of a failed delivery.

        Args:
            delivery_id: ID of delivery to retry.
            reset_attempts: Whether to reset attempt count.

        Returns:
            True if retry was scheduled.
        """
        delivery = None

        for d in self._delivery_history:
            if d.id == delivery_id:
                delivery = d
                break

        if not delivery:
            return False

        if reset_attempts:
            delivery.attempts.clear()

        delivery.status = DeliveryStatus.RETRYING
        delivery.next_retry_at = datetime.utcnow()

        if self.delivery_manager:
            try:
                self.delivery_manager.schedule_delivery(
                    delivery,
                    delivery.subscription_id,
                    delivery.event_id,
                )
                return True
            except Exception:  # REVIEWED: broad catch
                return False

        return True

    def record_delivery(self, delivery: Delivery) -> None:
        """Record a delivery for management tracking.

        Args:
            delivery: The delivery record.
        """
        self._delivery_history.append(delivery)

    def replay_events(
        self,
        start_time: datetime,
        end_time: datetime,
        event_type: str | None = None,
        subscription_id: str | None = None,
    ) -> list[Delivery]:
        """Replay (re-deliver) events from a time range.

        Args:
            start_time: Start of time range.
            end_time: End of time range.
            event_type: Optional filter by event type.
            subscription_id: Optional filter by subscription.

        Returns:
            List of delivery records created for replay.
        """
        replayed = []

        for delivery in self._delivery_history:
            if not (start_time <= delivery.created_at <= end_time):
                continue

            if event_type and delivery.event_id != event_type:
                continue

            if subscription_id and delivery.subscription_id != subscription_id:
                continue

            new_delivery = Delivery(
                subscription_id=delivery.subscription_id,
                event_id=delivery.event_id,
                status=DeliveryStatus.PENDING,
            )
            replayed.append(new_delivery)

        return replayed

    def get_delivery_status(self, delivery_id: str) -> dict | None:
        """Get status of a delivery.

        Args:
            delivery_id: ID of delivery.

        Returns:
            Delivery status dictionary, or None if not found.
        """
        for delivery in self._delivery_history:
            if delivery.id == delivery_id:
                return {
                    "id": delivery.id,
                    "status": delivery.status.value,
                    "attempts": len(delivery.attempts),
                    "created_at": delivery.created_at.isoformat(),
                    "next_retry_at": (delivery.next_retry_at.isoformat() if delivery.next_retry_at else None),
                }

        return None


class SubscriptionMigrator:
    """Migrate subscriptions between endpoints."""

    def __init__(self, registry: Any = None) -> None:
        """Initialize migrator.

        Args:
            registry: Webhook registry instance.
        """
        self.registry = registry
        self._migration_log: list[dict] = []

    def migrate_endpoint(
        self,
        old_endpoint_id: str,
        new_endpoint_id: str,
    ) -> dict:
        """Migrate all subscriptions from old to new endpoint.

        Args:
            old_endpoint_id: ID of endpoint to migrate from.
            new_endpoint_id: ID of endpoint to migrate to.

        Returns:
            Migration result dictionary.
        """
        if not self.registry:
            return {"success": False, "migrated": 0, "error": "No registry"}

        try:
            old_subs = self.registry.list_subscriptions(endpoint_id=old_endpoint_id)

            migrated = 0

            for sub in old_subs:
                new_sub = self.registry.register_subscription(
                    endpoint_id=new_endpoint_id,
                    event_types=sub.event_types,
                    filters=sub.filters,
                    custom_headers=sub.custom_headers,
                    description=f"Migrated: {sub.description}",
                )

                self.registry.delete_subscription(sub.id)
                migrated += 1

            result = {
                "success": True,
                "old_endpoint_id": old_endpoint_id,
                "new_endpoint_id": new_endpoint_id,
                "migrated": migrated,
            }

            self._migration_log.append(result)
            return result

        except Exception as e:
            return {
                "success": False,
                "migrated": 0,
                "error": str(e),
            }

    def update_endpoint_urls_bulk(
        self,
        url_mapping: dict[str, str],
    ) -> dict:
        """Update endpoint URLs in bulk.

        Args:
            url_mapping: Dictionary of endpoint_id -> new_url.

        Returns:
            Update result dictionary.
        """
        if not self.registry:
            return {"success": False, "updated": 0, "error": "No registry"}

        updated = 0

        for endpoint_id, new_url in url_mapping.items():
            try:
                self.registry.update_endpoint(endpoint_id, url=new_url)
                updated += 1
            except (ValueError, TypeError):
                pass

        return {
            "success": True,
            "updated": updated,
            "total": len(url_mapping),
        }

    def get_migration_log(self) -> list[dict]:
        """Get migration history.

        Returns:
            List of migration records.
        """
        return list(self._migration_log)


class UsageReporter:
    """Reports webhook usage statistics."""

    def __init__(self) -> None:
        """Initialize usage reporter."""
        self._delivery_log: list[tuple[datetime, str, str]] = []

    def record_delivery(
        self,
        timestamp: datetime,
        event_type: str,
        subscription_id: str,
    ) -> None:
        """Record a delivery for usage tracking.

        Args:
            timestamp: When delivery occurred.
            event_type: Type of event.
            subscription_id: ID of subscription.
        """
        self._delivery_log.append((timestamp, event_type, subscription_id))

    def get_usage_summary(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """Get usage summary for a time period.

        Args:
            start_time: Start of period.
            end_time: End of period.

        Returns:
            Usage summary dictionary.
        """
        relevant = [(ts, et, sub_id) for ts, et, sub_id in self._delivery_log if start_time <= ts <= end_time]

        total = len(relevant)
        by_event = defaultdict(int)
        by_subscription = defaultdict(int)

        for _, et, sub_id in relevant:
            by_event[et] += 1
            by_subscription[sub_id] += 1

        return {
            "period": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
            },
            "total_deliveries": total,
            "by_event_type": dict(by_event),
            "by_subscription": dict(by_subscription),
        }

    def get_usage_by_period(
        self,
        start_time: datetime,
        period_minutes: int = 60,
    ) -> list[dict]:
        """Get usage breakdown by time periods.

        Args:
            start_time: Start time.
            period_minutes: Period length in minutes.

        Returns:
            List of period usage dictionaries.
        """
        periods = []
        current_start = start_time

        max_time = max((ts for ts, _, _ in self._delivery_log), default=datetime.utcnow())

        while current_start < max_time:
            current_end = current_start + timedelta(minutes=period_minutes)

            count = sum(1 for ts, _, _ in self._delivery_log if current_start <= ts < current_end)

            periods.append(
                {
                    "start": current_start.isoformat(),
                    "end": current_end.isoformat(),
                    "deliveries": count,
                }
            )

            current_start = current_end

        return periods


class RateLimiter:
    """Per-endpoint rate limiting using token bucket."""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60) -> None:
        """Initialize rate limiter.

        Args:
            max_requests: Max requests per window.
            window_seconds: Window duration.
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, dict] = {}

    def is_allowed(self, endpoint_id: str) -> bool:
        """Check if a request is allowed for endpoint.

        Args:
            endpoint_id: ID of endpoint.

        Returns:
            True if request is allowed.
        """
        if endpoint_id not in self._buckets:
            self._buckets[endpoint_id] = {
                "tokens": self.max_requests,
                "last_refill": datetime.utcnow(),
            }

        bucket = self._buckets[endpoint_id]
        now = datetime.utcnow()
        elapsed = (now - bucket["last_refill"]).total_seconds()

        if elapsed >= self.window_seconds:
            bucket["tokens"] = self.max_requests
            bucket["last_refill"] = now
        else:
            tokens_to_add = int((elapsed / self.window_seconds) * self.max_requests)
            bucket["tokens"] = min(self.max_requests, bucket["tokens"] + tokens_to_add)
            bucket["last_refill"] = now

        if bucket["tokens"] > 0:
            bucket["tokens"] -= 1
            return True

        return False

    def get_status(self, endpoint_id: str) -> dict:
        """Get rate limit status for endpoint.

        Args:
            endpoint_id: ID of endpoint.

        Returns:
            Status dictionary.
        """
        bucket = self._buckets.get(endpoint_id)

        if not bucket:
            return {
                "tokens_available": self.max_requests,
                "max_tokens": self.max_requests,
                "allowed": True,
            }

        return {
            "tokens_available": bucket["tokens"],
            "max_tokens": self.max_requests,
            "allowed": bucket["tokens"] > 0,
        }


class DocumentationGenerator:
    """Auto-generates webhook documentation."""

    def __init__(self, registry: Any = None) -> None:
        """Initialize documentation generator.

        Args:
            registry: Webhook registry instance.
        """
        self.registry = registry

    def generate_event_catalog(self) -> dict:
        """Generate documentation for all registered event types.

        Returns:
            Event catalog dictionary.
        """
        if not self.registry:
            return {}

        event_types = self.registry.list_event_types()
        catalog = {
            "version": "1.0",
            "generated_at": datetime.utcnow().isoformat(),
            "events": {},
        }

        for event_type in event_types:
            catalog["events"][event_type] = {
                "description": f"Event type: {event_type}",
                "subscriptions": len(self.registry.get_subscriptions_for_event(event_type)),
            }

        return catalog

    def generate_endpoint_documentation(self, endpoint_id: str) -> dict:
        """Generate documentation for an endpoint.

        Args:
            endpoint_id: ID of endpoint.

        Returns:
            Endpoint documentation dictionary.
        """
        if not self.registry:
            return {}

        try:
            endpoint = self.registry.get_endpoint(endpoint_id)
            subscriptions = self.registry.list_subscriptions(endpoint_id=endpoint_id)

            return {
                "endpoint_id": endpoint.id,
                "url": endpoint.url,
                "description": endpoint.description,
                "timeout_seconds": endpoint.timeout_seconds,
                "subscriptions": len(subscriptions),
                "event_types": list(set(et for sub in subscriptions for et in sub.event_types)),
            }

        except (ValueError, TypeError):
            return {}

    def generate_subscription_documentation(self, subscription_id: str) -> dict:
        """Generate documentation for a subscription.

        Args:
            subscription_id: ID of subscription.

        Returns:
            Subscription documentation dictionary.
        """
        if not self.registry:
            return {}

        try:
            subscription = self.registry.get_subscription(subscription_id)
            endpoint = self.registry.get_endpoint(subscription.endpoint_id)

            return {
                "subscription_id": subscription.id,
                "endpoint_url": endpoint.url,
                "event_types": subscription.event_types,
                "filters": [f.to_dict() for f in subscription.filters],
                "custom_headers": subscription.custom_headers,
                "retry_policy": subscription.endpoint.retry_policy.to_dict(),
            }

        except (ValueError, TypeError):
            return {}
