"""Prompt-contract tests that do not classify user or assistant prose."""

import unittest


class TestHonestyContractInPrompts(unittest.TestCase):
    def test_execution_prompt_has_honesty_contract(self) -> None:
        from thomas.agent.prompt_templates import SYSTEM_PROMPT

        self.assertIn("<honesty_contract>", SYSTEM_PROMPT)
        self.assertIn("NEVER claim", SYSTEM_PROMPT)
        self.assertIn("NEVER fabricate", SYSTEM_PROMPT)

    def test_low_intent_prompt_has_honesty_contract(self) -> None:
        from thomas.agent.prompt_templates import LOW_INTENT_SYSTEM_PROMPT

        self.assertIn("<honesty_contract>", LOW_INTENT_SYSTEM_PROMPT)
        self.assertIn("Never claim", LOW_INTENT_SYSTEM_PROMPT)

    def test_built_prompt_has_honesty(self) -> None:
        from thomas.agent.prompt_templates import build_default_system_prompt

        prompt = build_default_system_prompt(cwd="/", platform="linux", model_name="m", model_id="m")
        self.assertIn("honesty_contract", prompt)


class TestIdentityIntegrity(unittest.TestCase):
    def test_identity_owns_honest_failure_instructions(self) -> None:
        from thomas.agent.prompt_templates import _IDENTITY

        self.assertIn("Honest", _IDENTITY)
        self.assertIn("I don't know", _IDENTITY)
        self.assertIn("I messed up", _IDENTITY)


class TestDirectOrderEnforcement(unittest.TestCase):
    def test_priority_order_starts_with_user_request(self) -> None:
        from thomas.agent.prompt_templates import SYSTEM_PROMPT

        section = SYSTEM_PROMPT.split("<priority_order>")[1].split("</priority_order>")[0]
        self.assertIn("Follow the user's direct request", section)


if __name__ == "__main__":
    unittest.main()
