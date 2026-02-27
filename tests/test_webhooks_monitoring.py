"""Tests for webhook monitoring and metrics."""

from datetime import datetime

from thomas.webhooks._types import (
    Delivery,
    DeliveryAttempt,
    DeliveryStatus,
)
from thomas.webhooks.monitoring import (
    AlertingManager,
    DeliveryMetrics,
    EventVolumeMeter,
    HealthScore,
    SLATracker,
)


class TestDeliveryMetrics:
    """Test delivery metrics tracking."""

    def test_record_successful_delivery(self):
        """Test recording successful delivery."""
        metrics = DeliveryMetrics()
        delivery = Delivery(id="del_1")
        attempt = DeliveryAttempt(
            attempt_number=1,
            status=DeliveryStatus.DELIVERED,
            latency_ms=50,
        )

        metrics.record_delivery(delivery, "ep_1", attempt)

        assert metrics.get_success_rate("ep_1") == 100.0

    def test_record_failed_delivery(self):
        """Test recording failed delivery."""
        metrics = DeliveryMetrics()
        delivery = Delivery(id="del_1")
        attempt = DeliveryAttempt(
            attempt_number=1,
            status=DeliveryStatus.FAILED,
            latency_ms=100,
        )

        metrics.record_delivery(delivery, "ep_1", attempt)

        assert metrics.get_failure_rate("ep_1") == 100.0

    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        metrics = DeliveryMetrics()
        delivery1 = Delivery(id="del_1")
        delivery2 = Delivery(id="del_2")

        metrics.record_delivery(
            delivery1,
            "ep_1",
            DeliveryAttempt(status=DeliveryStatus.DELIVERED, latency_ms=50),
        )
        metrics.record_delivery(
            delivery2,
            "ep_1",
            DeliveryAttempt(status=DeliveryStatus.FAILED, latency_ms=100),
        )

        assert metrics.get_success_rate("ep_1") == 50.0

    def test_latency_percentile(self):
        """Test latency percentile calculation."""
        metrics = DeliveryMetrics()

        for i in range(100):
            delivery = Delivery(id=f"del_{i}")
            attempt = DeliveryAttempt(
                status=DeliveryStatus.DELIVERED,
                latency_ms=i * 10,
            )
            metrics.record_delivery(delivery, "ep_1", attempt)

        p95 = metrics.get_latency_percentile(95, "ep_1")
        assert p95 is not None
        assert 900 <= p95 <= 1000

    def test_get_endpoint_stats(self):
        """Test getting endpoint statistics."""
        metrics = DeliveryMetrics()
        delivery = Delivery(id="del_1")
        attempt = DeliveryAttempt(
            status=DeliveryStatus.DELIVERED,
            latency_ms=75,
        )

        metrics.record_delivery(delivery, "ep_1", attempt)

        stats = metrics.get_endpoint_stats("ep_1")

        assert stats["endpoint_id"] == "ep_1"
        assert stats["total_attempts"] == 1
        assert stats["successes"] == 1
        assert stats["success_rate"] == 100.0

    def test_get_all_stats(self):
        """Test getting stats for all endpoints."""
        metrics = DeliveryMetrics()

        for i in range(2):
            delivery = Delivery(id=f"del_{i}")
            attempt = DeliveryAttempt(status=DeliveryStatus.DELIVERED)
            metrics.record_delivery(delivery, f"ep_{i}", attempt)

        stats = metrics.get_all_stats()
        assert len(stats) == 2


class TestHealthScore:
    """Test health score calculation."""

    def test_calculate_health_score(self):
        """Test health score calculation."""
        metrics = DeliveryMetrics()
        health = HealthScore()
        health.register_metrics("ep_1", metrics)

        delivery = Delivery(id="del_1")
        attempt = DeliveryAttempt(
            status=DeliveryStatus.DELIVERED,
            latency_ms=50,
        )
        metrics.record_delivery(delivery, "ep_1", attempt)

        score = health.calculate_score("ep_1")
        assert 0 <= score <= 100

    def test_healthy_status(self):
        """Test healthy status determination."""
        metrics = DeliveryMetrics()
        health = HealthScore()
        health.register_metrics("ep_1", metrics)

        for _ in range(10):
            delivery = Delivery(id=f"del_{_}")
            attempt = DeliveryAttempt(
                status=DeliveryStatus.DELIVERED,
                latency_ms=50,
            )
            metrics.record_delivery(delivery, "ep_1", attempt)

        status = health.get_health_status("ep_1")
        assert status in ("healthy", "degraded", "critical")


class TestAlertingManager:
    """Test alerting system."""

    def test_register_handler(self):
        """Test registering alert handler."""
        manager = AlertingManager()
        handler_called = []

        def test_handler(alert):
            handler_called.append(alert)

        manager.register_handler("endpoint_degradation", test_handler)

        manager.check_endpoint_degradation("ep_1", health_score=50.0)

        assert len(handler_called) == 1

    def test_check_endpoint_degradation(self):
        """Test endpoint degradation check."""
        manager = AlertingManager()

        result = manager.check_endpoint_degradation("ep_1", health_score=50.0)

        assert result
        alerts = manager.get_alerts("endpoint_degradation")
        assert len(alerts) == 1

    def test_check_high_error_rate(self):
        """Test high error rate check."""
        manager = AlertingManager()

        result = manager.check_high_error_rate("ep_1", error_rate=10.0)

        assert result
        alerts = manager.get_alerts("high_error_rate")
        assert len(alerts) == 1

    def test_check_high_latency(self):
        """Test high latency check."""
        manager = AlertingManager()

        result = manager.check_high_latency("ep_1", latency_ms=6000)

        assert result
        alerts = manager.get_alerts("high_latency")
        assert len(alerts) == 1

    def test_clear_alerts(self):
        """Test clearing alerts."""
        manager = AlertingManager()

        manager.check_endpoint_degradation("ep_1", health_score=50.0)
        manager.clear_alerts()

        assert len(manager.get_alerts()) == 0

    def test_get_alerts_by_type(self):
        """Test filtering alerts by type."""
        manager = AlertingManager()

        manager.check_endpoint_degradation("ep_1", health_score=50.0)
        manager.check_high_error_rate("ep_2", error_rate=10.0)

        degradation_alerts = manager.get_alerts("endpoint_degradation")
        assert len(degradation_alerts) == 1


class TestEventVolumeMeter:
    """Test event volume tracking."""

    def test_record_event(self):
        """Test recording event volume."""
        meter = EventVolumeMeter()

        meter.record_event("order.created")
        meter.record_event("order.created")
        meter.record_event("payment.completed")

        assert meter.get_volume() == 3

    def test_get_volume_by_type(self):
        """Test getting volume by event type."""
        meter = EventVolumeMeter()

        meter.record_event("order.created")
        meter.record_event("order.created")
        meter.record_event("payment.completed")

        volumes = meter.get_volume_by_type()

        assert volumes["order.created"] == 2
        assert volumes["payment.completed"] == 1

    def test_get_volume_filter_by_type(self):
        """Test filtering volume by event type."""
        meter = EventVolumeMeter()

        meter.record_event("order.created")
        meter.record_event("order.created")
        meter.record_event("payment.completed")

        volume = meter.get_volume("order.created")

        assert volume == 2


class TestSLATracker:
    """Test SLA compliance tracking."""

    def test_record_compliant_delivery(self):
        """Test recording SLA-compliant delivery."""
        tracker = SLATracker(sla_seconds=60)
        delivery = Delivery(id="del_1")

        from datetime import timedelta

        now = datetime.utcnow()
        delivery.created_at = now - timedelta(seconds=30)
        delivery.attempts.append(
            DeliveryAttempt(
                attempt_number=1,
                timestamp=now,
                status=DeliveryStatus.DELIVERED,
            )
        )

        compliant = tracker.record_delivery(delivery)

        assert compliant

    def test_record_non_compliant_delivery(self):
        """Test recording SLA non-compliant delivery."""
        tracker = SLATracker(sla_seconds=30)
        delivery = Delivery(id="del_1")

        from datetime import timedelta

        now = datetime.utcnow()
        delivery.created_at = now - timedelta(seconds=60)
        delivery.attempts.append(
            DeliveryAttempt(
                attempt_number=1,
                timestamp=now,
                status=DeliveryStatus.DELIVERED,
            )
        )

        compliant = tracker.record_delivery(delivery)

        assert not compliant

    def test_get_sla_compliance_rate(self):
        """Test SLA compliance rate calculation."""
        tracker = SLATracker(sla_seconds=60)

        from datetime import timedelta

        now = datetime.utcnow()

        for i in range(10):
            delivery = Delivery(id=f"del_{i}")
            delivery.created_at = now - timedelta(seconds=30)
            delivery.attempts.append(
                DeliveryAttempt(
                    attempt_number=1,
                    timestamp=now,
                    status=DeliveryStatus.DELIVERED,
                )
            )
            tracker.record_delivery(delivery)

        rate = tracker.get_sla_compliance_rate()

        assert rate == 100.0

    def test_get_sla_stats(self):
        """Test getting SLA statistics."""
        tracker = SLATracker(sla_seconds=60)
        delivery = Delivery(id="del_1")

        from datetime import timedelta

        now = datetime.utcnow()
        delivery.created_at = now - timedelta(seconds=30)
        delivery.attempts.append(
            DeliveryAttempt(
                attempt_number=1,
                timestamp=now,
                status=DeliveryStatus.DELIVERED,
            )
        )

        tracker.record_delivery(delivery)

        stats = tracker.get_stats()

        assert stats["sla_seconds"] == 60
        assert stats["compliant"] == 1
        assert stats["compliance_rate"] == 100.0
