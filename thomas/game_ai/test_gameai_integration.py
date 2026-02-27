"""
Integration tests combining multiple AI systems.

Tests behavior trees with steering, GOAP with planning, navmesh pathfinding,
and complete AI agent scenarios.
"""

import unittest

from thomas.game_ai._types import ActionType, GameEntity, NavMeshPolygon, Vec2
from thomas.game_ai.behavior_tree import Action, BehaviorTree, BTNodeStatus, Condition, Sequence
from thomas.game_ai.goap import Goal, GOAPAction, GOAPPlanner
from thomas.game_ai.navmesh import NavMesh, NavMeshQuery
from thomas.game_ai.steering import Flee, Seek, SteeringManager
from thomas.game_ai.utility_ai import Decision, UtilityAI


class TestBehaviorTreeWithSteering(unittest.TestCase):
    """Test behavior tree controlling steering behaviors."""

    def test_seek_behavior_tree(self):
        """Test tree that uses steering to seek target."""
        target = Vec2(10, 0)
        entity = GameEntity(id=1, position=Vec2(0, 0), velocity=Vec2(0, 0))

        # BT that seeks target
        root = Sequence("seek_sequence")

        root.add_child(
            Condition(
                "target_exists",
                lambda bb: bb.get("target") is not None,
            )
        )

        def seek_action(bb, dt):
            target_pos = bb.get("target")
            seek = Seek(target_pos, max_force=10.0)
            output = seek.calculate(entity)

            entity.velocity = entity.velocity + output.force * dt
            entity.position = entity.position + entity.velocity * dt

            return BTNodeStatus.RUNNING if entity.position.distance_to(target_pos) > 1.0 else BTNodeStatus.SUCCESS

        root.add_child(Action("apply_seek", seek_action))

        tree = BehaviorTree(root)
        tree.set_blackboard_value("target", target)

        # Tick tree until seeking completes or times out
        for _ in range(100):
            status = tree.tick(0.016)
            if status != BTNodeStatus.RUNNING:
                break

        # Entity should have moved toward target
        self.assertGreater(entity.position.x, 0)

    def test_flee_behavior_tree(self):
        """Test tree that uses steering to flee."""
        threat = Vec2(5, 0)
        entity = GameEntity(id=1, position=Vec2(0, 0), velocity=Vec2(0, 0))

        root = Sequence("flee_sequence")

        def flee_action(bb, dt):
            threat_pos = bb.get("threat")
            flee = Flee(threat_pos, max_force=10.0, panic_distance=20.0)
            output = flee.calculate(entity)

            entity.velocity = entity.velocity + output.force * dt
            entity.position = entity.position + entity.velocity * dt

            return BTNodeStatus.RUNNING

        root.add_child(Action("apply_flee", flee_action))

        tree = BehaviorTree(root)
        tree.set_blackboard_value("threat", threat)

        # Tick a few times
        for _ in range(10):
            tree.tick(0.016)

        # Entity should have negative velocity (fleeing)
        self.assertLess(entity.position.x, 0)


class TestNavMeshPathfinding(unittest.TestCase):
    """Test navmesh pathfinding in behavior tree."""

    def setUp(self):
        """Set up navmesh."""
        self.poly1 = NavMeshPolygon(id=1, vertices=[Vec2(0, 0), Vec2(10, 0), Vec2(10, 10), Vec2(0, 10)])

        self.poly2 = NavMeshPolygon(id=2, vertices=[Vec2(10, 0), Vec2(20, 0), Vec2(20, 10), Vec2(10, 10)])

        self.mesh = NavMesh([self.poly1, self.poly2])
        self.query = NavMeshQuery(self.mesh)

    def test_pathfinding_in_tree(self):
        """Test behavior tree finding path."""
        entity = GameEntity(id=1, position=Vec2(2, 5), velocity=Vec2(0, 0))
        goal_pos = Vec2(15, 5)

        # Tree that finds and follows path
        root = Sequence("follow_path")

        path_container = {"path": [], "index": 0}

        def find_path_action(bb, dt):
            if not path_container["path"]:
                path_container["path"] = self.query.find_path(entity.position, goal_pos)

            return BTNodeStatus.SUCCESS if path_container["path"] else BTNodeStatus.FAILURE

        def follow_path_action(bb, dt):
            if path_container["index"] >= len(path_container["path"]):
                return BTNodeStatus.SUCCESS

            target = path_container["path"][path_container["index"]]

            # Move toward waypoint
            direction = target - entity.position
            if direction.magnitude() > 0.5:
                entity.velocity = direction.normalize() * 5.0
                entity.position = entity.position + entity.velocity * dt
            else:
                path_container["index"] += 1

            return (
                BTNodeStatus.RUNNING if path_container["index"] < len(path_container["path"]) else BTNodeStatus.SUCCESS
            )

        root.add_child(Action("find_path", find_path_action))
        root.add_child(Action("follow_path", follow_path_action))

        tree = BehaviorTree(root)

        # Execute tree
        for _ in range(200):
            status = tree.tick(0.016)
            if status != BTNodeStatus.RUNNING:
                break

        # Entity should have reached goal area
        self.assertLess(entity.position.distance_to(goal_pos), 2.0)


class TestGOAPWithUtility(unittest.TestCase):
    """Test GOAP planning with utility-based decision making."""

    def test_plan_selection_with_utility(self):
        """Test selecting goal based on utility."""
        # Create GOAP planner
        planner = GOAPPlanner()

        gather_wood = GOAPAction(
            name="gather_wood",
            action_type=ActionType.GATHER,
            preconditions={"location": "forest"},
            effects={"has_wood": True},
            cost=2.0,
        )

        gather_stone = GOAPAction(
            name="gather_stone",
            action_type=ActionType.GATHER,
            preconditions={"location": "mountain"},
            effects={"has_stone": True},
            cost=2.0,
        )

        planner.register_actions([gather_wood, gather_stone])

        # Create utility AI to select which goal
        ai = UtilityAI()

        wood_goal = Decision(name="get_wood", composition_mode="multiply")
        wood_goal.add_consideration(
            "need_wood",
            lambda bb: 1.0 if bb.get("wood_count", 0) < bb.get("max_wood", 5) else 0.0,
        )

        stone_goal = Decision(name="get_stone", composition_mode="multiply")
        stone_goal.add_consideration(
            "need_stone",
            lambda bb: 1.0 if bb.get("stone_count", 0) < bb.get("max_stone", 5) else 0.0,
        )

        ai.register_decision(wood_goal)
        ai.register_decision(stone_goal)

        # With low wood
        blackboard = {
            "wood_count": 1,
            "max_wood": 5,
            "stone_count": 5,
            "max_stone": 5,
        }

        choice = ai.choose_decision(blackboard, method="highest")
        self.assertEqual(choice, "get_wood")

        # With low stone
        blackboard = {
            "wood_count": 5,
            "max_wood": 5,
            "stone_count": 1,
            "max_stone": 5,
        }

        choice = ai.choose_decision(blackboard, method="highest")
        self.assertEqual(choice, "get_stone")


class TestCompleteAIAgent(unittest.TestCase):
    """Test complete AI agent with multiple systems."""

    def test_complete_agent_loop(self):
        """Test full agent loop with planning and execution."""
        # Create agent
        agent = GameEntity(id=1, position=Vec2(0, 0), velocity=Vec2(0, 0))

        # Create navmesh
        poly1 = NavMeshPolygon(id=1, vertices=[Vec2(-5, -5), Vec2(5, -5), Vec2(5, 5), Vec2(-5, 5)])

        poly2 = NavMeshPolygon(id=2, vertices=[Vec2(5, -5), Vec2(15, -5), Vec2(15, 5), Vec2(5, 5)])

        mesh = NavMesh([poly1, poly2])
        query = NavMeshQuery(mesh)

        # Create GOAP planner
        planner = GOAPPlanner()

        move_action = GOAPAction(
            name="move_to_target",
            action_type=ActionType.MOVE,
            preconditions={"can_move": True},
            effects={"at_target": True},
            cost=1.0,
        )

        planner.register_action(move_action)

        # Create behavior tree for execution
        root = Sequence("agent_ai")

        def plan_action(bb, dt):
            if bb.get("plan") is None:
                goal = Goal("reach_target", {"at_target": True})
                current_state = {"can_move": True, "at_target": False}
                plan = planner.plan(current_state, goal)

                if plan:
                    bb["plan"] = plan
                    return BTNodeStatus.SUCCESS

            return BTNodeStatus.FAILURE

        def navigate_action(bb, dt):
            path = query.find_path(agent.position, Vec2(10, 0))

            if path:
                target = path[1] if len(path) > 1 else path[0]
                direction = target - agent.position

                if direction.magnitude() > 0.1:
                    agent.velocity = direction.normalize() * 5.0
                    agent.position = agent.position + agent.velocity * dt
                    return BTNodeStatus.RUNNING

            return BTNodeStatus.SUCCESS

        root.add_child(Action("plan", plan_action))
        root.add_child(Action("navigate", navigate_action))

        tree = BehaviorTree(root)

        # Run agent
        for _ in range(200):
            status = tree.tick(0.016)
            if status == BTNodeStatus.SUCCESS:
                break

        # Agent should have moved
        self.assertGreater(agent.position.x, 0)


class TestSteeringWithMultipleBehaviors(unittest.TestCase):
    """Test steering manager with multiple blended behaviors."""

    def test_flocking_behavior(self):
        """Test simple flocking."""
        from thomas.game_ai.steering import Alignment, Cohesion, Separation

        # Create flock
        entities = [GameEntity(id=i, position=Vec2(i * 2, 0), velocity=Vec2(1, 0)) for i in range(3)]

        # Create steering manager for first entity
        manager = SteeringManager()

        # Add flocking behaviors
        separation = Separation(entities, separation_distance=3.0)
        alignment = Alignment(entities, alignment_distance=10.0)
        cohesion = Cohesion(entities, cohesion_distance=10.0)

        manager.add_behavior(separation, weight=1.5)
        manager.add_behavior(alignment, weight=1.0)
        manager.add_behavior(cohesion, weight=1.0)

        # Update entities
        for _ in range(20):
            manager.update_entity(entities[0], delta_time=0.016, max_speed=5.0)

        # Entities should maintain spacing
        self.assertGreater(entities[0].position.distance_to(entities[1].position), 0)


class TestStateTransitions(unittest.TestCase):
    """Test state machine integration with other systems."""

    def test_state_driven_behavior(self):
        """Test behavior tree responding to state changes."""
        from thomas.game_ai.state_machine import SimpleState, StateMachine

        # Create state machine
        idle_state = SimpleState(
            "idle",
            on_execute_func=lambda bb: None,
        )

        attacking_state = SimpleState(
            "attacking",
            on_execute_func=lambda bb: None,
        )

        fsm = StateMachine(idle_state)
        fsm.add_state(attacking_state)

        # Create tree that responds to state
        root = Sequence("state_aware_ai")

        def check_state(bb):
            return fsm.current_state_name == "attacking"

        def attack_action(bb, dt):
            return BTNodeStatus.SUCCESS

        root.add_child(Condition("is_attacking", check_state))
        root.add_child(Action("execute_attack", attack_action))

        tree = BehaviorTree(root)

        # When idle, tree should fail
        status = tree.tick(0.016)
        self.assertEqual(status, BTNodeStatus.FAILURE)

        # Change state
        fsm.change_state(attacking_state)

        # Now tree should succeed
        status = tree.tick(0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)


if __name__ == "__main__":
    unittest.main()
