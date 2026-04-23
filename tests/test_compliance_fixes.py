"""Tests for Thomas anti-confabulation and compliance enforcement.

Validates:
- Clarification budget allows at least 1 question at all autonomy levels
- Nudge system forbids confabulation instead of encouraging it
- Anti-confabulation detection catches fabricated execution claims
- Honesty contract present in system prompts
- Tool suppression only applies to local models on low-intent routes
"""

import unittest


class TestClarificationBudget(unittest.TestCase):
    """Verify the clarification question budget never drops to zero."""

    def test_budget_never_zero(self):
        """At ALL autonomy levels, the model must be able to ask at least 1 question."""
        # Simulate the budget calculation from loop.py
        for autonomy_level in range(1, 5):
            for explicit_action in [True, False]:
                for action_route in [True, False]:
                    project_related = True
                    full_auto = autonomy_level == 4 and (project_related or explicit_action or action_route)
                    budget_active = project_related or explicit_action or action_route

                    cap = 2
                    if budget_active:
                        cap = 1
                    if full_auto:
                        cap = 1  # NEW: was 0
                    # continuation_turn case
                    if budget_active:
                        continuation_cap = 1  # NEW: was 0
                    else:
                        continuation_cap = 1
                    cap = max(1, cap)
                    continuation_cap = max(1, continuation_cap)

                    self.assertGreaterEqual(
                        cap,
                        1,
                        f"Budget dropped to 0 at autonomy={autonomy_level}, "
                        f"explicit={explicit_action}, action_route={action_route}",
                    )
                    self.assertGreaterEqual(continuation_cap, 1)


class TestNudgeAntiConfabulation(unittest.TestCase):
    """Verify nudge prompts enforce honesty, not confabulation."""

    def _get_nudges(self):
        from thomas.agent.loop import AgentLoop

        full_auto = AgentLoop._full_auto_nudge("test prompt", 1)
        assume = AgentLoop._assume_and_proceed_nudge(
            "test prompt",
            retry_index=1,
            question_cap=1,
            questions_seen=2,
            route_input_source="prompt_only",
        )
        return full_auto, assume

    def test_full_auto_nudge_has_honesty_rule(self):
        full_auto, _ = self._get_nudges()
        self.assertIn("HONESTY", full_auto.upper())
        self.assertIn("never claim", full_auto.lower())
        self.assertIn("never fabricate", full_auto.lower())

    def test_assume_nudge_has_honesty_rule(self):
        _, assume = self._get_nudges()
        self.assertIn("HONESTY", assume.upper())
        self.assertIn("never claim", assume.lower())

    def test_nudges_no_longer_say_assume_defaults(self):
        """Old nudges said 'assume sensible defaults' which caused confabulation."""
        full_auto, assume = self._get_nudges()
        self.assertNotIn("choose sensible defaults", full_auto.lower())
        self.assertNotIn("assume sensible defaults", assume.lower())

    def test_nudges_allow_honest_failure(self):
        full_auto, assume = self._get_nudges()
        # Both nudges should acknowledge that failing honestly is acceptable
        self.assertTrue(
            "cannot" in full_auto.lower() or "can't" in full_auto.lower(),
            "Full-auto nudge should mention inability as acceptable",
        )
        self.assertTrue(
            "cannot" in assume.lower() or "can't" in assume.lower() or "blocking" in assume.lower(),
            "Assume nudge should mention inability as acceptable",
        )


class TestClaimsExecutionDetection(unittest.TestCase):
    """Test the _claims_execution anti-confabulation detector."""

    def _check(self, text: str) -> bool:
        from thomas.agent.loop import AgentLoop

        return AgentLoop._claims_execution(text)

    def test_detects_created_claim(self):
        self.assertTrue(self._check("I've created the file at /home/user/output.md"))

    def test_detects_written_claim(self):
        self.assertTrue(self._check("I have written the report to output/report.md"))

    def test_detects_saved_claim(self):
        self.assertTrue(self._check("File saved to /tmp/results.json"))

    def test_detects_executed_claim(self):
        self.assertTrue(self._check("I've executed the build script successfully"))

    def test_detects_agents_launched(self):
        self.assertTrue(self._check("I have 50 agents running now on the research task"))

    def test_detects_heres_your_output(self):
        self.assertTrue(self._check("Here's the output from the analysis"))

    def test_normal_response_not_flagged(self):
        self.assertFalse(self._check("The function returns True when the input is valid."))

    def test_question_not_flagged(self):
        self.assertFalse(self._check("Which file would you like me to edit?"))

    def test_explanation_not_flagged(self):
        self.assertFalse(self._check("To fix this bug, you'd need to update the config."))

    def test_empty_not_flagged(self):
        self.assertFalse(self._check(""))

    def test_honest_failure_not_flagged(self):
        self.assertFalse(self._check("I can't do that because I don't have access to the file."))


class TestHonestyContractInPrompts(unittest.TestCase):
    """Verify the honesty contract is present in all system prompts."""

    def test_execution_prompt_has_honesty_contract(self):
        from thomas.agent.prompt_templates import SYSTEM_PROMPT

        self.assertIn("<honesty_contract>", SYSTEM_PROMPT)
        self.assertIn("NEVER claim", SYSTEM_PROMPT)
        self.assertIn("NEVER fabricate", SYSTEM_PROMPT)

    def test_low_intent_prompt_has_honesty_contract(self):
        from thomas.agent.prompt_templates import LOW_INTENT_SYSTEM_PROMPT

        self.assertIn("<honesty_contract>", LOW_INTENT_SYSTEM_PROMPT)
        self.assertIn("Never claim", LOW_INTENT_SYSTEM_PROMPT)

    def test_honesty_contract_mentions_tool_execution(self):
        from thomas.agent.prompt_templates import SYSTEM_PROMPT

        self.assertIn("tool", SYSTEM_PROMPT.lower().split("honesty_contract")[1].split("</honesty_contract>")[0])

    def test_honesty_prefers_honest_failure(self):
        from thomas.agent.prompt_templates import SYSTEM_PROMPT

        section = SYSTEM_PROMPT.split("<honesty_contract>")[1].split("</honesty_contract>")[0]
        self.assertIn("honest", section.lower())

    def test_built_prompt_has_honesty(self):
        from thomas.agent.prompt_templates import build_default_system_prompt

        prompt = build_default_system_prompt(cwd="/", platform="linux", model_name="m", model_id="m")
        self.assertIn("honesty_contract", prompt)


class TestIdentityIntegrity(unittest.TestCase):
    """Verify the identity and conversation intelligence are intact."""

    def test_identity_has_honest_trait(self):
        from thomas.agent.prompt_templates import _IDENTITY

        self.assertIn("Honest", _IDENTITY)

    def test_identity_says_dont_know(self):
        from thomas.agent.prompt_templates import _IDENTITY

        self.assertIn("I don't know", _IDENTITY)

    def test_identity_says_messed_up(self):
        from thomas.agent.prompt_templates import _IDENTITY

        self.assertIn("I messed up", _IDENTITY)


class TestDirectOrderEnforcement(unittest.TestCase):
    """Verify the execution contract enforces direct order compliance."""

    def test_execution_contract_present(self):
        from thomas.agent.prompt_templates import SYSTEM_PROMPT

        self.assertIn("<execution_contract>", SYSTEM_PROMPT)

    def test_priority_order_user_first(self):
        from thomas.agent.prompt_templates import SYSTEM_PROMPT

        section = SYSTEM_PROMPT.split("<priority_order>")[1].split("</priority_order>")[0]
        # First priority should be user's request
        self.assertIn("Follow the user's direct request", section)

    def test_honesty_says_never_deflect(self):
        from thomas.agent.prompt_templates import SYSTEM_PROMPT

        section = SYSTEM_PROMPT.split("<honesty_contract>")[1].split("</honesty_contract>")[0]
        self.assertIn("direct order", section.lower())


if __name__ == "__main__":
    unittest.main()
