"""
Agent scheduling strategies for coordinating agent activation.

Implements sequential, random, priority, simultaneous, event-driven,
and lazy activation scheduling.
"""

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .agent_based import Agent, Environment


class ScheduleStrategy(ABC):
    """Base class for scheduling strategies."""

    @abstractmethod
    def get_active_agents(self) -> list[Agent]:
        """
        Determine which agents should be active this step.

        Returns:
            List of agents to activate
        """
        pass

    @abstractmethod
    def step(self, environment: Environment) -> None:
        """Execute one simulation step."""
        pass


class SequentialSchedule(ScheduleStrategy):
    """
    Sequential activation: agents activate in fixed order.

    Reproducible and simple, but creates systematic bias.
    """

    def __init__(self, agents: list[Agent]) -> None:
        """Initialize sequential scheduler."""
        self.agents = agents
        self.step_count = 0

    def get_active_agents(self) -> list[Agent]:
        """Return agents in order."""
        return [a for a in self.agents if a.alive]

    def step(self, environment: Environment) -> None:
        """Activate agents in sequence."""
        active_agents = self.get_active_agents()

        # Perception phase
        for agent in active_agents:
            agent.perceive(environment)

        # Decision and action phases
        for agent in active_agents:
            actions = agent.decide(environment)
            for action in actions:
                agent.act(action, environment)

        # Message delivery
        environment.deliver_messages()

        # Age agents
        for agent in self.agents:
            if agent.alive and agent.energy <= 0:
                agent.die(self.step_count)

        self.step_count += 1


class RandomSchedule(ScheduleStrategy):
    """
    Random order activation: agents activate in random order each step.

    Reduces systematic bias at cost of non-reproducibility
    (unless seed fixed).
    """

    def __init__(self, agents: list[Agent]) -> None:
        """Initialize random scheduler."""
        self.agents = agents
        self.step_count = 0

    def get_active_agents(self) -> list[Agent]:
        """Return agents in random order."""
        active = [a for a in self.agents if a.alive]
        random.shuffle(active)
        return active

    def step(self, environment: Environment) -> None:
        """Activate agents in random order."""
        active_agents = self.get_active_agents()

        # Perception phase
        for agent in active_agents:
            agent.perceive(environment)

        # Decision and action phases
        for agent in active_agents:
            actions = agent.decide(environment)
            for action in actions:
                agent.act(action, environment)

        # Message delivery
        environment.deliver_messages()

        # Age agents
        for agent in self.agents:
            if agent.alive and agent.energy <= 0:
                agent.die(self.step_count)

        self.step_count += 1


class PrioritySchedule(ScheduleStrategy):
    """
    Priority-based activation: agents with higher priority activate first.

    Priority determined by agent state variable.
    """

    def __init__(self, agents: list[Agent]) -> None:
        """Initialize priority scheduler."""
        self.agents = agents
        self.step_count = 0

    def get_active_agents(self) -> list[Agent]:
        """Return agents sorted by priority."""
        active = [a for a in self.agents if a.alive]
        return sorted(active, key=lambda a: a.state.get("priority", 0), reverse=True)

    def step(self, environment: Environment) -> None:
        """Activate agents by priority."""
        active_agents = self.get_active_agents()

        # Perception phase
        for agent in active_agents:
            agent.perceive(environment)

        # Decision and action phases
        for agent in active_agents:
            actions = agent.decide(environment)
            for action in actions:
                agent.act(action, environment)

        # Message delivery
        environment.deliver_messages()

        # Age agents
        for agent in self.agents:
            if agent.alive and agent.energy <= 0:
                agent.die(self.step_count)

        self.step_count += 1


class SimultaneousSchedule(ScheduleStrategy):
    """
    Simultaneous activation: all agents perceive, then all act.

    Reduces interaction order bias, more realistic for some systems.
    """

    def __init__(self, agents: list[Agent]) -> None:
        """Initialize simultaneous scheduler."""
        self.agents = agents
        self.step_count = 0

    def get_active_agents(self) -> list[Agent]:
        """Return all active agents."""
        return [a for a in self.agents if a.alive]

    def step(self, environment: Environment) -> None:
        """Execute simultaneous activation."""
        active_agents = self.get_active_agents()

        # All agents perceive first
        for agent in active_agents:
            agent.perceive(environment)

        # All agents decide
        decisions = {}
        for agent in active_agents:
            decisions[agent.agent_id] = agent.decide(environment)

        # All agents act
        for agent in active_agents:
            for action in decisions.get(agent.agent_id, []):
                agent.act(action, environment)

        # Message delivery
        environment.deliver_messages()

        # Age agents
        for agent in self.agents:
            if agent.alive and agent.energy <= 0:
                agent.die(self.step_count)

        self.step_count += 1


class EventDrivenSchedule(ScheduleStrategy):
    """
    Event-driven activation: agents activate only when events occur.

    Efficient when agents are mostly inactive.
    """

    def __init__(self, agents: list[Agent]) -> None:
        """Initialize event-driven scheduler."""
        self.agents = agents
        self.active_set: set[int] = set(a.agent_id for a in agents)
        self.step_count = 0

    def get_active_agents(self) -> list[Agent]:
        """Return currently active agents."""
        return [a for a in self.agents if a.agent_id in self.active_set and a.alive]

    def mark_active(self, agent_id: int) -> None:
        """Mark agent as active."""
        self.active_set.add(agent_id)

    def mark_inactive(self, agent_id: int) -> None:
        """Mark agent as inactive."""
        self.active_set.discard(agent_id)

    def step(self, environment: Environment) -> None:
        """Execute event-driven activation."""
        active_agents = self.get_active_agents()

        # Perception phase
        for agent in active_agents:
            agent.perceive(environment)

        # Decision and action phases
        for agent in active_agents:
            actions = agent.decide(environment)
            for action in actions:
                agent.act(action, environment)

        # Message delivery
        environment.deliver_messages()

        # Age agents and mark inactive
        for agent in self.agents:
            if agent.alive and agent.energy <= 0:
                agent.die(self.step_count)
                self.mark_inactive(agent.agent_id)

        self.step_count += 1


class LazyActivationSchedule(ScheduleStrategy):
    """
    Lazy activation: track last activation time, skip unchanged agents.

    Most efficient for sparse interactions.
    """

    def __init__(self, agents: list[Agent]) -> None:
        """Initialize lazy scheduler."""
        self.agents = agents
        self.last_activation: dict[int, int] = {a.agent_id: 0 for a in agents}
        self.step_count = 0

    def get_active_agents(self) -> list[Agent]:
        """Return agents needing activation."""
        threshold = max(0, self.step_count - 5)  # Reactivate every 5 steps

        return [
            a
            for a in self.agents
            if a.alive and (a.agent_id in self.last_activation and self.last_activation[a.agent_id] <= threshold)
        ]

    def step(self, environment: Environment) -> None:
        """Execute lazy activation."""
        active_agents = self.get_active_agents()

        # Perception phase
        for agent in active_agents:
            agent.perceive(environment)

        # Decision and action phases
        for agent in active_agents:
            actions = agent.decide(environment)
            if actions:  # Only mark active if took action
                for action in actions:
                    agent.act(action, environment)
                self.last_activation[agent.agent_id] = self.step_count

        # Message delivery
        environment.deliver_messages()

        # Age agents
        for agent in self.agents:
            if agent.alive and agent.energy <= 0:
                agent.die(self.step_count)

        self.step_count += 1


@dataclass
class ScheduleGroup:
    """Group of agents with specific schedule."""

    group_id: str
    agents: list[Agent]
    schedule: ScheduleStrategy
    update_frequency: int = 1  # Update every N global steps


class CompositeScheduler:
    """
    Manage multiple schedule groups with different frequencies.

    Allows different agent types to have different activation patterns.
    """

    def __init__(self) -> None:
        """Initialize composite scheduler."""
        self.groups: dict[str, ScheduleGroup] = {}
        self.step_count = 0

    def add_group(
        self,
        group_id: str,
        agents: list[Agent],
        schedule_type: str = "sequential",
        update_frequency: int = 1,
    ) -> None:
        """
        Add schedule group.

        Args:
            group_id: Unique group identifier
            agents: Agents in group
            schedule_type: "sequential", "random", "priority", "simultaneous"
            update_frequency: How often to update this group
        """
        if schedule_type == "sequential":
            schedule = SequentialSchedule(agents)
        elif schedule_type == "random":
            schedule = RandomSchedule(agents)
        elif schedule_type == "priority":
            schedule = PrioritySchedule(agents)
        elif schedule_type == "simultaneous":
            schedule = SimultaneousSchedule(agents)
        else:
            raise ValueError(f"Unknown schedule type: {schedule_type}")

        self.groups[group_id] = ScheduleGroup(group_id, agents, schedule, update_frequency)

    def step(self, environment: Environment) -> None:
        """Execute one global step with all groups."""
        for group in self.groups.values():
            if self.step_count % group.update_frequency == 0:
                group.schedule.step(environment)

        self.step_count += 1

    def get_statistics(self) -> dict[str, int]:
        """Get scheduler statistics."""
        stats = {
            "step_count": self.step_count,
            "num_groups": len(self.groups),
        }

        for group_id, group in self.groups.items():
            stats[f"{group_id}_active"] = len([a for a in group.agents if a.alive])
            stats[f"{group_id}_steps"] = group.schedule.step_count

        return stats
