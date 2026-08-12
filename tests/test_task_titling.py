"""Tests for task-card titling — real names, not prompt truncation."""

import unittest

from thomas.core.task_titling import derive_task_title, generate_task_title


class TestDeriveTaskTitle(unittest.TestCase):
    def test_strips_greeting_and_politeness_into_imperative(self):
        self.assertEqual(
            derive_task_title("hey thomas can you please build me a pac-man game"),
            "Build a pac-man game",
        )

    def test_keeps_existing_imperative(self):
        self.assertEqual(
            derive_task_title("Fix the login bug where the session times out"),
            "Fix the login bug where the session times out",
        )

    def test_truncates_long_asks_with_ellipsis(self):
        title = derive_task_title(
            "build a full inventory management dashboard with charts and exports and user roles and audit logs"
        )
        self.assertTrue(title.startswith("Build a full inventory management"))
        self.assertTrue(title.endswith("…"))
        self.assertLessEqual(len(title.split()), 10)

    def test_uses_first_clause_only(self):
        self.assertEqual(
            derive_task_title("Make a budget spreadsheet. It should also email me weekly."),
            "Make a budget spreadsheet",
        )

    def test_drops_indirect_object_pronoun(self):
        self.assertEqual(derive_task_title("make us a landing page"), "Make a landing page")

    def test_strips_help_me(self):
        # The most common non-engineer phrasing — surfaced by the persona sweep
        # (29% of titles kept "Help me ..." before this fix).
        self.assertEqual(
            derive_task_title("Help me make a printable birthday invitation"),
            "Make a printable birthday invitation",
        )
        self.assertEqual(derive_task_title("help me negotiate my salary"), "Negotiate my salary")

    def test_strips_im_statement_opener(self):
        self.assertEqual(
            derive_task_title("I'm starting an Etsy shop for handmade jewelry"),
            "Starting an Etsy shop for handmade jewelry",
        )

    def test_extracts_buried_imperative_clause(self):
        # Statement-then-request: the task is the imperative clause, not the lead-in.
        self.assertEqual(
            derive_task_title("I keep forgetting birthdays, set up a reminder a week before"),
            "Set up a reminder a week before",
        )
        self.assertTrue(
            derive_task_title("My computer is running slow, can you figure out what's wrong").startswith(
                "Figure out what's wrong"
            )
        )

    def test_truncated_title_does_not_end_on_article(self):
        title = derive_task_title("set up a small home network with a guest wifi and parental controls for the kids")
        self.assertTrue(title.endswith("…"))
        self.assertFalse(title.rstrip("…").rstrip().lower().endswith((" a", " the", " with", " for", " and")))

    def test_empty_prompt_is_safe(self):
        self.assertEqual(derive_task_title("   "), "New task")

    def test_not_a_raw_truncation(self):
        prompt = "hey can you please go ahead and " + "x" * 300
        title = derive_task_title(prompt)
        # The old behavior was prompt[:200]; the new title must not start with the
        # conversational filler the old truncation would have kept.
        self.assertFalse(title.lower().startswith("hey can you"))


class TestGenerateTaskTitle(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_to_heuristic_without_llm(self):
        self.assertEqual(
            await generate_task_title("please build me a snake game"),
            "Build a snake game",
        )

    async def test_uses_model_title_when_available(self):
        class _LLM:
            async def generate(self, _prompt):
                return "Build a Pac-Man browser game"

        self.assertEqual(
            await generate_task_title("hey make a pacman thing", llm=_LLM()),
            "Build a Pac-Man browser game",
        )

    async def test_rejects_junk_model_output_and_falls_back(self):
        class _LLM:
            async def generate(self, _prompt):
                return "Sure! Here is a title: " + "word " * 40

        # Model rambled instead of titling -> heuristic wins.
        self.assertEqual(
            await generate_task_title("build me a calculator app", llm=_LLM()),
            "Build a calculator app",
        )

    async def test_survives_model_exception(self):
        class _LLM:
            async def generate(self, _prompt):
                raise RuntimeError("model down")

        self.assertEqual(
            await generate_task_title("make a todo list app", llm=_LLM()),
            "Make a todo list app",
        )


if __name__ == "__main__":
    unittest.main()
