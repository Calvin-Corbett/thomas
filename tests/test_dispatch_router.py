import unittest

from thomas.agent.dispatch import should_dispatch


class TestDispatchRouter(unittest.TestCase):
    def test_exploratory_planning_stays_conversational(self):
        decision = should_dispatch("let's think through this and plan how it should work")
        self.assertEqual(decision.action, "casual")

    def test_explicit_implementation_request_dispatches(self):
        decision = should_dispatch("please implement this plan")
        self.assertEqual(decision.action, "dispatch")

    def test_status_followup_with_active_task_stays_conversational(self):
        decision = should_dispatch(
            "how's that going?",
            active_tasks=[{"state": "executing", "summary": "Implementing the plan"}],
        )
        self.assertEqual(decision.action, "casual")


if __name__ == "__main__":
    unittest.main()
