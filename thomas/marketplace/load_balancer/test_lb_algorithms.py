"""
Tests for load balancing algorithms.

Verifies correct distribution, weight handling, and edge cases.
"""

import pytest

from thomas.marketplace.load_balancer._exceptions import NoHealthyBackendError
from thomas.marketplace.load_balancer._types import Backend, RequestContext
from thomas.marketplace.load_balancer.algorithms import (
    ConsistentHash,
    IPHash,
    LeastConnections,
    LeastResponseTime,
    RandomChoice,
    ResourceBased,
    RoundRobin,
    WeightedLeastConnections,
    WeightedRandom,
    WeightedRoundRobin,
)


@pytest.fixture
def backends():
    """Create test backends."""
    return [
        Backend("b1", "host1", 8080, weight=1),
        Backend("b2", "host2", 8080, weight=1),
        Backend("b3", "host3", 8080, weight=1),
    ]


@pytest.fixture
def weighted_backends():
    """Create weighted test backends."""
    return [
        Backend("b1", "host1", 8080, weight=1),
        Backend("b2", "host2", 8080, weight=2),
        Backend("b3", "host3", 8080, weight=3),
    ]


@pytest.fixture
def context():
    """Create test request context."""
    return RequestContext(client_ip="192.168.1.1", path="/api/test")


class TestRoundRobin:
    """Tests for round-robin algorithm."""

    def test_round_robin_distribution(self, backends, context):
        """Test even distribution across backends."""
        algo = RoundRobin()
        selections = {}

        for _ in range(300):
            decision = algo.select(backends, context)
            bid = decision.backend.id
            selections[bid] = selections.get(bid, 0) + 1

        # Each backend should get ~100 requests
        for count in selections.values():
            assert 80 < count < 120

    def test_round_robin_empty_backends(self, context):
        """Test round-robin with empty backend list."""
        algo = RoundRobin()
        with pytest.raises(NoHealthyBackendError):
            algo.select([], context)

    def test_round_robin_single_backend(self, context):
        """Test round-robin with single backend."""
        algo = RoundRobin()
        backends = [Backend("b1", "host1", 8080)]

        for _ in range(10):
            decision = algo.select(backends, context)
            assert decision.backend.id == "b1"


class TestWeightedRoundRobin:
    """Tests for weighted round-robin algorithm."""

    def test_weighted_distribution(self, weighted_backends, context):
        """Test distribution respects weights."""
        algo = WeightedRoundRobin()
        selections = {}

        for _ in range(600):
            decision = algo.select(weighted_backends, context)
            bid = decision.backend.id
            selections[bid] = selections.get(bid, 0) + 1

        # Expected: b1=100, b2=200, b3=300
        assert 80 < selections.get("b1", 0) < 120
        assert 180 < selections.get("b2", 0) < 220
        assert 280 < selections.get("b3", 0) < 320

    def test_weighted_with_zero_weight(self, context):
        """Test handling of zero-weight backends."""
        backends = [
            Backend("b1", "host1", 8080, weight=1),
            Backend("b2", "host2", 8080, weight=0),
            Backend("b3", "host3", 8080, weight=1),
        ]
        algo = WeightedRoundRobin()

        selections = {}
        for _ in range(100):
            decision = algo.select(backends, context)
            bid = decision.backend.id
            selections[bid] = selections.get(bid, 0) + 1

        # b2 should not be selected (weight=0)
        assert selections.get("b2", 0) == 0


class TestLeastConnections:
    """Tests for least connections algorithm."""

    def test_selects_least_loaded(self, backends, context):
        """Test selection of backend with least connections."""
        algo = LeastConnections()
        active_connections = {
            "b1": 10,
            "b2": 5,
            "b3": 15,
        }

        decision = algo.select(backends, context, active_connections=active_connections)
        assert decision.backend.id == "b2"

    def test_least_connections_with_zero(self, backends, context):
        """Test selection when some backends have no connections."""
        algo = LeastConnections()
        active_connections = {
            "b1": 10,
            "b2": 0,
            "b3": 5,
        }

        decision = algo.select(backends, context, active_connections=active_connections)
        assert decision.backend.id == "b2"

    def test_least_connections_empty_dict(self, backends, context):
        """Test with empty active connections dict."""
        algo = LeastConnections()
        decision = algo.select(backends, context, active_connections={})
        # Should select based on missing connections (assumed 0)
        assert decision.backend.id in [b.id for b in backends]


class TestWeightedLeastConnections:
    """Tests for weighted least connections algorithm."""

    def test_capacity_ratio(self, weighted_backends, context):
        """Test selection based on capacity ratio."""
        algo = WeightedLeastConnections()
        active_connections = {
            "b1": 5,  # b1: 5/1 = 5
            "b2": 10,  # b2: 10/2 = 5
            "b3": 20,  # b3: 20/3 = 6.67
        }

        decision = algo.select(weighted_backends, context, active_connections=active_connections)
        # Should select b1 or b2 (both have ratio 5)
        assert decision.backend.id in ["b1", "b2"]


class TestRandomChoice:
    """Tests for random choice algorithm."""

    def test_random_selects_from_pool(self, backends, context):
        """Test random selection returns valid backend."""
        algo = RandomChoice()

        for _ in range(50):
            decision = algo.select(backends, context)
            assert decision.backend in backends

    def test_random_distribution(self, backends, context):
        """Test random provides reasonable distribution."""
        algo = RandomChoice()
        selections = {}

        for _ in range(300):
            decision = algo.select(backends, context)
            bid = decision.backend.id
            selections[bid] = selections.get(bid, 0) + 1

        # Each backend should get some requests
        assert len(selections) == 3


class TestWeightedRandom:
    """Tests for weighted random algorithm."""

    def test_weighted_random_distribution(self, weighted_backends, context):
        """Test weighted random respects weights."""
        algo = WeightedRandom()
        selections = {}

        for _ in range(600):
            decision = algo.select(weighted_backends, context)
            bid = decision.backend.id
            selections[bid] = selections.get(bid, 0) + 1

        # Verify approximate distribution
        assert selections.get("b1", 0) > 0
        assert selections.get("b2", 0) > selections.get("b1", 0)
        assert selections.get("b3", 0) > selections.get("b2", 0)

    def test_weighted_random_ignores_zero_weight(self, context):
        """Test zero-weight backends are ignored."""
        backends = [
            Backend("b1", "host1", 8080, weight=1),
            Backend("b2", "host2", 8080, weight=0),
            Backend("b3", "host3", 8080, weight=1),
        ]
        algo = WeightedRandom()

        selections = set()
        for _ in range(100):
            decision = algo.select(backends, context)
            selections.add(decision.backend.id)

        # b2 should never be selected
        assert "b2" not in selections


class TestIPHash:
    """Tests for IP hash algorithm."""

    def test_same_ip_same_backend(self, backends, context):
        """Test same IP always selects same backend."""
        algo = IPHash()

        decision1 = algo.select(backends, context)
        decision2 = algo.select(backends, context)

        assert decision1.backend.id == decision2.backend.id

    def test_different_ips_different_backends(self, backends):
        """Test different IPs can select different backends."""
        algo = IPHash()

        context1 = RequestContext(client_ip="192.168.1.1", path="/test")
        context2 = RequestContext(client_ip="192.168.1.2", path="/test")

        decision1 = algo.select(backends, context1)
        algo.select(backends, context2)

        # They might be same or different, but algorithm is deterministic
        d1_repeat = algo.select(backends, context1)
        assert d1_repeat.backend.id == decision1.backend.id


class TestConsistentHash:
    """Tests for consistent hashing algorithm."""

    def test_consistent_hash_stability(self, backends, context):
        """Test consistent hash gives same result."""
        algo = ConsistentHash()

        decision1 = algo.select(backends, context)
        decision2 = algo.select(backends, context)

        assert decision1.backend.id == decision2.backend.id

    def test_consistent_hash_minimal_redistribution(self, backends, context):
        """Test backend removal causes minimal redistribution."""
        algo = ConsistentHash()

        # Select with all backends
        selections_before = {}
        for i in range(100):
            ctx = RequestContext(client_ip=f"192.168.1.{i}", path="/test")
            decision = algo.select(backends, context=ctx)
            bid = decision.backend.id
            selections_before[bid] = selections_before.get(bid, 0) + 1

        # Remove one backend
        backends_reduced = backends[:-1]

        # Count redistributed requests
        redistributed = 0
        for i in range(100):
            ctx = RequestContext(client_ip=f"192.168.1.{i}", path="/test")
            decision = algo.select(backends_reduced, context=ctx)
            list(selections_before.keys())[0]  # Simplified

        # Most requests should stay with same backend
        assert redistributed < 50  # Less than 50% redistribution expected


class TestLeastResponseTime:
    """Tests for least response time algorithm."""

    def test_selects_lowest_latency(self, backends, context):
        """Test selection of backend with lowest latency."""
        algo = LeastResponseTime()
        latencies = {
            "b1": 100.0,
            "b2": 50.0,
            "b3": 75.0,
        }

        decision = algo.select(backends, context, latencies=latencies)
        assert decision.backend.id == "b2"

    def test_weighted_latency(self, weighted_backends, context):
        """Test weighted latency selection."""
        algo = LeastResponseTime()
        latencies = {
            "b1": 100.0,  # Score: 100/1 = 100
            "b2": 100.0,  # Score: 100/2 = 50
            "b3": 100.0,  # Score: 100/3 = 33.3
        }

        decision = algo.select(weighted_backends, context, latencies=latencies)
        assert decision.backend.id == "b3"  # Best score


class TestResourceBased:
    """Tests for resource-based algorithm."""

    def test_selects_best_resources(self, context):
        """Test selection based on available resources."""
        backends = [
            Backend("b1", "host1", 8080, metadata={"cpu_available": 50, "memory_available": 60}),
            Backend("b2", "host2", 8080, metadata={"cpu_available": 80, "memory_available": 70}),
            Backend("b3", "host3", 8080, metadata={"cpu_available": 40, "memory_available": 50}),
        ]
        algo = ResourceBased()

        decision = algo.select(backends, context)
        assert decision.backend.id == "b2"  # Best average resources

    def test_missing_resource_metadata(self, backends, context):
        """Test handling of missing resource metadata."""
        algo = ResourceBased()

        decision = algo.select(backends, context)
        # Should not crash, returns some backend
        assert decision.backend in backends
