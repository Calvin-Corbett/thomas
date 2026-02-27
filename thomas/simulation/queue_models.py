"""
Queueing theory models and analysis.

Implements M/M/1, M/M/c, M/D/1 and priority queue models with
analytics, Little's Law verification, and service level calculation.
"""

import heapq
from dataclasses import dataclass
from enum import Enum

from ._exceptions import ResourceError


class PriorityLevel(Enum):
    """Priority levels for queue."""

    LOW = 3
    NORMAL = 2
    HIGH = 1
    URGENT = 0


@dataclass
class Customer:
    """
    Customer in queue system.

    Attributes:
        customer_id: Unique identifier
        arrival_time: When customer arrived
        service_start_time: When service began
        service_end_time: When service completed
        service_duration: Length of service
        priority: Queue priority
    """

    customer_id: int
    arrival_time: float
    service_start_time: float | None = None
    service_end_time: float | None = None
    service_duration: float | None = None
    priority: PriorityLevel = PriorityLevel.NORMAL

    @property
    def wait_time(self) -> float:
        """Time spent waiting before service."""
        if self.service_start_time is None:
            return 0.0
        return self.service_start_time - self.arrival_time

    @property
    def total_time(self) -> float:
        """Total time in system."""
        if self.service_end_time is None:
            return 0.0
        return self.service_end_time - self.arrival_time

    def __lt__(self, other: "Customer") -> bool:
        """Compare by priority, then arrival time."""
        if self.priority.value != other.priority.value:
            return self.priority.value < other.priority.value
        return self.arrival_time < other.arrival_time


@dataclass
class Server:
    """
    Service server in queue.

    Attributes:
        server_id: Unique identifier
        busy: Whether server is currently serving
        current_customer: Customer being served
        service_time: Finish time of current service
        total_busy_time: Cumulative busy time
        customers_served: Number served by this server
    """

    server_id: int
    busy: bool = False
    current_customer: Customer | None = None
    service_time: float = 0.0
    total_busy_time: float = 0.0
    customers_served: int = 0

    def utilization(self, total_time: float) -> float:
        """Calculate server utilization."""
        if total_time <= 0:
            return 0.0
        return self.total_busy_time / total_time


@dataclass
class QueueStatistics:
    """
    Statistics for queue system.

    Attributes:
        avg_wait_time: Mean time waiting in queue
        avg_service_time: Mean service duration
        avg_total_time: Mean time in system
        avg_queue_length: Mean number of customers waiting
        avg_system_length: Mean number in system
        max_queue_length: Peak queue length
        server_utilization: Average server utilization
        throughput: Customers per unit time
        customers_served: Total served
        customers_lost: Total who left (if finite capacity)
    """

    avg_wait_time: float = 0.0
    avg_service_time: float = 0.0
    avg_total_time: float = 0.0
    avg_queue_length: float = 0.0
    avg_system_length: float = 0.0
    max_queue_length: int = 0
    server_utilization: float = 0.0
    throughput: float = 0.0
    customers_served: int = 0
    customers_lost: int = 0


class MM1Queue:
    """
    M/M/1 queue: Poisson arrivals, exponential service, single server.

    Analytical and simulation-based queueing model.
    """

    def __init__(self, arrival_rate: float, service_rate: float) -> None:
        """
        Initialize M/M/1 queue.

        Args:
            arrival_rate: Lambda (arrivals per time unit)
            service_rate: Mu (services per time unit)

        Raises:
            ResourceError: If service_rate <= arrival_rate (unstable)
        """
        if service_rate <= arrival_rate:
            raise ResourceError(f"Service rate {service_rate} must exceed arrival rate {arrival_rate}")

        self.arrival_rate = arrival_rate
        self.service_rate = service_rate
        self.rho = arrival_rate / service_rate  # Utilization

        # Simulation state
        self.queue: list[Customer] = []
        self.server = Server(server_id=0)
        self.next_customer_id = 0
        self.customers_processed: list[Customer] = []

    @property
    def l(self) -> float:
        """Average number of customers in system (steady-state)."""
        return self.rho / (1 - self.rho)

    @property
    def lq(self) -> float:
        """Average number of customers in queue (steady-state)."""
        return self.rho**2 / (1 - self.rho)

    @property
    def w(self) -> float:
        """Average time in system (steady-state)."""
        return 1 / (self.service_rate - self.arrival_rate)

    @property
    def wq(self) -> float:
        """Average wait time in queue (steady-state)."""
        return self.rho / (self.service_rate - self.arrival_rate)

    def arrive(self, current_time: float) -> Customer:
        """
        Process customer arrival.

        Args:
            current_time: Simulation time

        Returns:
            New customer
        """
        customer = Customer(
            customer_id=self.next_customer_id,
            arrival_time=current_time,
            priority=PriorityLevel.NORMAL,
        )
        self.next_customer_id += 1

        self.queue.append(customer)
        return customer

    def serve(self, current_time: float, service_duration: float) -> Customer | None:
        """
        Process next customer if server free.

        Args:
            current_time: Simulation time
            service_duration: Service duration for this customer

        Returns:
            Customer beginning service, or None if queue empty
        """
        if self.server.busy or not self.queue:
            return None

        customer = self.queue.pop(0)
        customer.service_start_time = current_time
        customer.service_duration = service_duration
        self.server.current_customer = customer
        self.server.busy = True
        self.server.service_time = current_time + service_duration

        return customer

    def complete_service(self, current_time: float) -> Customer | None:
        """
        Complete service of current customer.

        Args:
            current_time: Simulation time

        Returns:
            Customer who finished service
        """
        if not self.server.busy or self.server.current_customer is None:
            return None

        customer = self.server.current_customer
        customer.service_end_time = current_time
        self.customers_processed.append(customer)

        # Update server stats
        service_duration = current_time - customer.service_start_time
        self.server.total_busy_time += service_duration
        self.server.customers_served += 1
        self.server.busy = False
        self.server.current_customer = None

        return customer

    def statistics(self, current_time: float) -> QueueStatistics:
        """
        Compute current queue statistics.

        Args:
            current_time: Current simulation time

        Returns:
            Queue statistics object
        """
        if not self.customers_processed:
            return QueueStatistics()

        wait_times = [c.wait_time for c in self.customers_processed]
        total_times = [c.total_time for c in self.customers_processed]
        service_times = [c.service_duration for c in self.customers_processed if c.service_duration]

        stats = QueueStatistics(
            avg_wait_time=sum(wait_times) / len(wait_times) if wait_times else 0,
            avg_service_time=sum(service_times) / len(service_times) if service_times else 0,
            avg_total_time=sum(total_times) / len(total_times) if total_times else 0,
            max_queue_length=max(len(self.queue), 1),
            server_utilization=self.server.utilization(current_time),
            throughput=self.server.customers_served / current_time if current_time > 0 else 0,
            customers_served=self.server.customers_served,
        )

        # Average queue length via Little's Law: L = λ * W
        if current_time > 0:
            total_wait = sum(wait_times)
            stats.avg_queue_length = total_wait / current_time

        return stats

    def littles_law_verification(self) -> tuple[float, float, float]:
        """
        Verify Little's Law: L = λ * W.

        Returns:
            (observed_L, lambda_W, error_percent)
        """
        if not self.customers_processed:
            return 0.0, 0.0, 0.0

        # L from data: average time in system
        avg_time = sum(c.total_time for c in self.customers_processed) / len(self.customers_processed)
        observed_l = self.arrival_rate * avg_time

        # Expected L
        expected_l = self.l

        error = abs(observed_l - expected_l) / expected_l * 100 if expected_l > 0 else 0

        return observed_l, expected_l, error


class MMcQueue:
    """
    M/M/c queue: Poisson arrivals, exponential service, c servers.

    Multi-server queueing system.
    """

    def __init__(self, arrival_rate: float, service_rate: float, num_servers: int) -> None:
        """
        Initialize M/M/c queue.

        Args:
            arrival_rate: Lambda (arrivals per time unit)
            service_rate: Mu per server (services per time unit)
            num_servers: Number of parallel servers (c)

        Raises:
            ResourceError: If unstable
        """
        if num_servers * service_rate <= arrival_rate:
            raise ResourceError(f"Total capacity {num_servers * service_rate} must exceed {arrival_rate}")

        self.arrival_rate = arrival_rate
        self.service_rate = service_rate
        self.num_servers = num_servers
        self.rho = arrival_rate / (num_servers * service_rate)

        self.servers = [Server(server_id=i) for i in range(num_servers)]
        self.queue: list[Customer] = []
        self.next_customer_id = 0
        self.customers_processed: list[Customer] = []

    def arrive(self, current_time: float) -> Customer:
        """Process customer arrival."""
        customer = Customer(
            customer_id=self.next_customer_id,
            arrival_time=current_time,
            priority=PriorityLevel.NORMAL,
        )
        self.next_customer_id += 1
        self.queue.append(customer)
        return customer

    def serve(self, current_time: float, service_duration: float) -> Customer | None:
        """Assign customer to free server if available."""
        if not self.queue:
            return None

        free_server = next((s for s in self.servers if not s.busy), None)
        if free_server is None:
            return None

        customer = self.queue.pop(0)
        customer.service_start_time = current_time
        customer.service_duration = service_duration
        free_server.current_customer = customer
        free_server.busy = True
        free_server.service_time = current_time + service_duration

        return customer

    def complete_service(self, server_id: int, current_time: float) -> Customer | None:
        """Complete service on given server."""
        if server_id >= len(self.servers):
            return None

        server = self.servers[server_id]
        if not server.busy or server.current_customer is None:
            return None

        customer = server.current_customer
        customer.service_end_time = current_time
        self.customers_processed.append(customer)

        service_duration = current_time - customer.service_start_time
        server.total_busy_time += service_duration
        server.customers_served += 1
        server.busy = False
        server.current_customer = None

        return customer

    def statistics(self, current_time: float) -> QueueStatistics:
        """Compute current queue statistics."""
        if not self.customers_processed:
            return QueueStatistics()

        wait_times = [c.wait_time for c in self.customers_processed]
        total_times = [c.total_time for c in self.customers_processed]
        service_times = [c.service_duration for c in self.customers_processed if c.service_duration]

        util = sum(s.utilization(current_time) for s in self.servers) / len(self.servers)

        return QueueStatistics(
            avg_wait_time=sum(wait_times) / len(wait_times) if wait_times else 0,
            avg_service_time=sum(service_times) / len(service_times) if service_times else 0,
            avg_total_time=sum(total_times) / len(total_times) if total_times else 0,
            max_queue_length=max(len(self.queue), 0),
            server_utilization=util,
            throughput=sum(s.customers_served for s in self.servers) / current_time if current_time > 0 else 0,
            customers_served=sum(s.customers_served for s in self.servers),
        )


class MD1Queue:
    """
    M/D/1 queue: Poisson arrivals, deterministic (constant) service.

    Useful for systems with fixed service times.
    """

    def __init__(self, arrival_rate: float, service_time: float) -> None:
        """
        Initialize M/D/1 queue.

        Args:
            arrival_rate: Lambda (arrivals per time unit)
            service_time: Fixed service duration

        Raises:
            ResourceError: If arrival_rate * service_time >= 1 (unstable)
        """
        rho = arrival_rate * service_time
        if rho >= 1:
            raise ResourceError(f"Service utilization {rho} must be < 1")

        self.arrival_rate = arrival_rate
        self.service_time = service_time
        self.rho = rho

        self.queue: list[Customer] = []
        self.server = Server(server_id=0)
        self.next_customer_id = 0
        self.customers_processed: list[Customer] = []

    @property
    def wq(self) -> float:
        """Average wait time in queue (M/D/1 formula)."""
        return self.rho / (2 * (1 - self.rho) * self.arrival_rate)

    def arrive(self, current_time: float) -> Customer:
        """Process arrival."""
        customer = Customer(
            customer_id=self.next_customer_id,
            arrival_time=current_time,
            priority=PriorityLevel.NORMAL,
        )
        self.next_customer_id += 1
        self.queue.append(customer)
        return customer

    def serve(self, current_time: float) -> Customer | None:
        """Serve next customer with deterministic time."""
        if self.server.busy or not self.queue:
            return None

        customer = self.queue.pop(0)
        customer.service_start_time = current_time
        customer.service_duration = self.service_time
        self.server.current_customer = customer
        self.server.busy = True
        self.server.service_time = current_time + self.service_time

        return customer

    def complete_service(self, current_time: float) -> Customer | None:
        """Complete service."""
        if not self.server.busy or self.server.current_customer is None:
            return None

        customer = self.server.current_customer
        customer.service_end_time = current_time
        self.customers_processed.append(customer)

        self.server.total_busy_time += self.service_time
        self.server.customers_served += 1
        self.server.busy = False
        self.server.current_customer = None

        return customer

    def statistics(self, current_time: float) -> QueueStatistics:
        """Compute current queue statistics."""
        if not self.customers_processed:
            return QueueStatistics()

        wait_times = [c.wait_time for c in self.customers_processed]
        total_times = [c.total_time for c in self.customers_processed]

        return QueueStatistics(
            avg_wait_time=sum(wait_times) / len(wait_times) if wait_times else 0,
            avg_service_time=self.service_time,
            avg_total_time=sum(total_times) / len(total_times) if total_times else 0,
            max_queue_length=max(len(self.queue), 0),
            server_utilization=self.server.utilization(current_time),
            throughput=self.server.customers_served / current_time if current_time > 0 else 0,
            customers_served=self.server.customers_served,
        )


class PriorityQueue:
    """
    Priority queue: Different service priority levels.

    Preemptive or non-preemptive priority discipline.
    """

    def __init__(self, num_servers: int = 1, preemptive: bool = False) -> None:
        """
        Initialize priority queue.

        Args:
            num_servers: Number of servers
            preemptive: Whether higher priority preempts service
        """
        self.num_servers = num_servers
        self.preemptive = preemptive

        self.servers = [Server(server_id=i) for i in range(num_servers)]
        self.queue: list[Customer] = []
        self.next_customer_id = 0
        self.customers_processed: list[Customer] = []

    def arrive(self, current_time: float, priority: PriorityLevel) -> Customer:
        """Process customer arrival with priority."""
        customer = Customer(
            customer_id=self.next_customer_id,
            arrival_time=current_time,
            priority=priority,
        )
        self.next_customer_id += 1

        heapq.heappush(self.queue, customer)
        return customer

    def serve(self, current_time: float, service_duration: float) -> Customer | None:
        """Serve highest priority customer."""
        if not self.queue:
            return None

        free_server = next((s for s in self.servers if not s.busy), None)
        if free_server is None:
            return None

        customer = heapq.heappop(self.queue)
        customer.service_start_time = current_time
        customer.service_duration = service_duration
        free_server.current_customer = customer
        free_server.busy = True
        free_server.service_time = current_time + service_duration

        return customer

    def complete_service(self, server_id: int, current_time: float) -> Customer | None:
        """Complete service on server."""
        if server_id >= len(self.servers):
            return None

        server = self.servers[server_id]
        if not server.busy or server.current_customer is None:
            return None

        customer = server.current_customer
        customer.service_end_time = current_time
        self.customers_processed.append(customer)

        service_duration = current_time - customer.service_start_time
        server.total_busy_time += service_duration
        server.customers_served += 1
        server.busy = False
        server.current_customer = None

        return customer

    def statistics(self, current_time: float) -> QueueStatistics:
        """Compute current queue statistics."""
        if not self.customers_processed:
            return QueueStatistics()

        wait_times = [c.wait_time for c in self.customers_processed]
        total_times = [c.total_time for c in self.customers_processed]
        service_times = [c.service_duration for c in self.customers_processed if c.service_duration]

        util = sum(s.utilization(current_time) for s in self.servers) / len(self.servers)

        return QueueStatistics(
            avg_wait_time=sum(wait_times) / len(wait_times) if wait_times else 0,
            avg_service_time=sum(service_times) / len(service_times) if service_times else 0,
            avg_total_time=sum(total_times) / len(total_times) if total_times else 0,
            max_queue_length=max(len(self.queue), 0),
            server_utilization=util,
            throughput=sum(s.customers_served for s in self.servers) / current_time if current_time > 0 else 0,
            customers_served=sum(s.customers_served for s in self.servers),
        )

    def service_level(self, max_wait: float) -> float:
        """
        Calculate service level: % customers served within max_wait.

        Args:
            max_wait: Maximum acceptable wait time

        Returns:
            Percentage (0-100) of customers meeting SL
        """
        if not self.customers_processed:
            return 0.0

        met = sum(1 for c in self.customers_processed if c.wait_time <= max_wait)
        return (met / len(self.customers_processed)) * 100
