"""
Tests for steering behaviors system.

Tests individual behaviors (seek, flee, pursue, etc.) and flocking behaviors.
"""

import unittest

from thomas.marketplace.game_ai._types import GameEntity, Vec2
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
    SteeringManager,
    SteeringOutput,
    Wander,
)


class TestBasicBehaviors(unittest.TestCase):
    """Test basic steering behaviors."""

    def setUp(self):
        """Set up test entities."""
        self.entity = GameEntity(
            id=1,
            position=Vec2(0, 0),
            velocity=Vec2(1, 0),
            faction="player",
        )

    def test_seek_toward_target(self):
        """Test seek behavior moves toward target."""
        target = Vec2(10, 0)
        seek = Seek(target, max_force=10.0)

        output = seek.calculate(self.entity)

        self.assertTrue(output.is_active)
        # Force should point toward target
        self.assertGreater(output.force.x, 0)

    def test_seek_at_target(self):
        """Test seek at target position."""
        self.entity.position = Vec2(10, 0)
        target = Vec2(10, 0)
        seek = Seek(target)

        output = seek.calculate(self.entity)

        self.assertFalse(output.is_active)
        self.assertEqual(output.force.magnitude(), 0)

    def test_flee_away_from_threat(self):
        """Test flee behavior moves away."""
        threat = Vec2(10, 0)
        flee = Flee(threat, max_force=10.0, panic_distance=20.0)

        output = flee.calculate(self.entity)

        self.assertTrue(output.is_active)
        # Force should point away
        self.assertLess(output.force.x, 0)

    def test_flee_outside_panic_distance(self):
        """Test flee when outside panic distance."""
        threat = Vec2(100, 0)
        flee = Flee(threat, panic_distance=20.0)

        output = flee.calculate(self.entity)

        self.assertFalse(output.is_active)

    def test_arrive_slows_down(self):
        """Test arrive slows near target."""
        target = Vec2(10, 0)
        self.entity.velocity = Vec2(5, 0)

        arrive = Arrive(target, arrival_distance=5.0)
        output = arrive.calculate(self.entity)

        # Arrive should be active and slow down
        self.assertTrue(output.is_active)

    def test_arrive_at_target(self):
        """Test arrive at target."""
        self.entity.position = Vec2(10, 0)
        target = Vec2(10, 0)
        arrive = Arrive(target)

        output = arrive.calculate(self.entity)

        self.assertFalse(output.is_active)

    def test_wander_creates_movement(self):
        """Test wander creates steering force."""
        wander = Wander()

        output = wander.calculate(self.entity)

        self.assertTrue(output.is_active)
        self.assertGreater(output.force.magnitude(), 0)


class TestPredictiveBehaviors(unittest.TestCase):
    """Test behaviors that predict movement."""

    def setUp(self):
        """Set up test entities."""
        self.player = GameEntity(
            id=1,
            position=Vec2(0, 0),
            velocity=Vec2(5, 0),
            faction="player",
        )

        self.target = GameEntity(
            id=2,
            position=Vec2(10, 0),
            velocity=Vec2(2, 0),
            faction="enemy",
        )

    def test_pursue_moves_to_predicted_pos(self):
        """Test pursue predicts target position."""
        pursue = Pursue(self.target, prediction_time=1.0)

        output = pursue.calculate(self.player)

        # Should return active output (may be 0 if already aligned)
        self.assertTrue(output.is_active)

    def test_evade_flees_from_predicted_pos(self):
        """Test evade predicts threat position."""
        self.target.position = Vec2(2, 0)  # Close to player

        evade = Evade(self.target, prediction_time=1.0, panic_distance=20.0)

        output = evade.calculate(self.player)

        # Should flee from predicted position
        self.assertTrue(output.is_active)


class TestFlockingBehaviors(unittest.TestCase):
    """Test flocking (group) behaviors."""

    def setUp(self):
        """Set up flock."""
        self.boid1 = GameEntity(id=1, position=Vec2(0, 0), velocity=Vec2(1, 0))
        self.boid2 = GameEntity(id=2, position=Vec2(2, 0), velocity=Vec2(1, 0))
        self.boid3 = GameEntity(id=3, position=Vec2(4, 0), velocity=Vec2(1, 0))

        self.neighbors = [self.boid1, self.boid2, self.boid3]

    def test_separation_keeps_distance(self):
        """Test separation keeps neighbors apart."""
        sep = Separation(self.neighbors, separation_distance=3.0)

        output = sep.calculate(self.boid1)

        # Should try to separate from boid2 and boid3
        self.assertTrue(output.is_active)
        # Force should point backward (away from neighbors)
        self.assertLess(output.force.x, 0)

    def test_alignment_matches_heading(self):
        """Test alignment matches neighbor velocities."""
        self.boid2.velocity = Vec2(2, 1)  # Different heading
        align = Alignment(self.neighbors, alignment_distance=10.0)

        output = align.calculate(self.boid1)

        # Should adjust to match average heading
        self.assertTrue(output.is_active)

    def test_cohesion_moves_toward_center(self):
        """Test cohesion moves toward neighbor center."""
        # Neighbors are ahead of boid1
        coh = Cohesion(self.neighbors, cohesion_distance=10.0)

        output = coh.calculate(self.boid1)

        # Should move toward center of neighbors
        self.assertTrue(output.is_active)
        self.assertGreater(output.force.x, 0)

    def test_separation_no_neighbors(self):
        """Test separation with isolated entity."""
        sep = Separation([self.boid1], separation_distance=3.0)

        output = sep.calculate(self.boid1)

        self.assertFalse(output.is_active)


class TestObstacleAvoidance(unittest.TestCase):
    """Test obstacle avoidance behavior."""

    def test_avoid_approaching_obstacle(self):
        """Test avoidance of approaching obstacle."""
        entity = GameEntity(
            id=1,
            position=Vec2(0, 0),
            velocity=Vec2(5, 0),
            faction="player",
        )

        obstacles = [Vec2(10, 0), Vec2(20, 0)]
        avoid = ObstacleAvoidance(obstacles, detection_range=15.0)

        output = avoid.calculate(entity)

        # Should detect obstacle ahead
        self.assertTrue(output.is_active)
        # Should steer away from it
        self.assertLess(output.force.y, output.force.y if output.force.y > 0 else 1)

    def test_no_obstacles(self):
        """Test with no obstacles."""
        entity = GameEntity(id=1, position=Vec2(0, 0), velocity=Vec2(5, 0))

        avoid = ObstacleAvoidance([], detection_range=15.0)

        output = avoid.calculate(entity)

        self.assertFalse(output.is_active)

    def test_obstacle_out_of_range(self):
        """Test obstacle outside detection range."""
        entity = GameEntity(id=1, position=Vec2(0, 0), velocity=Vec2(5, 0))

        obstacles = [Vec2(100, 0)]
        avoid = ObstacleAvoidance(obstacles, detection_range=15.0)

        output = avoid.calculate(entity)

        self.assertFalse(output.is_active)


class TestSteeringManager(unittest.TestCase):
    """Test steering manager with blended behaviors."""

    def setUp(self):
        """Set up manager."""
        self.manager = SteeringManager()
        self.entity = GameEntity(
            id=1,
            position=Vec2(0, 0),
            velocity=Vec2(1, 0),
            faction="player",
        )

    def test_single_behavior(self):
        """Test manager with single behavior."""
        seek = Seek(Vec2(10, 0))
        self.manager.add_behavior(seek, weight=1.0)

        force = self.manager.calculate(self.entity)

        self.assertGreater(force.magnitude(), 0)

    def test_blended_behaviors(self):
        """Test manager blending multiple behaviors."""
        seek = Seek(Vec2(10, 0), max_force=5.0)
        flee = Flee(Vec2(-10, 0), max_force=5.0, panic_distance=20.0)

        self.manager.add_behavior(seek, weight=1.0)
        self.manager.add_behavior(flee, weight=1.0)

        force = self.manager.calculate(self.entity)

        # Should have blended force
        self.assertIsNotNone(force)

    def test_behavior_weight(self):
        """Test behavior weighting."""
        strong_seek = Seek(Vec2(10, 0), max_force=10.0)
        weak_flee = Flee(Vec2(-10, 0), max_force=10.0, panic_distance=20.0)

        self.manager.add_behavior(strong_seek, weight=2.0)
        self.manager.add_behavior(weak_flee, weight=0.5)

        force = self.manager.calculate(self.entity)

        # Should be dominated by seek
        self.assertGreater(force.x, 0)

    def test_entity_update(self):
        """Test updating entity with steering."""
        seek = Seek(Vec2(10, 0))
        self.manager.add_behavior(seek, weight=1.0)

        initial_pos = self.entity.position
        self.manager.update_entity(self.entity, delta_time=0.1, max_speed=10.0)

        # Entity should have moved
        self.assertNotEqual(self.entity.position, initial_pos)

    def test_max_speed_clamping(self):
        """Test velocity clamping by max speed."""
        seek = Seek(Vec2(100, 0), max_force=100.0)
        self.manager.add_behavior(seek, weight=1.0)

        self.manager.update_entity(self.entity, delta_time=0.1, max_speed=5.0)

        # Velocity should not exceed max_speed
        self.assertLessEqual(self.entity.velocity.magnitude(), 5.0)


class TestSteeringOutput(unittest.TestCase):
    """Test SteeringOutput dataclass."""

    def test_output_creation(self):
        """Test creating output."""
        force = Vec2(5, 0)
        output = SteeringOutput(force=force, is_active=True)

        self.assertEqual(output.force, force)
        self.assertTrue(output.is_active)

    def test_output_inactive(self):
        """Test inactive output."""
        output = SteeringOutput(Vec2(0, 0), is_active=False)

        self.assertFalse(output.is_active)
        self.assertEqual(output.force.magnitude(), 0)


if __name__ == "__main__":
    unittest.main()
