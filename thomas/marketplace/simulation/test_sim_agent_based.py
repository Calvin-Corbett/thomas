"""
Tests for agent-based modeling framework.
"""

import pytest
from _types import AgentAction
from agent_based import (
    Agent,
    AgentScheduler,
    Environment,
    Goal,
    Message,
    SimpleAgent,
    UtilityAgent,
)


class TestAgent:
    """Test Agent base class."""

    def test_agent_creation(self):
        """Test agent initialization."""
        agent = SimpleAgent("test_agent", position=(5, 5), energy=100.0)

        assert agent.agent_type == "test_agent"
        assert agent.position == (5, 5)
        assert agent.energy == 100.0
        assert agent.alive

    def test_agent_unique_ids(self):
        """Test agents get unique IDs."""
        Agent._next_id = 0
        a1 = SimpleAgent()
        a2 = SimpleAgent()
        a3 = SimpleAgent()

        assert a1.agent_id != a2.agent_id != a3.agent_id

    def test_agent_state_tracking(self):
        """Test agent state dictionary."""
        agent = SimpleAgent()
        agent.state["health"] = 80
        agent.state["energy"] = 50

        assert agent.state["health"] == 80
        assert agent.state["energy"] == 50

    def test_agent_death(self):
        """Test agent death."""
        agent = SimpleAgent()
        agent.die(time=10.0)

        assert not agent.alive
        assert agent.death_time == 10.0


class TestEnvironment:
    """Test Environment class."""

    def test_environment_creation(self):
        """Test environment initialization."""
        env = Environment(width=100.0, height=100.0, wraparound=False)

        assert env.width == 100.0
        assert env.height == 100.0
        assert not env.wraparound

    def test_add_agent(self):
        """Test adding agent to environment."""
        env = Environment()
        agent = SimpleAgent(position=(50, 50))

        env.add_agent(agent)

        assert agent in env.agents
        assert env.get_population() == 1

    def test_remove_agent(self):
        """Test removing agent from environment."""
        env = Environment()
        agent = SimpleAgent(position=(50, 50))

        env.add_agent(agent)
        env.remove_agent(agent.agent_id)

        assert agent not in env.agents
        assert env.get_population() == 0

    def test_valid_position_check(self):
        """Test position validation."""
        env = Environment(width=100.0, height=100.0, wraparound=False)

        assert env.is_valid_position((50, 50))
        assert env.is_valid_position((0, 0))
        assert env.is_valid_position((100, 100))
        assert not env.is_valid_position((-1, 50))
        assert not env.is_valid_position((150, 50))

    def test_distance_calculation(self):
        """Test distance between positions."""
        env = Environment()

        dist = env.distance((0, 0), (3, 4))
        assert dist == pytest.approx(5.0)

    def test_distance_wraparound(self):
        """Test distance with wraparound."""
        env = Environment(width=100.0, height=100.0, wraparound=True)

        # Without wraparound: dist((0,0), (99,0)) = 99
        # With wraparound: dist((0,0), (99,0)) = 1
        dist = env.distance((0, 0), (99, 0))
        assert dist == pytest.approx(1.0)

    def test_agents_near_query(self):
        """Test spatial query for nearby agents."""
        env = Environment()

        a1 = SimpleAgent(position=(50, 50))
        a2 = SimpleAgent(position=(52, 52))
        a3 = SimpleAgent(position=(80, 80))

        env.add_agent(a1)
        env.add_agent(a2)
        env.add_agent(a3)

        nearby = env.agents_near((50, 50), radius=5)

        assert a1 in nearby
        assert a2 in nearby
        assert a3 not in nearby

    def test_add_obstacle(self):
        """Test obstacle creation."""
        env = Environment()
        env.add_obstacle(x=50, y=50, radius=10)

        assert not env.is_valid_position((50, 50))
        assert not env.is_valid_position((52, 50))
        assert env.is_valid_position((65, 50))

    def test_population_counting(self):
        """Test population queries."""
        env = Environment()

        for i in range(5):
            a = SimpleAgent("herbivore")
            env.add_agent(a)

        for i in range(3):
            a = SimpleAgent("carnivore")
            env.add_agent(a)

        assert env.get_population() == 8
        assert env.get_population("herbivore") == 5
        assert env.get_population("carnivore") == 3


class TestSimpleAgent:
    """Test SimpleAgent with rule-based behavior."""

    def test_add_rule(self):
        """Test adding behavior rule."""
        agent = SimpleAgent()

        def condition(a: Agent) -> bool:
            return a.energy < 50

        def action(a: Agent):
            a.energy += 10

        agent.add_rule(condition, action, priority=1)

        assert len(agent.rules) == 1

    def test_rule_execution(self):
        """Test rule condition and action."""
        agent = SimpleAgent()
        agent.energy = 30

        executed = []

        def condition(a: Agent) -> bool:
            return a.energy < 50

        def action(a: Agent):
            executed.append(True)

        agent.add_rule(condition, action)

        env = Environment()
        env.add_agent(agent)
        agent.decide(env)

        assert len(executed) == 1

    def test_rule_priority(self):
        """Test rule execution priority."""
        agent = SimpleAgent()

        order = []

        def action1(a: Agent):
            order.append(1)

        def action2(a: Agent):
            order.append(2)

        agent.add_rule(lambda a: True, action1, priority=1)
        agent.add_rule(lambda a: True, action2, priority=2)

        env = Environment()
        agent.decide(env)

        # Higher priority first
        assert order == [2, 1]


class TestUtilityAgent:
    """Test goal-oriented utility-maximizing agent."""

    def test_add_goal(self):
        """Test adding goal."""
        agent = UtilityAgent()

        def utility(a: Agent) -> float:
            return float(a.energy)

        goal = Goal(
            goal_id="survive",
            description="Maintain energy",
            utility=utility,
        )

        agent.add_goal(goal)

        assert "survive" in agent.goals

    def test_goal_satisfaction(self):
        """Test goal satisfaction determination."""
        agent = UtilityAgent()
        agent.energy = 80

        def utility(a: Agent) -> float:
            return float(a.energy) / 100

        goal = Goal(
            goal_id="survive",
            description="Have sufficient energy",
            utility=utility,
        )

        agent.add_goal(goal)

        env = Environment()
        agent.perceive(env)
        agent.decide(env)

        assert goal.satisfied

    def test_utility_calculation(self):
        """Test utility function evaluation."""
        agent = UtilityAgent()
        agent.energy = 50

        def utility(a: Agent) -> float:
            return a.energy / 100

        goal = Goal(
            goal_id="test",
            description="Test",
            utility=utility,
        )

        agent.add_goal(goal)

        assert utility(agent) == pytest.approx(0.5)


class TestAgentAction:
    """Test agent actions."""

    def test_move_action(self):
        """Test movement action."""
        agent = SimpleAgent(position=(50, 50))
        env = Environment(width=100, height=100)
        env.add_agent(agent)

        action = AgentAction(
            agent_id=agent.agent_id,
            action_type="move",
            data={"dx": 5, "dy": 0},
        )

        success = agent.act(action, env)

        assert success
        assert agent.position == (55, 50)

    def test_consume_action(self):
        """Test consumption action."""
        agent = SimpleAgent(energy=100)
        env = Environment()

        action = AgentAction(
            agent_id=agent.agent_id,
            action_type="consume",
            data={"amount": 10},
        )

        agent.act(action, env)

        assert agent.energy == 90

    def test_produce_action(self):
        """Test production action."""
        agent = SimpleAgent(energy=50)
        env = Environment()

        action = AgentAction(
            agent_id=agent.agent_id,
            action_type="produce",
            data={"amount": 20},
        )

        agent.act(action, env)

        assert agent.energy == 70

    def test_communication_action(self):
        """Test agent communication."""
        a1 = SimpleAgent()
        a2 = SimpleAgent()

        env = Environment()
        env.add_agent(a1)
        env.add_agent(a2)

        message_action = AgentAction(
            agent_id=a1.agent_id,
            action_type="communicate",
            data={
                "recipient_id": a2.agent_id,
                "content": {"signal": "hello"},
            },
            time=0.0,
        )

        a1.act(message_action, env)
        env.deliver_messages()

        assert len(a2.received_messages) == 1
        assert a2.received_messages[0].content["signal"] == "hello"


class TestMessage:
    """Test message passing."""

    def test_message_creation(self):
        """Test message initialization."""
        msg = Message(
            sender_id=1,
            recipient_id=2,
            content={"data": "test"},
            timestamp=0.0,
        )

        assert msg.sender_id == 1
        assert msg.recipient_id == 2
        assert msg.content["data"] == "test"

    def test_message_delivery(self):
        """Test message delivery to agents."""
        a1 = SimpleAgent()
        a2 = SimpleAgent()

        env = Environment()
        env.add_agent(a1)
        env.add_agent(a2)

        msg = Message(
            sender_id=a1.agent_id,
            recipient_id=a2.agent_id,
            content={"greeting": "hello"},
        )

        env.post_message(msg)
        env.deliver_messages()

        assert len(a2.received_messages) == 1


class TestAgentScheduler:
    """Test agent scheduling."""

    def test_sequential_schedule(self):
        """Test sequential activation."""
        agents = [SimpleAgent() for _ in range(5)]
        scheduler = AgentScheduler(agents, schedule_type="sequential")

        env = Environment()
        for a in agents:
            env.add_agent(a)

        # Execute one step
        scheduler.step(env)

        assert scheduler.step_count == 1

    def test_agent_activation_order(self):
        """Test agent activation occurs."""
        agent = SimpleAgent()
        agent.state["activated"] = False

        def set_activated(a: Agent):
            a.state["activated"] = True

        agent.add_rule(lambda a: True, set_activated)

        scheduler = AgentScheduler([agent], schedule_type="sequential")
        env = Environment()
        env.add_agent(agent)

        scheduler.step(env)

        assert agent.state["activated"]

    def test_random_schedule_differs(self):
        """Test random schedule shuffles order."""
        agents = [SimpleAgent() for _ in range(10)]

        seq_scheduler = AgentScheduler(agents, schedule_type="sequential")
        rand_scheduler = AgentScheduler(agents, schedule_type="random")

        seq_agents = seq_scheduler.get_active_agents()
        rand_agents = rand_scheduler.get_active_agents()

        # IDs should be different (unless very unlucky)
        seq_ids = [a.agent_id for a in seq_agents]
        rand_ids = [a.agent_id for a in rand_agents]

        assert len(set(seq_ids)) == 10
        assert len(set(rand_ids)) == 10


class TestAgentPerception:
    """Test agent perception capabilities."""

    def test_perceive_environment(self):
        """Test agent perceives nearby agents."""
        a1 = SimpleAgent(position=(50, 50))
        a1.state["perception_radius"] = 10

        a2 = SimpleAgent(position=(55, 55))
        a3 = SimpleAgent(position=(100, 100))

        env = Environment()
        env.add_agent(a1)
        env.add_agent(a2)
        env.add_agent(a3)

        a1.perceive(env)

        assert a2 in a1.perceived_agents
        assert a3 not in a1.perceived_agents

    def test_perception_excludes_self(self):
        """Test agent doesn't perceive itself."""
        agent = SimpleAgent(position=(50, 50))
        agent.state["perception_radius"] = 100

        env = Environment()
        env.add_agent(agent)

        agent.perceive(env)

        assert agent not in agent.perceived_agents


class TestAgentMetadata:
    """Test agent custom metadata."""

    def test_custom_fields(self):
        """Test custom metadata fields."""
        agent = SimpleAgent()

        agent.metadata["species"] = "herbivore"
        agent.metadata["color"] = "brown"

        assert agent.metadata["species"] == "herbivore"
        assert agent.metadata["color"] == "brown"

    def test_state_snapshot(self):
        """Test agent state snapshot for recording."""
        agent = SimpleAgent(position=(10, 20), energy=50)
        agent.state["custom"] = "value"

        snapshot = agent.get_state_snapshot(time=10.0)

        assert snapshot.agent_id == agent.agent_id
        assert snapshot.position == (10, 20)
        assert snapshot.state["custom"] == "value"
        assert snapshot.alive
