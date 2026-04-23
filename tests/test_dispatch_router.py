import unittest

from thomas.agent.dispatch import should_dispatch


class TestDispatchRouter(unittest.TestCase):
    def test_exploratory_planning_stays_conversational(self):
        decision = should_dispatch("let's think through this and plan how it should work")
        self.assertEqual(decision.action, "casual")

    def test_explicit_implementation_request_dispatches(self):
        decision = should_dispatch("please implement this plan")
        self.assertEqual(decision.action, "dispatch")

    def test_explicit_file_tool_request_dispatches(self):
        decision = should_dispatch("Use your file tools and name three top-level files in the current repo.")
        self.assertEqual(decision.action, "dispatch")

    def test_background_delegation_request_dispatches(self):
        decision = should_dispatch("answer now and delegate the rest in the background")
        self.assertEqual(decision.action, "dispatch")

    def test_subagent_request_dispatches(self):
        decision = should_dispatch("Spawn exactly three real sub-agents now and keep the response short.")
        self.assertEqual(decision.action, "dispatch")

    def test_status_followup_with_active_task_stays_conversational(self):
        decision = should_dispatch(
            "how's that going?",
            active_tasks=[{"state": "executing", "summary": "Implementing the plan"}],
        )
        self.assertEqual(decision.action, "casual")

    def test_history_recall_prompt_stays_conversational(self):
        decision = should_dispatch("What were the two things I asked right before this?")
        self.assertEqual(decision.action, "casual")

    def test_remember_this_prompt_stays_conversational(self):
        decision = should_dispatch(
            "Remember this: I'm making a simple vegetarian meal plan for a friend training for a half marathon."
        )
        self.assertEqual(decision.action, "casual")

    def test_inline_chat_reply_request_stays_conversational(self):
        decision = should_dispatch("Give me a 2-day sample meal plan right here in chat.")
        self.assertEqual(decision.action, "casual")

    def test_artifact_fix_followup_dispatches(self):
        decision = should_dispatch(
            "the controls feel slow and the level doesnt advance after i win",
            recent_messages=[
                {"role": "assistant", "content": "I built the project in D:\\Desktop\\DemoProject. Open that folder to try it."}
            ],
        )
        self.assertEqual(decision.action, "dispatch")


if __name__ == "__main__":
    unittest.main()
