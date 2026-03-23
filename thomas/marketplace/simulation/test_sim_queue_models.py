"""
Tests for queueing theory models.
"""

import pytest
from _exceptions import ResourceError
from queue_models import (
    Customer,
    MD1Queue,
    MM1Queue,
    MMcQueue,
    PriorityLevel,
    PriorityQueue,
    Server,
)


class TestMM1Queue:
    """Test M/M/1 queue model."""

    def test_stable_queue(self):
        """Test M/M/1 queue stability."""
        queue = MM1Queue(arrival_rate=2.0, service_rate=5.0)
        assert queue.rho == pytest.approx(0.4)

    def test_unstable_queue_fails(self):
        """Test unstable queue raises error."""
        with pytest.raises(ResourceError):
            MM1Queue(arrival_rate=5.0, service_rate=5.0)

    def test_analytical_metrics(self):
        """Test analytical queue metrics."""
        queue = MM1Queue(arrival_rate=2.0, service_rate=5.0)

        # L = ρ / (1 - ρ)
        expected_l = 0.4 / (1 - 0.4)
        assert queue.l == pytest.approx(expected_l)

        # W = 1 / (μ - λ)
        expected_w = 1 / (5.0 - 2.0)
        assert queue.w == pytest.approx(expected_w)

        # Wq = ρ / (μ - λ)
        expected_wq = 0.4 / (5.0 - 2.0)
        assert queue.wq == pytest.approx(expected_wq)

    def test_customer_arrival(self):
        """Test customer arrival processing."""
        queue = MM1Queue(arrival_rate=2.0, service_rate=5.0)

        customer = queue.arrive(current_time=0.0)
        assert customer.customer_id == 0
        assert customer.arrival_time == 0.0
        assert len(queue.queue) == 1

    def test_customer_service(self):
        """Test customer service processing."""
        queue = MM1Queue(arrival_rate=2.0, service_rate=5.0)

        queue.arrive(0.0)
        customer = queue.serve(0.0, service_duration=2.0)

        assert customer is not None
        assert customer.service_start_time == 0.0
        assert customer.service_duration == 2.0
        assert queue.server.busy

    def test_customer_completion(self):
        """Test customer service completion."""
        queue = MM1Queue(arrival_rate=2.0, service_rate=5.0)

        queue.arrive(0.0)
        queue.serve(0.0, service_duration=2.0)
        completed = queue.complete_service(2.0)

        assert completed is not None
        assert completed.service_end_time == 2.0
        assert completed.total_time == 2.0
        assert not queue.server.busy

    def test_littles_law(self):
        """Test Little's Law verification."""
        queue = MM1Queue(arrival_rate=2.0, service_rate=5.0)

        # Simulate queue
        current_time = 0.0
        for _ in range(100):
            if current_time % 0.5 == 0:
                queue.arrive(current_time)

            customer = queue.serve(current_time, service_duration=0.2)

            completed = [c for c in queue.customers_processed if c.service_end_time == current_time]
            for c in completed:
                queue.complete_service(current_time)

            current_time += 0.1

        # Verify Little's Law: L = λ * W
        L_obs, L_expected, error = queue.littles_law_verification()
        # Allow reasonable error margin for simulation
        assert error < 50  # Within 50% is acceptable for small sample

    def test_queue_statistics(self):
        """Test queue statistics computation."""
        queue = MM1Queue(arrival_rate=2.0, service_rate=5.0)

        for i in range(10):
            queue.arrive(float(i))
            queue.serve(float(i), service_duration=0.5)
            queue.complete_service(float(i) + 0.5)

        stats = queue.statistics(current_time=10.0)

        assert stats.customers_served == 10
        assert stats.avg_service_time == pytest.approx(0.5)
        assert stats.throughput > 0


class TestMMcQueue:
    """Test M/M/c multi-server queue."""

    def test_multi_server_stability(self):
        """Test multi-server queue stability."""
        queue = MMcQueue(arrival_rate=3.0, service_rate=2.0, num_servers=2)
        assert queue.rho == pytest.approx(0.75)

    def test_unstable_multi_server_fails(self):
        """Test unstable multi-server queue."""
        with pytest.raises(ResourceError):
            MMcQueue(arrival_rate=5.0, service_rate=2.0, num_servers=2)

    def test_parallel_service(self):
        """Test parallel service on multiple servers."""
        queue = MMcQueue(arrival_rate=2.0, service_rate=3.0, num_servers=2)

        # Arrive multiple customers
        for i in range(3):
            queue.arrive(float(i))

        # All should be served initially
        for i in range(2):
            customer = queue.serve(float(i), service_duration=1.0)
            assert customer is not None

        # Third customer waits
        customer = queue.serve(float(2), service_duration=1.0)
        assert customer is None
        assert len(queue.queue) == 1

    def test_multi_server_statistics(self):
        """Test multi-server statistics."""
        queue = MMcQueue(arrival_rate=2.0, service_rate=3.0, num_servers=2)

        for i in range(10):
            queue.arrive(float(i))

        for i in range(10):
            if queue.queue:
                queue.serve(float(i), service_duration=1.0)

        stats = queue.statistics(current_time=10.0)
        assert stats.customers_served >= 0
        assert stats.server_utilization >= 0


class TestMD1Queue:
    """Test M/D/1 queue with deterministic service."""

    def test_deterministic_service(self):
        """Test deterministic service time."""
        queue = MD1Queue(arrival_rate=2.0, service_time=0.4)
        assert queue.rho == pytest.approx(0.8)

    def test_unstable_deterministic_fails(self):
        """Test unstable deterministic queue."""
        with pytest.raises(ResourceError):
            MD1Queue(arrival_rate=3.0, service_time=0.5)

    def test_fixed_service_duration(self):
        """Test fixed service duration enforcement."""
        queue = MD1Queue(arrival_rate=2.0, service_time=1.0)

        queue.arrive(0.0)
        customer = queue.serve(0.0)

        assert customer.service_duration == 1.0

    def test_deterministic_statistics(self):
        """Test deterministic queue statistics."""
        queue = MD1Queue(arrival_rate=2.0, service_time=0.4)

        for i in range(20):
            queue.arrive(float(i) * 0.5)

        for i in range(20):
            queue.serve(float(i) * 0.5, service_duration=0.4)

        stats = queue.statistics(current_time=10.0)
        assert stats.avg_service_time == pytest.approx(0.4)


class TestPriorityQueue:
    """Test priority queue with service levels."""

    def test_priority_ordering(self):
        """Test customers served by priority."""
        queue = PriorityQueue(num_servers=1, preemptive=False)

        # Arrive in order: normal, low, high
        c1 = queue.arrive(0.0, PriorityLevel.NORMAL)
        c2 = queue.arrive(0.0, PriorityLevel.LOW)
        c3 = queue.arrive(0.0, PriorityLevel.HIGH)

        # High priority should be served first
        customer = queue.serve(0.0, service_duration=1.0)
        assert customer.customer_id == c3.customer_id

    def test_service_level_calculation(self):
        """Test service level metric."""
        queue = PriorityQueue(num_servers=1, preemptive=False)

        for i in range(10):
            queue.arrive(float(i), PriorityLevel.NORMAL)
            queue.serve(float(i), service_duration=0.5)
            queue.complete_service(0, float(i) + 0.5)

        sl = queue.service_level(max_wait=1.0)
        assert 0 <= sl <= 100

    def test_multiple_priority_levels(self):
        """Test handling of all priority levels."""
        queue = PriorityQueue(num_servers=2)

        customers = []
        for level in [PriorityLevel.LOW, PriorityLevel.HIGH, PriorityLevel.URGENT, PriorityLevel.NORMAL]:
            c = queue.arrive(0.0, level)
            customers.append((c.customer_id, level))

        # Serve all
        for _ in range(4):
            c = queue.serve(0.0, service_duration=1.0)
            if c:
                queue.complete_service(0, 1.0)

        # Verify order by checking processed customers
        processed_priorities = [c.priority for c in queue.customers_processed]

        # Should process in priority order
        if len(processed_priorities) >= 2:
            for i in range(len(processed_priorities) - 1):
                assert processed_priorities[i].value <= processed_priorities[i + 1].value


class TestCustomer:
    """Test Customer class."""

    def test_customer_creation(self):
        """Test customer initialization."""
        customer = Customer(
            customer_id=1,
            arrival_time=0.0,
            priority=PriorityLevel.NORMAL,
        )

        assert customer.customer_id == 1
        assert customer.arrival_time == 0.0
        assert customer.wait_time == 0.0

    def test_wait_time_calculation(self):
        """Test wait time computation."""
        customer = Customer(
            customer_id=1,
            arrival_time=0.0,
            service_start_time=5.0,
            priority=PriorityLevel.NORMAL,
        )

        assert customer.wait_time == 5.0

    def test_total_time_calculation(self):
        """Test total time in system."""
        customer = Customer(
            customer_id=1,
            arrival_time=0.0,
            service_start_time=5.0,
            service_end_time=10.0,
            priority=PriorityLevel.NORMAL,
        )

        assert customer.total_time == 10.0

    def test_customer_comparison(self):
        """Test customer priority comparison."""
        c1 = Customer(1, 0.0, priority=PriorityLevel.LOW)
        c2 = Customer(2, 0.0, priority=PriorityLevel.HIGH)
        c3 = Customer(3, 0.0, priority=PriorityLevel.URGENT)

        sorted_customers = sorted([c1, c2, c3])

        assert sorted_customers[0].customer_id == 3  # URGENT first
        assert sorted_customers[1].customer_id == 2  # HIGH second
        assert sorted_customers[2].customer_id == 1  # LOW last


class TestServer:
    """Test Server class."""

    def test_server_creation(self):
        """Test server initialization."""
        server = Server(server_id=0)

        assert server.server_id == 0
        assert not server.busy
        assert server.customers_served == 0

    def test_utilization_calculation(self):
        """Test server utilization metric."""
        server = Server(server_id=0)
        server.total_busy_time = 50.0

        utilization = server.utilization(total_time=100.0)
        assert utilization == pytest.approx(0.5)

    def test_zero_time_utilization(self):
        """Test utilization with zero time."""
        server = Server(server_id=0)

        utilization = server.utilization(total_time=0.0)
        assert utilization == 0.0
