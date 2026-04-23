"""
Tests for utility-based AI system.

Tests utility curves, decision scoring, action selection, and composition modes.
"""

import unittest

from thomas.marketplace.game_ai._types import Blackboard
from thomas.marketplace.game_ai.utility_ai import (
    Decision,
    ExponentialCurve,
    InverseCurve,
    LinearCurve,
    LogisticCurve,
    StepCurve,
    UtilityAI,
    create_response_curve,
)


class TestUtilityCurves(unittest.TestCase):
    """Test utility curve types."""

    def test_linear_curve(self):
        """Test linear curve."""
        curve = LinearCurve(0, 10)

        self.assertAlmostEqual(curve.evaluate(0), 0.0)
        self.assertAlmostEqual(curve.evaluate(5), 0.5)
        self.assertAlmostEqual(curve.evaluate(10), 1.0)

    def test_linear_curve_inverted(self):
        """Test inverted linear curve."""
        curve = LinearCurve(0, 10, invert=True)

        self.assertAlmostEqual(curve.evaluate(0), 1.0)
        self.assertAlmostEqual(curve.evaluate(5), 0.5)
        self.assertAlmostEqual(curve.evaluate(10), 0.0)

    def test_linear_curve_clamping(self):
        """Test linear curve clamps values."""
        curve = LinearCurve(0, 10)

        # Below min
        self.assertAlmostEqual(curve.evaluate(-5), 0.0)

        # Above max
        self.assertAlmostEqual(curve.evaluate(15), 1.0)

    def test_exponential_curve(self):
        """Test exponential curve."""
        curve = ExponentialCurve(exponent=2.0)

        self.assertAlmostEqual(curve.evaluate(0.0), 0.0)
        self.assertAlmostEqual(curve.evaluate(0.5), 0.25)
        self.assertAlmostEqual(curve.evaluate(1.0), 1.0)

    def test_exponential_curve_steep(self):
        """Test exponential curve with high exponent."""
        curve = ExponentialCurve(exponent=4.0)

        # Higher exponent = steeper curve
        value_at_half = curve.evaluate(0.5)
        self.assertLess(value_at_half, 0.25)

    def test_logistic_curve(self):
        """Test logistic (S-curve)."""
        curve = LogisticCurve(midpoint=0.5, steepness=1.0)

        # Below midpoint
        self.assertLess(curve.evaluate(0.0), 0.5)

        # At midpoint
        self.assertAlmostEqual(curve.evaluate(0.5), 0.5, places=1)

        # Above midpoint
        self.assertGreater(curve.evaluate(1.0), 0.5)

    def test_step_curve(self):
        """Test step curve."""
        curve = StepCurve(threshold=0.5)

        self.assertEqual(curve.evaluate(0.0), 0.0)
        self.assertEqual(curve.evaluate(0.49), 0.0)
        self.assertEqual(curve.evaluate(0.5), 1.0)
        self.assertEqual(curve.evaluate(1.0), 1.0)

    def test_step_curve_inverted(self):
        """Test inverted step curve."""
        curve = StepCurve(threshold=0.5, invert=True)

        self.assertEqual(curve.evaluate(0.0), 1.0)
        self.assertEqual(curve.evaluate(0.5), 0.0)

    def test_inverse_curve(self):
        """Test inverse curve."""
        curve = InverseCurve(offset=1.0)

        self.assertGreater(curve.evaluate(0.0), 0.5)
        self.assertAlmostEqual(curve.evaluate(1.0), 0.5, places=1)


class TestDecision(unittest.TestCase):
    """Test Decision class."""

    def test_decision_creation(self):
        """Test creating a decision."""
        decision = Decision(name="attack")

        self.assertEqual(decision.name, "attack")
        self.assertEqual(len(decision.utility_functions), 0)

    def test_decision_add_consideration(self):
        """Test adding consideration to decision."""
        decision = Decision(name="attack")

        decision.add_consideration(
            "enemy_visible",
            lambda bb: 1.0 if bb.get("enemy_visible") else 0.0,
            weight=2.0,
        )

        self.assertEqual(len(decision.utility_functions), 1)
        self.assertEqual(decision.weights["enemy_visible"], 2.0)

    def test_decision_composition_modes(self):
        """Test decision composition modes."""
        decision = Decision(name="test", composition_mode="multiply")
        self.assertEqual(decision.composition_mode, "multiply")

        decision2 = Decision(name="test", composition_mode="average")
        self.assertEqual(decision2.composition_mode, "average")


class TestUtilityAI(unittest.TestCase):
    """Test UtilityAI system."""

    def setUp(self):
        """Set up utility AI."""
        self.ai = UtilityAI()

        # Attack decision
        attack = Decision(name="attack", composition_mode="multiply")
        attack.add_consideration(
            "enemy_visible",
            lambda bb: 1.0 if bb.get("enemy_visible") else 0.0,
            weight=1.0,
        )
        attack.add_consideration(
            "has_ammo",
            lambda bb: 1.0 if bb.get("has_ammo") else 0.0,
            weight=1.0,
        )

        # Flee decision
        flee = Decision(name="flee", composition_mode="multiply")
        flee.add_consideration(
            "low_health",
            lambda bb: min(1.0, 1.0 - bb.get("health", 100) / 100),
            weight=1.0,
        )

        self.ai.register_decision(attack)
        self.ai.register_decision(flee)

    def test_score_decisions(self):
        """Test scoring all decisions."""
        blackboard: Blackboard = {
            "enemy_visible": True,
            "has_ammo": True,
            "health": 100,
        }

        scores = self.ai.score_decisions(blackboard)

        self.assertEqual(len(scores), 2)
        # Attack should score higher
        attack_score = next(s for s in scores if s.decision_name == "attack")
        flee_score = next(s for s in scores if s.decision_name == "flee")

        self.assertGreater(attack_score.utility, flee_score.utility)

    def test_choose_decision_highest(self):
        """Test choosing best decision."""
        blackboard: Blackboard = {
            "enemy_visible": True,
            "has_ammo": True,
            "health": 100,
        }

        choice = self.ai.choose_decision(blackboard, method="highest")

        self.assertEqual(choice, "attack")

    def test_choose_decision_low_health(self):
        """Test decision changes with health."""
        blackboard: Blackboard = {
            "enemy_visible": True,
            "has_ammo": False,
            "health": 10,
        }

        choice = self.ai.choose_decision(blackboard, method="highest")

        # Can't attack without ammo, should flee
        self.assertEqual(choice, "flee")

    def test_choose_decision_weighted_random(self):
        """Test weighted random selection."""
        blackboard: Blackboard = {
            "enemy_visible": True,
            "has_ammo": True,
            "health": 100,
        }

        # Run multiple times to test randomness
        choices = set()
        for _ in range(20):
            choice = self.ai.choose_decision(blackboard, method="weighted_random")
            choices.add(choice)

        # Should pick "attack" most often (it has higher utility)
        self.assertIn("attack", choices)

    def test_no_valid_decisions(self):
        """Test when no decisions are valid."""
        blackboard: Blackboard = {
            "enemy_visible": False,
            "has_ammo": False,
            "health": 0,
        }

        choice = self.ai.choose_decision(blackboard, method="highest")

        # With low scores, should still return something (highest of lowest)
        self.assertIsNotNone(choice)

    def test_last_scores(self):
        """Test getting last scores."""
        blackboard: Blackboard = {
            "enemy_visible": True,
            "has_ammo": True,
            "health": 100,
        }

        self.ai.score_decisions(blackboard)
        scores = self.ai.get_last_scores()

        self.assertIn("attack", scores)
        self.assertIn("flee", scores)

    def test_debug_print(self):
        """Test debug output."""
        blackboard: Blackboard = {
            "enemy_visible": True,
            "has_ammo": True,
            "health": 100,
        }

        self.ai.score_decisions(blackboard)
        debug_str = self.ai.debug_print_scores()

        self.assertIn("attack", debug_str)
        self.assertIn("Decision Scores", debug_str)


class TestCompositionModes(unittest.TestCase):
    """Test different composition modes."""

    def test_multiply_composition(self):
        """Test multiplicative composition."""
        ai = UtilityAI()

        decision = Decision(name="test", composition_mode="multiply")
        decision.add_consideration("a", lambda bb: 0.8, weight=1.0)
        decision.add_consideration("b", lambda bb: 0.5, weight=1.0)

        ai.register_decision(decision)
        scores = ai.score_decisions({})

        # 0.8 * 0.5 = 0.4
        self.assertAlmostEqual(scores[0].utility, 0.4)

    def test_average_composition(self):
        """Test average composition."""
        ai = UtilityAI()

        decision = Decision(name="test", composition_mode="average")
        decision.add_consideration("a", lambda bb: 0.8, weight=1.0)
        decision.add_consideration("b", lambda bb: 0.6, weight=1.0)

        ai.register_decision(decision)
        scores = ai.score_decisions({})

        # (0.8 + 0.6) / 2 = 0.7
        self.assertAlmostEqual(scores[0].utility, 0.7)

    def test_weighted_average(self):
        """Test weighted average composition."""
        ai = UtilityAI()

        decision = Decision(name="test", composition_mode="average")
        decision.add_consideration("a", lambda bb: 0.8, weight=2.0)
        decision.add_consideration("b", lambda bb: 0.6, weight=1.0)

        ai.register_decision(decision)
        scores = ai.score_decisions({})

        # (0.8*2 + 0.6*1) / 3 = 2.2/3 ≈ 0.733
        self.assertAlmostEqual(scores[0].utility, 2.2 / 3, places=2)

    def test_min_composition(self):
        """Test minimum composition."""
        ai = UtilityAI()

        decision = Decision(name="test", composition_mode="min")
        decision.add_consideration("a", lambda bb: 0.8, weight=1.0)
        decision.add_consideration("b", lambda bb: 0.3, weight=1.0)

        ai.register_decision(decision)
        scores = ai.score_decisions({})

        # min(0.8, 0.3) = 0.3
        self.assertAlmostEqual(scores[0].utility, 0.3)


class TestResponseCurves(unittest.TestCase):
    """Test response curve factory function."""

    def test_linear_response_curve(self):
        """Test creating linear response curve."""
        curve = create_response_curve((0, 10), curve_type="linear")

        self.assertAlmostEqual(curve(0), 0.0)
        self.assertAlmostEqual(curve(5), 0.5)
        self.assertAlmostEqual(curve(10), 1.0)

    def test_exponential_response_curve(self):
        """Test creating exponential response curve."""
        curve = create_response_curve((0, 1), curve_type="exponential", exponent=2.0)

        self.assertAlmostEqual(curve(0), 0.0)
        self.assertAlmostEqual(curve(1), 1.0)

    def test_logistic_response_curve(self):
        """Test creating logistic response curve."""
        curve = create_response_curve((0, 1), curve_type="logistic", steepness=2.0)

        # Should be S-shaped
        val_low = curve(0.2)
        val_mid = curve(0.5)
        val_high = curve(0.8)

        self.assertLess(val_low, val_mid)
        self.assertLess(val_mid, val_high)

    def test_step_response_curve(self):
        """Test creating step response curve."""
        curve = create_response_curve((0, 1), curve_type="step", threshold=0.5)

        self.assertEqual(curve(0.3), 0.0)
        self.assertEqual(curve(0.7), 1.0)


if __name__ == "__main__":
    unittest.main()
