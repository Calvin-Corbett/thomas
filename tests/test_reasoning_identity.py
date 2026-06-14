"""Guard test for Thomas's identity law (Calvin, 2026-06-14).

Thomas is ONLY a chatbot: he talks, may read to stay aware, and never does work
himself — and there are no modes/switches. This locks the system prompt so a
future change can't silently soften the identity. See memory:
thomas-chatbot-only-no-modes-law.
"""

import unittest

from thomas.marketplace.specialists.reasoning import THOMAS_CHATBOT_SYSTEM_PROMPT


class TestThomasIdentity(unittest.TestCase):
    def test_declares_chatbot_only(self):
        low = THOMAS_CHATBOT_SYSTEM_PROMPT.lower()
        self.assertIn("chatbot", low)
        self.assertIn("your entire job", low)

    def test_states_cannot_do_work_or_plan(self):
        low = THOMAS_CHATBOT_SYSTEM_PROMPT.lower()
        self.assertIn("cannot build", low)
        # He does not plan/design/architect the work either — that's task-manager work.
        self.assertIn("architect the work", low)
        # By design, not an apology-worthy limitation.
        self.assertIn("by design", low)

    def test_allows_read_to_inform_and_report(self):
        low = THOMAS_CHATBOT_SYSTEM_PROMPT.lower()
        self.assertIn("read", low)
        # He reads state and reports back ("how's the evolve loop going?").
        self.assertIn("evolve loop", low)

    def test_assistant_framing(self):
        self.assertIn("assistant", THOMAS_CHATBOT_SYSTEM_PROMPT.lower())

    def test_work_is_handed_to_task_manager(self):
        low = THOMAS_CHATBOT_SYSTEM_PROMPT.lower()
        self.assertIn("task manager", low)

    def test_identity_is_not_toggleable_but_autonomy_stays(self):
        low = THOMAS_CHATBOT_SYSTEM_PROMPT.lower()
        # One canonical identity, no alternative version (or an agent picks the wrong one).
        self.assertIn("no other mode for you", low)
        self.assertIn("no setting changes it", low)
        # Autonomy levels are explicitly preserved (they don't change who he is).
        self.assertIn("autonomy levels", low)

    def test_forbids_fake_completion(self):
        low = THOMAS_CHATBOT_SYSTEM_PROMPT.lower()
        self.assertIn("never claim", low)

    def test_forbids_claiming_work_started_and_offers_instead(self):
        # The chat agent must not assert work began ("I'll get that started" /
        # "a task card has been created") when it can't know that — it offers to
        # hand off instead. Guards the live "logic doesn't add up" dishonesty.
        low = THOMAS_CHATBOT_SYSTEM_PROMPT.lower()
        self.assertIn("a task card has been created", low)  # named as a forbidden phrase
        self.assertIn("offer to hand it to the task manager", low)


if __name__ == "__main__":
    unittest.main()
