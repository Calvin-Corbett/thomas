"""Worker control-protocol text must not reach the person who asked.

Live incident, 2026-07-24: a request for "a one page guide explaining what a
401k is, as a PDF I can print and give to my employees" produced a good
two-page PDF, and reported it in chat as:

    Created 401k_employee_guide.pdf. why_blocked: The workspace does not
    contain scripts/forge/gates/monolith_guard.py, and the available tools
    provide file operations only, with no shell or process-execution
    capability for running tests or Python scripts.
"""

from __future__ import annotations

import unittest

from thomas.core.task_bot_runtime import _user_facing_summary


class UserFacingSummaryTests(unittest.TestCase):
    def test_keeps_the_human_sentence_and_drops_the_protocol(self):
        summary = (
            "Created 401k_employee_guide.pdf. why_blocked: The workspace does not "
            "contain scripts/forge/gates/monolith_guard.py, and the available tools "
            "provide file operations only."
        )
        self.assertEqual(_user_facing_summary(summary), "Created 401k_employee_guide.pdf")

    def test_ordinary_summaries_are_untouched(self):
        for summary in (
            "Reviewed the live chart and delivered chart.pdf with backing data.",
            "Done - the report is ready to print.",
            "Created snake.html.",
        ):
            self.assertEqual(_user_facing_summary(summary), summary)

    def test_every_protocol_field_is_recognised(self):
        for field in ("what_failed", "what_was_tried", "why_blocked", "GIVE_UP"):
            with self.subTest(field=field):
                self.assertEqual(
                    _user_facing_summary(f"Built the thing. {field}: internal detail here"),
                    "Built the thing",
                )

    def test_a_summary_that_merely_mentions_a_protocol_word_is_left_alone(self):
        """Matching the bare token anywhere turned "Added a give_up flag to the
        retry loop" into "Added a". The protocol always writes a labelled field
        or the marker alone on its line, so match that shape, not the word."""
        for summary in (
            "Added a give_up flag to the retry loop",
            "Refactored why_blocked handling in the parser",
            "Documented what_failed semantics for the team",
        ):
            with self.subTest(summary=summary):
                self.assertEqual(_user_facing_summary(summary), summary)

    def test_a_pure_protocol_message_yields_nothing_to_show(self):
        """Callers substitute their own wording rather than print the protocol."""
        summary = "GIVE_UP\nwhat_failed: tests\nwhat_was_tried: retry\nwhy_blocked: no shell"
        self.assertEqual(_user_facing_summary(summary), "")

    def test_matching_is_case_insensitive(self):
        self.assertEqual(_user_facing_summary("Made it. WHY_BLOCKED: nope"), "Made it")


if __name__ == "__main__":
    unittest.main()
