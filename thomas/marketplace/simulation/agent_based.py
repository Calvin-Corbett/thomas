"""
Agent-Based Modeling (ABM) framework.

Implements agent lifecycle, behavior, perception, environment interaction,
and agent-to-agent communication.
"""

import math
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ._types import AgentAction, AgentState


class BehaviorType(str, Enum):
    """Types of agent behavior."""

    RULE_BASED = "rule_based"
    GOAL_ORIENTED = "goal_oriented"
    REACTIVE = "reactive"
    LEARNING = "learning"


@dataclass
class Rule:
    """
    If-then rule for agent behavior.

    Attributes:
        condition: Callable taking agent and returning bool
        action: Callable to invoke if condition true
        priority: Execution priority (higher = earlier)
    """

    condition: Callable[["Agent"], bool]
    action: Callable[["Agent"], None]
    priority: int = 0

    def __lt__(self, other: "Rule") -> bool:
        """Compare by priority descending."""
        return self.priority > other.priority


@dataclass
class Goal:
    """
    Agent goal with utility function.

    Attributes:
        goal_id: Unique identifier
        description: Human-readable description
        utility: Function computing utility of state
        satisfied: Whether goal is met
    """

    goal_id: str
    description: str
    utility: Callable[["Agent"], float]
    satisfied: bool = False


@dataclass
class Message:
    """
    Message between agents.

    Attributes:
        sender_id: ID of sender
        recipient_id: ID of recipient
        content: Message data
        timestamp: When sent
    """

    sender_id: int
    recipient_id: int
    content: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0


class Agent(ABC):
    """
    Base agent class with perception, decision, and action capabilities.

    Subclasses implement specific behavior strategies.
    """

    _next_id = 0

    def __init__(
        self,
        agent_type: str = "agent",
        position: tuple[float, float] | None = None,
        energy: float = 100.0,
    ) -> None:
        """
        Initialize agent.

        Args:
            agent_type: Type/species of agent
            position: (x, y) coordinates or None for non-spatial
            energy: Initial energy/health
        """
        self.agent_id = Agent._next_id
        Agent._next_id += 1

        self.agent_type = agent_type
        self.position = position
        self.energy = energy
        self.alive = True
        self.birth_time = 0.0
        self.death_time: float | None = None

        # State and behavior
        self.state: dict[str, Any] = {}
        self.rules: list[Rule] = []
        self.goals: dict[str, Goal] = {}
        self.behavior_type = BehaviorType.RULE_BASED

        # Perception and action
        self.perceived_agents: list[Agent] = []
        self.recent_actions: list[AgentAction] = []
        self.received_messages: list[Message] = []

        # Custom fields
        self.metadata: dict[str, Any] = {}

    def perceive(self, environment: "Environment") -> None:
        """
        Perceive environment and agents.

        Args:
            environment: Agent's environment
        """
        if self.position is None:
            return

        # Agents within perception radius
        perception_radius = self.state.get("perception_radius", 10.0)
        self.perceived_agents = environment.agents_near(self.position, perception_radius)
        self.perceived_agents = [a for a in self.perceived_agents if a.agent_id != self.agent_id]

    @abstractmethod
    def decide(self, environment: "Environment") -> list[AgentAction]:
        """
        Make decisions based on perception and goals.

        Args:
            environment: Environment context

        Returns:
            List of actions to take
        """
        pass

    def act(self, action: AgentAction, environment: "Environment") -> bool:
        """
        Execute action in environment.

        Args:
            action: Action to perform
            environment: Environment context

        Returns:
            True if action succeeded
        """
        self.recent_actions.append(action)

        if action.action_type == "move" and self.position:
            dx = action.data.get("dx", 0.0)
            dy = action.data.get("dy", 0.0)
            new_x = self.position[0] + dx
            new_y = self.position[1] + dy
            new_pos = (new_x, new_y)

            if environment.is_valid_position(new_pos):
                self.position = new_pos
                action.success = True
                return True

        elif action.action_type == "consume":
            amount = action.data.get("amount", 1.0)
            self.energy -= amount
            action.success = True
            return True

        elif action.action_type == "produce":
            amount = action.data.get("amount", 1.0)
            self.energy += amount
            action.success = True
            return True

        elif action.action_type == "communicate":
            recipient_id = action.data.get("recipient_id")
            message = Message(
                sender_id=self.agent_id,
                recipient_id=recipient_id,
                content=action.data.get("content", {}),
                timestamp=action.time,
            )
            environment.post_message(message)
            action.success = True
            return True

        action.success = False
        return False

    def add_rule(
        self, condition: Callable[["Agent"], bool], action: Callable[["Agent"], None], priority: int = 0
    ) -> None:
        """Add if-then rule."""
        rule = Rule(condition, action, priority)
        self.rules.append(rule)
        self.rules.sort()

    def add_goal(self, goal: Goal) -> None:
        """Add goal with utility function."""
        self.goals[goal.goal_id] = goal

    def receive_message(self, message: Message) -> None:
        """Receive message from another agent."""
        self.received_messages.append(message)

    def get_state_snapshot(self, time: float) -> AgentState:
        """Get current state for recording."""
        return AgentState(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            position=self.position,
            state=self.state.copy(),
            alive=self.alive,
            birth_time=self.birth_time,
            death_time=self.death_time,
            custom_fields=self.metadata.copy(),
        )

    def die(self, time: float) -> None:
        """Kill agent."""
        self.alive = False
        self.death_time = time


class SimpleAgent(Agent):
    """
    Simple agent with rule-based behavior.

    Executes registered rules in priority order.
    """

    def decide(self, environment: "Environment") -> list[AgentAction]:
        """Execute rules and generate actions."""
        actions = []

        # Execute rules in priority order
        for rule in self.rules:
            try:
                if rule.condition(self):
                    rule.action(self)
            except Exception:
                # Rule execution failed, continue to next
                pass

        return actions


class UtilityAgent(Agent):
    """
    Agent that maximizes utility over goals.

    Selects action that maximizes expected utility.
    """

    def decide(self, environment: "Environment") -> list[AgentAction]:
        """Choose action maximizing utility."""
        actions = []

        if not self.goals:
            return actions

        # Compute utility for each goal
        total_utility = 0.0
        for goal in self.goals.values():
            utility = goal.utility(self)
            total_utility += utility
            goal.satisfied = utility > 0.5

        # Generate actions based on goal utilities
        for goal in self.goals.values():
            if goal.satisfied:
                action = AgentAction(
                    agent_id=self.agent_id,
                    action_type="goal_pursuit",
                    data={"goal_id": goal.goal_id, "utility": goal.utility(self)},
                )
                actions.append(action)

        return actions


class Environment:
    """
    Simulation environment for agents.

    Supports grid-based or continuous space, with resource patches,
    obstacles, and spatial queries.
    """

    def __init__(
        self,
        width: float = 100.0,
        height: float = 100.0,
        grid_based: bool = False,
        cell_size: float | None = None,
        wraparound: bool = False,
    ) -> None:
        """
        Initialize environment.

        Args:
            width: Environment width
            height: Environment height
            grid_based: Use discrete grid vs continuous space
            cell_size: Size of grid cells (if grid_based)
            wraparound: Toroidal topology (wrap at edges)
        """
        self.width = width
        self.height = height
        self.grid_based = grid_based
        self.cell_size = cell_size or 1.0
        self.wraparound = wraparound

        self.agents: list[Agent] = []
        self.obstacles: list[tuple[float, float, float]] = []  # (x, y, radius)
        self.resources: dict[str, list[tuple[float, float, float]]] = {}  # type -> [(x, y, amount)]
        self.messages: list[Message] = []

        # Spatial index for faster queries
        self._spatial_index: dict[tuple[int, int], list[Agent]] = {}

    def add_agent(self, agent: Agent) -> None:
        """Add agent to environment."""
        self.agents.append(agent)
        self._update_spatial_index(agent)

    def remove_agent(self, agent_id: int) -> None:
        """Remove agent from environment."""
        self.agents = [a for a in self.agents if a.agent_id != agent_id]

    def add_obstacle(self, x: float, y: float, radius: float) -> None:
        """Add circular obstacle."""
        self.obstacles.append((x, y, radius))

    def spawn_resource(self, resource_type: str, x: float, y: float, amount: float) -> None:
        """Spawn resource patch."""
        if resource_type not in self.resources:
            self.resources[resource_type] = []
        self.resources[resource_type].append((x, y, amount))

    def is_valid_position(self, pos: tuple[float, float]) -> bool:
        """Check if position is valid (not obstacle, within bounds)."""
        x, y = pos

        # Bounds check
        if self.wraparound:
            x = x % self.width
            y = y % self.height
        else:
            if not (0 <= x <= self.width and 0 <= y <= self.height):
                return False

        # Obstacle check
        for ox, oy, radius in self.obstacles:
            dist = math.sqrt((x - ox) ** 2 + (y - oy) ** 2)
            if dist < radius:
                return False

        return True

    def distance(self, pos1: tuple[float, float], pos2: tuple[float, float]) -> float:
        """Compute distance between positions."""
        x1, y1 = pos1
        x2, y2 = pos2

        if self.wraparound:
            dx = min(abs(x1 - x2), self.width - abs(x1 - x2))
            dy = min(abs(y1 - y2), self.height - abs(y1 - y2))
        else:
            dx = abs(x1 - x2)
            dy = abs(y1 - y2)

        return math.sqrt(dx**2 + dy**2)

    def agents_near(self, position: tuple[float, float], radius: float) -> list[Agent]:
        """Find agents within radius of position."""
        result = []

        for agent in self.agents:
            if agent.position is None:
                continue

            if self.distance(position, agent.position) <= radius:
                result.append(agent)

        return result

    def agents_in_cell(self, cell_x: int, cell_y: int) -> list[Agent]:
        """Get agents in grid cell."""
        return self._spatial_index.get((cell_x, cell_y), [])

    def post_message(self, message: Message) -> None:
        """Post message to be delivered."""
        self.messages.append(message)

    def deliver_messages(self) -> None:
        """Deliver pending messages to recipients."""
        for message in self.messages:
            recipient = next((a for a in self.agents if a.agent_id == message.recipient_id), None)
            if recipient:
                recipient.receive_message(message)

        self.messages = []

    def _update_spatial_index(self, agent: Agent) -> None:
        """Update spatial index for agent."""
        if not self.grid_based or agent.position is None:
            return

        x, y = agent.position
        cell_x = int(x / self.cell_size)
        cell_y = int(y / self.cell_size)
        cell_key = (cell_x, cell_y)

        if cell_key not in self._spatial_index:
            self._spatial_index[cell_key] = []

        self._spatial_index[cell_key].append(agent)

    def get_population(self, agent_type: str | None = None) -> int:
        """Get count of agents (optionally filtered by type)."""
        if agent_type is None:
            return len([a for a in self.agents if a.alive])

        return len([a for a in self.agents if a.alive and a.agent_type == agent_type])


class AgentScheduler:
    """
    Scheduler for agent activation.

    Supports sequential, random, priority, and simultaneous activation.
    """

    def __init__(self, agents: list[Agent], schedule_type: str = "sequential") -> None:
        """
        Initialize scheduler.

        Args:
            agents: Agents to schedule
            schedule_type: Type of scheduling ("sequential", "random", "priority", "simultaneous")
        """
        self.agents = agents
        self.schedule_type = schedule_type
        self.step_count = 0

    def step(self, environment: Environment) -> None:
        """Execute one time step."""
        # Determine activation order
        if self.schedule_type == "sequential":
            active_agents = self.agents
        elif self.schedule_type == "random":
            active_agents = self.agents[:]
            import random

            random.shuffle(active_agents)
        elif self.schedule_type == "priority":
            active_agents = sorted(self.agents, key=lambda a: a.state.get("priority", 0), reverse=True)
        else:  # simultaneous
            active_agents = self.agents

        # Perception phase
        for agent in active_agents:
            if agent.alive:
                agent.perceive(environment)

        # Decision phase
        action_map = {}
        for agent in active_agents:
            if agent.alive:
                actions = agent.decide(environment)
                action_map[agent.agent_id] = actions

        # Action phase
        for agent in active_agents:
            if agent.alive:
                for action in action_map.get(agent.agent_id, []):
                    agent.act(action, environment)

        # Message delivery
        environment.deliver_messages()

        # Death check
        for agent in self.agents:
            if agent.alive and agent.energy <= 0:
                agent.die(self.step_count)

        self.step_count += 1
