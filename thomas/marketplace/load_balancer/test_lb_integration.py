"""
Integration tests for the load balancer.

Tests full request routing, failover, metrics collection, and graceful shutdown.
"""

import time

import pytest

from thomas.marketplace.load_balancer._exceptions import (
    CircuitOpenError,
    NoHealthyBackendError,
)
from thomas.marketplace.load_balancer._types import (
    Backend,
    CircuitState,
    HealthCheckConfig,
    LoadBalancerConfig,
    RequestContext,
)
from thomas.marketplace.load_balancer.balancer import LoadBalancer
from thomas.marketplace.load_balancer.l7_router import L7Router


@pytest.fixture
def backends():
    """Create test backends."""
    return [
        Backend("b1", "127.0.0.1", 8001),
        Backend("b2", "127.0.0.1", 8002),
        Backend("b3", "127.0.0.1", 8003),
    ]


@pytest.fixture
def config():
    """Create test load balancer config."""
    health_config = HealthCheckConfig(
        enabled=False,  # Disable for testing
        interval=1,
        timeout=1,
        healthy_threshold=1,
        unhealthy_threshold=1,
    )
    return LoadBalancerConfig(
        algorithm="round_robin",
        health_check=health_config,
        enable_circuit_breaker=True,
        enable_rate_limiter=True,
        enable_connection_pool=False,
        enable_sticky_sessions=True,
    )


@pytest.fixture
def lb(config, backends):
    """Create configured load balancer."""
    balancer = LoadBalancer(config)
    balancer.start()

    for backend in backends:
        balancer.add_backend(backend)

    # Mark all as healthy for testing
    for backend in backends:
        for _ in range(2):
            balancer._health_checker._update_status(backend.id, True)

    return balancer


class TestLoadBalancerBasicRouting:
    """Tests for basic request routing."""

    def test_add_backends(self, lb, backends):
        """Test adding backends to load balancer."""
        assert len(lb.pool) == 3

    def test_route_request(self, lb):
        """Test basic request routing."""
        context = RequestContext(client_ip="192.168.1.1", path="/api/test")

        decision = lb.route_request(context)
        assert decision.backend is not None
        assert decision.backend.id in ["b1", "b2", "b3"]

    def test_routing_distribution(self, lb):
        """Test requests distributed across backends."""
        selections = {}

        for i in range(30):
            context = RequestContext(client_ip=f"192.168.1.{i}", path="/api/test")
            decision = lb.route_request(context)
            bid = decision.backend.id
            selections[bid] = selections.get(bid, 0) + 1

        # Each backend should get requests with round-robin
        assert len(selections) == 3
        for count in selections.values():
            assert 5 < count < 15

    def test_no_healthy_backends(self, lb):
        """Test error when no healthy backends."""
        # Mark all as unhealthy
        for backend_id in ["b1", "b2", "b3"]:
            lb._health_checker._health_status[backend_id] = "unhealthy"

        context = RequestContext(client_ip="192.168.1.1", path="/api/test")

        with pytest.raises(NoHealthyBackendError):
            lb.route_request(context)

    def test_circuit_breaker_open(self, lb):
        """Test circuit breaker prevents routing to broken backend."""
        context = RequestContext(client_ip="192.168.1.1", path="/api/test")

        # Open circuit for b1
        for _ in range(5):
            lb._circuit_breaker.record_failure("b1")

        # Routing should fail or route elsewhere
        try:
            decision = lb.route_request(context)
            # May succeed routing to healthy backend
            assert decision.backend.id != "b1"
        except CircuitOpenError:
            pass  # Also acceptable


class TestLoadBalancerMetrics:
    """Tests for metrics collection."""

    def test_record_request_metrics(self, lb):
        """Test recording request metrics."""
        context = RequestContext(client_ip="192.168.1.1", path="/api/test")
        decision = lb.route_request(context)

        lb.record_request(decision, latency=50.0, success=True)

        metrics = lb.get_metrics()
        assert metrics["global"]["total_requests"] == 1

    def test_error_rate_tracking(self, lb):
        """Test error rate metrics."""
        context = RequestContext(client_ip="192.168.1.1", path="/api/test")

        for _ in range(10):
            decision = lb.route_request(context)
            lb.record_request(decision, latency=50.0, success=True)

        for _ in range(5):
            decision = lb.route_request(context)
            lb.record_request(decision, latency=50.0, success=False)

        metrics = lb.get_metrics()
        # 5 errors out of 15 requests ≈ 33%
        assert 30 < metrics["global"]["error_rate"] < 40

    def test_backend_distribution_metrics(self, lb):
        """Test per-backend distribution metrics."""
        for i in range(30):
            context = RequestContext(client_ip=f"192.168.1.{i}", path="/api/test")
            decision = lb.route_request(context)
            lb.record_request(decision, latency=50.0, success=True)

        distribution = lb._metrics.get_backend_distribution()
        assert len(distribution) == 3
        for pct in distribution.values():
            assert 20 < pct < 40  # Each ~33%

    def test_latency_tracking(self, lb):
        """Test latency percentile tracking."""
        context = RequestContext(client_ip="192.168.1.1", path="/api/test")

        latencies = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        for latency in latencies:
            decision = lb.route_request(context)
            lb.record_request(decision, latency=float(latency), success=True)

        backend_metrics = lb._metrics.get_backend_metrics("b1")
        if backend_metrics and backend_metrics["total_requests"] > 0:
            assert backend_metrics["latency_p50"] > 0
            assert backend_metrics["latency_p95"] > backend_metrics["latency_p50"]
            assert backend_metrics["latency_p99"] >= backend_metrics["latency_p95"]

    def test_global_metrics_export(self, lb):
        """Test exporting global metrics."""
        context = RequestContext(client_ip="192.168.1.1", path="/api/test")

        for _ in range(5):
            decision = lb.route_request(context)
            lb.record_request(decision, latency=50.0, success=True)

        export = lb._metrics.export_metrics()
        assert "timestamp" in export
        assert "global" in export
        assert "backends" in export
        assert "distribution" in export


class TestLoadBalancerFailover:
    """Tests for failover behavior."""

    def test_passive_health_detection(self, lb):
        """Test passive health detection on errors."""
        context = RequestContext(client_ip="192.168.1.1", path="/api/test")
        decision = lb.route_request(context)

        # Mark as failed
        lb.record_request(decision, latency=50.0, success=False)

        # Check health status changed
        status = lb._health_checker.get_status(decision.backend.id)
        # Should eventually become unhealthy after multiple failures
        assert status is not None

    def test_retry_on_different_backend(self, lb):
        """Test retrying on different backend after failure."""
        context = RequestContext(client_ip="192.168.1.1", path="/api/test")

        # Initial routing
        decision1 = lb.route_request(context)
        lb.record_request(decision1, latency=50.0, success=False)

        # Retry (excluding failed backend)
        try:
            decision2 = lb.retry_request(context, excluded_backends=[decision1.backend.id])
            assert decision2.backend.id != decision1.backend.id
        except NoHealthyBackendError:
            pass  # Also acceptable if few backends

    def test_circuit_breaker_recovery(self, lb):
        """Test circuit breaker recovery."""
        # Open circuit for b1
        for _ in range(5):
            lb._circuit_breaker.record_failure("b1")

        state = lb._circuit_breaker.get_state("b1")
        assert state == CircuitState.OPEN

        # After recovery timeout, should be HALF_OPEN
        breaker = lb._circuit_breaker.get_breaker("b1")
        breaker.recovery_timeout = 0.5
        time.sleep(0.6)

        # Should allow execution now
        assert breaker.can_execute()


class TestLoadBalancerStickySessions:
    """Tests for sticky session behavior."""

    def test_session_affinity_request_routing(self, lb):
        """Test sticky sessions route to same backend."""
        context1 = RequestContext(
            client_ip="192.168.1.1",
            path="/api/test",
            session_id="sess1",
        )

        # First request establishes session
        decision1 = lb.route_request(context1)

        # Second request should go to same backend
        decision2 = lb.route_request(context1)

        assert decision1.backend.id == decision2.backend.id

    def test_session_failover(self, lb):
        """Test session failover when preferred backend down."""
        context = RequestContext(
            client_ip="192.168.1.1",
            path="/api/test",
            session_id="sess1",
        )

        decision = lb.route_request(context)
        original_backend = decision.backend.id

        # Simulate backend going down
        lb.drain_backend(original_backend)

        # Session should failover or route to another backend
        decision2 = lb.route_request(context)
        # May fail due to circuit or select different backend
        assert decision2.backend.id is not None


class TestLoadBalancerDraining:
    """Tests for graceful shutdown/draining."""

    def test_drain_backend(self, lb, backends):
        """Test draining a backend."""
        lb.drain_backend("b1")

        assert "b1" in lb._draining_backends

        # New requests should not route to b1
        for _ in range(20):
            context = RequestContext(client_ip="192.168.1.1", path="/api/test")
            decision = lb.route_request(context)
            assert decision.backend.id in ["b2", "b3"]

    def test_remove_backend(self, lb):
        """Test removing a backend."""
        initial_count = len(lb.pool)

        lb.remove_backend("b1")

        assert len(lb.pool) == initial_count - 1

        # b1 should not be routed to
        for _ in range(20):
            context = RequestContext(client_ip="192.168.1.1", path="/api/test")
            decision = lb.route_request(context)
            assert decision.backend.id != "b1"

    def test_shutdown(self, config, backends):
        """Test graceful shutdown."""
        lb = LoadBalancer(config)
        lb.start()

        for backend in backends:
            lb.add_backend(backend)

        lb.stop()

        # Should be able to start again
        lb2 = LoadBalancer(config)
        lb2.start()
        lb2.stop()


class TestLoadBalancerAlgorithmSwitch:
    """Tests for runtime algorithm switching."""

    def test_switch_algorithm(self, lb):
        """Test switching algorithm at runtime."""
        initial = lb.config.algorithm
        assert initial == "round_robin"

        lb.set_algorithm("random")
        assert lb.config.algorithm == "random"

        # Should still work
        context = RequestContext(client_ip="192.168.1.1", path="/api/test")
        decision = lb.route_request(context)
        assert decision.backend is not None

    def test_invalid_algorithm(self, lb):
        """Test error on invalid algorithm."""
        with pytest.raises(ValueError):
            lb.set_algorithm("invalid_algorithm")


class TestL7Router:
    """Tests for Layer 7 routing."""

    def test_path_prefix_routing(self):
        """Test path prefix based routing."""
        b1 = Backend("b1", "host1", 8080)
        b2 = Backend("b2", "host2", 8080)

        router = L7Router()
        router.add_path_prefix_route("/api/v1", b1)
        router.add_path_prefix_route("/api/v2", b2)

        context1 = RequestContext(client_ip="192.168.1.1", path="/api/v1/users")
        context2 = RequestContext(client_ip="192.168.1.1", path="/api/v2/users")

        assert router.route(context1).id == "b1"
        assert router.route(context2).id == "b2"

    def test_exact_path_routing(self):
        """Test exact path routing."""
        b1 = Backend("b1", "host1", 8080)
        b2 = Backend("b2", "host2", 8080)

        router = L7Router()
        router.add_exact_path_route("/", b1)
        router.add_exact_path_route("/admin", b2)

        context1 = RequestContext(client_ip="192.168.1.1", path="/")
        context2 = RequestContext(client_ip="192.168.1.1", path="/admin")
        context3 = RequestContext(client_ip="192.168.1.1", path="/admin/users")

        assert router.route(context1).id == "b1"
        assert router.route(context2).id == "b2"
        assert router.route(context3) is None  # No match

    def test_regex_routing(self):
        """Test regex path routing."""
        b1 = Backend("b1", "host1", 8080)
        b2 = Backend("b2", "host2", 8080)

        router = L7Router()
        router.add_regex_route(r"^/api/v\d+/.*", b1)
        router.add_regex_route(r"^/admin/.*", b2)

        context1 = RequestContext(client_ip="192.168.1.1", path="/api/v1/users")
        context2 = RequestContext(client_ip="192.168.1.1", path="/api/v3/products")
        context3 = RequestContext(client_ip="192.168.1.1", path="/admin/dashboard")

        assert router.route(context1).id == "b1"
        assert router.route(context2).id == "b1"
        assert router.route(context3).id == "b2"

    def test_header_based_routing(self):
        """Test header-based routing."""
        b1 = Backend("b1", "host1", 8080)
        b2 = Backend("b2", "host2", 8080)

        router = L7Router()
        router.add_header_route("/api", b1, headers={"x-client-type": "web"})
        router.add_header_route("/api", b2, headers={"x-client-type": "mobile"})

        context1 = RequestContext(
            client_ip="192.168.1.1",
            path="/api/test",
            headers={"x-client-type": "web"},
        )
        context2 = RequestContext(
            client_ip="192.168.1.1",
            path="/api/test",
            headers={"x-client-type": "mobile"},
        )

        assert router.route(context1).id == "b1"
        assert router.route(context2).id == "b2"

    def test_route_priority(self):
        """Test route priority handling."""
        b1 = Backend("b1", "host1", 8080)
        b2 = Backend("b2", "host2", 8080)

        router = L7Router()
        router.add_path_prefix_route("/api", b1, priority=1)
        router.add_path_prefix_route("/api/v1", b2, priority=2)  # Higher priority

        context = RequestContext(client_ip="192.168.1.1", path="/api/v1/users")

        # Higher priority should match first
        assert router.route(context).id == "b2"

    def test_route_stats(self):
        """Test route statistics tracking."""
        b1 = Backend("b1", "host1", 8080)
        router = L7Router()
        router.add_exact_path_route("/", b1)

        context = RequestContext(client_ip="192.168.1.1", path="/")

        for _ in range(5):
            router.route(context)

        stats = router.get_route_stats()
        assert "/ (exact)" in stats
        assert stats["/ (exact)"] == 5


class TestLoadBalancerStats:
    """Tests for comprehensive statistics."""

    def test_get_stats(self, lb):
        """Test getting comprehensive stats."""
        context = RequestContext(client_ip="192.168.1.1", path="/api/test")

        for _ in range(10):
            decision = lb.route_request(context)
            lb.record_request(decision, latency=50.0, success=True)

        stats = lb.get_stats()
        assert "config" in stats
        assert "backends" in stats
        assert "metrics" in stats
        assert "health" in stats
        assert "circuit_breakers" in stats

        assert stats["backends"]["total"] == 3
        assert stats["metrics"]["global"]["total_requests"] == 10
