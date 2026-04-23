"""
Thomas simulation module: Discrete event, Monte Carlo, and agent-based simulation engines.

Provides a comprehensive framework for building and running various types of simulations.
"""

# Core types and exceptions
from ._exceptions import (
    AgentError,
    DistributionError,
    EnvironmentError,
    EventError,
    MetricsError,
    ResourceError,
    ScheduleError,
    SimulationError,
)
from ._types import (
    AgentAction,
    AgentState,
    Distribution,
    DistributionType,
    EnvironmentCell,
    Event,
    EventType,
    MetricSample,
    ResourceState,
    SimConfig,
    SimResult,
    SimState,
)

# Agent-Based Modeling
from .agent_based import (
    Agent,
    AgentScheduler,
    BehaviorType,
    Environment,
    Goal,
    Message,
    Rule,
    SimpleAgent,
    UtilityAgent,
)

# Discrete Event Simulation
from .discrete_event import (
    ConditionalEvent,
    DiscreteEventSimulation,
    EventHandler,
)

# Distributions
from .distributions import (
    Beta,
    EmpiricalDistribution,
    Exponential,
    Lognormal,
    MixedDistribution,
    Normal,
    Poisson,
    Triangular,
    UniformContinuous,
    UniformDiscrete,
    fit_distribution,
)

# Environment
from .environment import (
    ContinuousEnvironment,
    GridEnvironment,
    ResourcePatch,
    ResourceType,
    TerrainType,
)

# Metrics
from .metrics import (
    BatchMean,
    BatchMeansAnalysis,
    ConfidenceIntervals,
    MetricsCollector,
    MultipleReplications,
    SensitivityAnalysis,
    WarmupDetection,
)

# Monte Carlo
from .monte_carlo import (
    ConvergenceMonitoring,
    MonteCarloIntegration,
    MonteCarloResult,
    RandomVariableGenerator,
    RiskSimulation,
    VarianceReduction,
)

# Queueing Models
from .queue_models import (
    Customer,
    MD1Queue,
    MM1Queue,
    MMcQueue,
    PriorityLevel,
    PriorityQueue,
    QueueStatistics,
    Server,
)

# Scenarios
from .scenarios import (
    BankQueueConfig,
    BankQueueScenario,
    EpidemicConfig,
    EpidemicScenario,
    PredatorPreyConfig,
    PredatorPreyScenario,
    SupplyChainConfig,
    SupplyChainScenario,
    TrafficConfig,
    TrafficScenario,
)

# Scheduler
from .scheduler import (
    CompositeScheduler,
    EventDrivenSchedule,
    LazyActivationSchedule,
    PrioritySchedule,
    RandomSchedule,
    ScheduleGroup,
    ScheduleStrategy,
    SequentialSchedule,
    SimultaneousSchedule,
)

__version__ = "1.0.0"
__all__ = [
    # Types
    "Event",
    "EventType",
    "Distribution",
    "DistributionType",
    "SimConfig",
    "SimState",
    "AgentState",
    "ResourceState",
    "AgentAction",
    "EnvironmentCell",
    "MetricSample",
    "SimResult",
    # Exceptions
    "SimulationError",
    "EventError",
    "AgentError",
    "ResourceError",
    "ScheduleError",
    "DistributionError",
    "EnvironmentError",
    "MetricsError",
    # Discrete Event
    "DiscreteEventSimulation",
    "EventHandler",
    "ConditionalEvent",
    # Queueing
    "MM1Queue",
    "MMcQueue",
    "MD1Queue",
    "PriorityQueue",
    "Customer",
    "Server",
    "QueueStatistics",
    "PriorityLevel",
    # Monte Carlo
    "RandomVariableGenerator",
    "MonteCarloIntegration",
    "RiskSimulation",
    "VarianceReduction",
    "ConvergenceMonitoring",
    "MonteCarloResult",
    # Distributions
    "UniformContinuous",
    "UniformDiscrete",
    "Normal",
    "Exponential",
    "Poisson",
    "Triangular",
    "Lognormal",
    "Beta",
    "EmpiricalDistribution",
    "MixedDistribution",
    "fit_distribution",
    # ABM
    "Agent",
    "SimpleAgent",
    "UtilityAgent",
    "Environment",
    "AgentScheduler",
    "Rule",
    "Goal",
    "Message",
    "BehaviorType",
    # Environment
    "GridEnvironment",
    "ContinuousEnvironment",
    "ResourcePatch",
    "TerrainType",
    "ResourceType",
    # Scheduler
    "ScheduleStrategy",
    "SequentialSchedule",
    "RandomSchedule",
    "PrioritySchedule",
    "SimultaneousSchedule",
    "EventDrivenSchedule",
    "LazyActivationSchedule",
    "ScheduleGroup",
    "CompositeScheduler",
    # Metrics
    "MetricsCollector",
    "BatchMeansAnalysis",
    "BatchMean",
    "WarmupDetection",
    "ConfidenceIntervals",
    "MultipleReplications",
    "SensitivityAnalysis",
    # Scenarios
    "EpidemicScenario",
    "EpidemicConfig",
    "SupplyChainScenario",
    "SupplyChainConfig",
    "TrafficScenario",
    "TrafficConfig",
    "PredatorPreyScenario",
    "PredatorPreyConfig",
    "BankQueueScenario",
    "BankQueueConfig",
]
