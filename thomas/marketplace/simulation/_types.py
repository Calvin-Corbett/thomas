"""
Core type definitions for simulation framework.

Defines fundamental data structures used across all simulation engines.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DistributionType(str, Enum):
    """Types of probability distributions."""

    UNIFORM = "uniform"
    NORMAL = "normal"
    EXPONENTIAL = "exponential"
    POISSON = "poisson"
    TRIANGULAR = "triangular"
    LOGNORMAL = "lognormal"
    WEIBULL = "weibull"
    BETA = "beta"
    GAMMA = "gamma"
    EMPIRICAL = "empirical"


class EventType(str, Enum):
    """Standard event types."""

    ARRIVAL = "arrival"
    DEPARTURE = "departure"
    SERVICE_START = "service_start"
    SERVICE_END = "service_end"
    AGENT_STEP = "agent_step"
    AGENT_BIRTH = "agent_birth"
    AGENT_DEATH = "agent_death"
    RESOURCE_DEPLETION = "resource_depletion"
    RESOURCE_REGENERATION = "resource_regeneration"
    CUSTOM = "custom"


@dataclass(frozen=True)
class Event:
    """
    Immutable event with timestamp, type, priority, and data.

    Attributes:
        time: Simulation timestamp when event occurs
        event_type: Type of event (arrival, departure, etc.)
        data: Event-specific payload data
        priority: Lower values processed first at same timestamp
        event_id: Unique identifier for cancellation
    """

    time: float
    event_type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    event_id: int | None = None

    def __lt__(self, other: "Event") -> bool:
        """Compare events by (time, priority) for heap ordering."""
        if self.time != other.time:
            return self.time < other.time
        return self.priority < other.priority

    def __eq__(self, other: object) -> bool:
        """Check event equality including ID."""
        if not isinstance(other, Event):
            return NotImplemented
        return self.event_id == other.event_id and self.time == other.time

    def __hash__(self) -> int:
        """Hash event by ID and time."""
        return hash((self.event_id, self.time))


@dataclass
class Distribution:
    """
    Parameterized probability distribution for sampling.

    Attributes:
        dist_type: Type of distribution
        params: Distribution-specific parameters (mean, std, min, max, etc.)
    """

    dist_type: DistributionType
    params: dict[str, float] = field(default_factory=dict)

    def validate(self) -> bool:
        """Validate parameters for this distribution type."""
        if self.dist_type == DistributionType.UNIFORM:
            return "min" in self.params and "max" in self.params
        elif self.dist_type == DistributionType.NORMAL:
            return "mean" in self.params and "std" in self.params
        elif self.dist_type == DistributionType.EXPONENTIAL:
            return "rate" in self.params
        elif self.dist_type == DistributionType.POISSON:
            return "lambda" in self.params
        elif self.dist_type == DistributionType.TRIANGULAR:
            return "min" in self.params and "mode" in self.params and "max" in self.params
        elif self.dist_type == DistributionType.LOGNORMAL:
            return "mean" in self.params and "std" in self.params
        elif self.dist_type == DistributionType.WEIBULL:
            return "shape" in self.params and "scale" in self.params
        elif self.dist_type == DistributionType.BETA:
            return "alpha" in self.params and "beta" in self.params
        elif self.dist_type == DistributionType.GAMMA:
            return "shape" in self.params and "scale" in self.params
        elif self.dist_type == DistributionType.EMPIRICAL:
            return "values" in self.params
        return False


@dataclass
class SimConfig:
    """
    Simulation configuration and parameters.

    Attributes:
        sim_id: Unique simulation identifier
        start_time: Initial simulation time
        end_time: Target simulation end time (or None for unlimited)
        max_events: Maximum events to process (or None for unlimited)
        random_seed: Random number generator seed
        warmup_time: Transient period before metrics collection
        replications: Number of independent runs
    """

    sim_id: str
    start_time: float = 0.0
    end_time: float | None = None
    max_events: int | None = None
    random_seed: int | None = None
    warmup_time: float = 0.0
    replications: int = 1


@dataclass
class SimState:
    """
    Current state of simulation execution.

    Attributes:
        current_time: Present simulation time
        events_processed: Number of events handled
        agents_active: Number of live agents
        stopped: Whether simulation has terminated
        stop_reason: Reason for termination (if stopped)
    """

    current_time: float = 0.0
    events_processed: int = 0
    agents_active: int = 0
    stopped: bool = False
    stop_reason: str | None = None


@dataclass
class AgentState:
    """
    State snapshot of an agent.

    Attributes:
        agent_id: Unique agent identifier
        agent_type: Type/class of agent
        position: (x, y) coordinates or None for non-spatial
        state: Agent-specific state dict
        alive: Whether agent is active
        birth_time: When agent spawned
        death_time: When agent died (if applicable)
        custom_fields: Additional agent-specific fields
    """

    agent_id: int
    agent_type: str
    position: tuple[float, float] | None = None
    state: dict[str, Any] = field(default_factory=dict)
    alive: bool = True
    birth_time: float = 0.0
    death_time: float | None = None
    custom_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceState:
    """
    State of a named resource.

    Attributes:
        resource_id: Resource identifier
        resource_type: Type of resource
        quantity: Current available amount
        capacity: Maximum capacity (if bounded)
        last_update_time: When last modified
        depletion_rate: Rate of consumption per time unit
        regeneration_rate: Rate of regrowth per time unit
    """

    resource_id: str
    resource_type: str
    quantity: float = 0.0
    capacity: float | None = None
    last_update_time: float = 0.0
    depletion_rate: float = 0.0
    regeneration_rate: float = 0.0


@dataclass
class AgentAction:
    """
    Action taken by an agent.

    Attributes:
        agent_id: Which agent took the action
        action_type: Type of action
        target: Target agent/resource/position
        data: Action-specific parameters
        time: When action was taken
        success: Whether action succeeded
    """

    agent_id: int
    action_type: str
    target: Any | None = None
    data: dict[str, Any] = field(default_factory=dict)
    time: float = 0.0
    success: bool = True


@dataclass
class EnvironmentCell:
    """
    Single cell in a grid-based environment.

    Attributes:
        x: Column index
        y: Row index
        cell_type: Terrain/resource type
        properties: Cell-specific properties (fertility, friction, etc.)
        agents: IDs of agents occupying cell
        value: Continuous scalar value (for diffusion, etc.)
    """

    x: int
    y: int
    cell_type: str = "empty"
    properties: dict[str, Any] = field(default_factory=dict)
    agents: list[int] = field(default_factory=list)
    value: float = 0.0


@dataclass
class MetricSample:
    """
    Single measurement at a point in time.

    Attributes:
        metric_name: Name of measured quantity
        value: Measured value
        time: Simulation time of measurement
        agent_id: Associated agent (if applicable)
        replication: Which replication run (if multiple)
        metadata: Additional context
    """

    metric_name: str
    value: float
    time: float = 0.0
    agent_id: int | None = None
    replication: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimResult:
    """
    Complete output of a simulation run.

    Attributes:
        config: Original simulation configuration
        final_state: Final simulation state
        events_log: Log of all processed events
        agent_trajectories: Trajectory of each agent through time
        metrics: Collected metrics from simulation
        samples: Raw metric samples
        wall_time: Elapsed real time (seconds)
        errors: Any errors encountered
        metadata: Additional result information
    """

    config: SimConfig
    final_state: SimState
    events_log: list[Event] = field(default_factory=list)
    agent_trajectories: dict[int, list[AgentState]] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    samples: list[MetricSample] = field(default_factory=list)
    wall_time: float = 0.0
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
