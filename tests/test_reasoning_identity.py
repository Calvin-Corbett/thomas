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
        # Positive framing (Calvin, 2026-06-26: "say your role, not what you can't do"):
        # he ASSISTS and hands the real work off; he doesn't do the hands-on building.
        self.assertIn("your entire job", low)
        self.assertIn("you assist the user", low)
        self.assertIn("do the hands-on building inside this chat", low)

    def test_states_cannot_do_work_or_plan(self):
        low = THOMAS_CHATBOT_SYSTEM_PROMPT.lower()
        # He does not do the hands-on work...
        self.assertIn("do the hands-on building inside this chat", low)
        # ...nor scope/plan/design it — that's the worker's job (positive framing).
        self.assertIn("you don't scope, plan, or design the work yourself", low)

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
        # The chat agent must not assert work began ("on it" / "I've handed that off")
        # when it never called send_task — that's a false claim. Guards the live
        # "logic doesn't add up" dishonesty (positive framing, 2026-06-26).
        low = THOMAS_CHATBOT_SYSTEM_PROMPT.lower()
        self.assertIn("without calling send_task does nothing", low)
        self.assertIn("false claim", low)
        self.assertIn("never tell the user you handed something off unless you actually called the tool", low)


if __name__ == "__main__":
    unittest.main()
