"""
Game AI Module - Complete AI system for game development.

This module provides a comprehensive suite of AI algorithms and techniques:
- Behavior Trees: Hierarchical decision-making with composable nodes
- GOAP: Goal-Oriented Action Planning with dynamic replanning
- Utility AI: Weighted decision-making based on utility curves
- Steering: Physics-based movement behaviors
- Navigation: Mesh-based pathfinding with smooth paths
- Influence Maps: Spatial influence propagation and queries
- State Machines: Finite state machines with hierarchical states
- Minimax: Game tree search with alpha-beta pruning
- Squad AI: Formation-based group movement and tactics
"""

from thomas.marketplace.game_ai._exceptions import (
    BehaviorTreeError,
    GameAIError,
    PathfindingError,
)
from thomas.marketplace.game_ai._types import (
    ActionType,
    AIState,
    Blackboard,
    BTNodeStatus,
    GameEntity,
    Goal,
    InfluenceCell,
    NavMeshPolygon,
    UtilityScore,
    Vec2,
)
from thomas.marketplace.game_ai.behavior_tree import (
    Action,
    BehaviorNode,
    BehaviorTree,
    Condition,
    Cooldown,
    Inverter,
    Limiter,
    Parallel,
    Repeater,
    Selector,
    Sequence,
    Succeeder,
    UntilFail,
)
from thomas.marketplace.game_ai.goap import (
    GOAPAction,
    GOAPPlanner,
    WorldState,
)
from thomas.marketplace.game_ai.influence_map import (
    InfluenceLayer,
    InfluenceMap,
)
from thomas.marketplace.game_ai.minimax import (
    GameNode,
    MinimaxEvaluator,
    MinimaxSearcher,
)
from thomas.marketplace.game_ai.navmesh import (
    NavMesh,
    NavMeshQuery,
)
from thomas.marketplace.game_ai.squad import (
    FormationType,
    Squadron,
)
from thomas.marketplace.game_ai.state_machine import (
    State,
    StateMachine,
    StateMessage,
)
from thomas.marketplace.game_ai.steering import (
    Alignment,
    Arrive,
    Cohesion,
    Evade,
    Flee,
    ObstacleAvoidance,
    Pursue,
    Seek,
    Separation,
    SteeringBehavior,
    SteeringManager,
    Wander,
)
from thomas.marketplace.game_ai.utility_ai import (
    Decision,
    ExponentialCurve,
    InverseCurve,
    LinearCurve,
    LogisticCurve,
    StepCurve,
    UtilityAI,
    UtilityCurve,
)

__all__ = [
    # Types
    "Vec2",
    "GameEntity",
    "AIState",
    "BTNodeStatus",
    "ActionType",
    "Goal",
    "NavMeshPolygon",
    "InfluenceCell",
    "UtilityScore",
    "Blackboard",
    # Exceptions
    "GameAIError",
    "PathfindingError",
    "BehaviorTreeError",
    # Behavior Tree
    "BehaviorNode",
    "Sequence",
    "Selector",
    "Parallel",
    "Inverter",
    "Repeater",
    "Succeeder",
    "UntilFail",
    "Cooldown",
    "Limiter",
    "Action",
    "Condition",
    "BehaviorTree",
    # GOAP
    "WorldState",
    "GOAPAction",
    "GOAPPlanner",
    # Utility AI
    "Decision",
    "UtilityCurve",
    "LinearCurve",
    "ExponentialCurve",
    "LogisticCurve",
    "StepCurve",
    "InverseCurve",
    "UtilityAI",
    # Navigation
    "NavMesh",
    "NavMeshQuery",
    # Steering
    "SteeringBehavior",
    "Seek",
    "Flee",
    "Arrive",
    "Pursue",
    "Evade",
    "Wander",
    "Separation",
    "Alignment",
    "Cohesion",
    "ObstacleAvoidance",
    "SteeringManager",
    # Influence Maps
    "InfluenceMap",
    "InfluenceLayer",
    # State Machine
    "State",
    "StateMessage",
    "StateMachine",
    # Minimax
    "GameNode",
    "MinimaxEvaluator",
    "MinimaxSearcher",
    # Squad
    "FormationType",
    "Squadron",
]

__version__ = "1.0.0"
