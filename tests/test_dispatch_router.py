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

    def test_memory_instruction_with_smoke_test_stays_conversational(self):
        decision = should_dispatch(
            "Memory smoke test: remember that the temporary code phrase is BLUE CEDAR 936. Reply with exactly: stored"
        )
        self.assertEqual(decision.action, "casual")
        self.assertEqual(decision.reason, "memory_instruction")

    def test_direct_exact_reply_stays_conversational(self):
        decision = should_dispatch("Reply with exactly: stored")
        self.assertEqual(decision.action, "casual")

    def test_exact_file_creation_still_dispatches(self):
        decision = should_dispatch("Create runtime/proof.txt containing exactly PROOF_OK")
        self.assertEqual(decision.action, "dispatch")

    def test_memory_recall_question_stays_conversational(self):
        decision = should_dispatch(
            "What was the temporary code phrase for this live QA run? Reply with only the phrase."
        )
        self.assertEqual(decision.action, "casual")
        self.assertEqual(decision.reason, "question_prompt")

    def test_explicit_repo_file_question_still_dispatches(self):
        decision = should_dispatch("What are three top-level files in the current repo?")
        self.assertEqual(decision.action, "dispatch")

    def test_status_followup_with_active_task_stays_conversational(self):
        decision = should_dispatch(
            "how's that going?",
            active_tasks=[{"state": "executing", "summary": "Implementing the plan"}],
        )
        self.assertEqual(decision.action, "casual")


if __name__ == "__main__":
    unittest.main()
