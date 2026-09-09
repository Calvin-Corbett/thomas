"""Tests for forwarding chat context into a background worker (handoff block)."""

import unittest

from thomas.server.chat_delegation import _handoff_block


class TestHandoffBlock(unittest.TestCase):
    def test_empty_when_no_messages(self):
        self.assertEqual(_handoff_block(None), "")
        self.assertEqual(_handoff_block([]), "")

    def test_formats_user_and_assistant_turns(self):
        msgs = [
            {"role": "user", "content": "Build me a landing page"},
            {"role": "assistant", "content": "Want me to hand that to the task manager?"},
            {"role": "user", "content": "yes and make it blue"},
        ]
        block = _handoff_block(msgs)
        self.assertIn("recent conversation", block)
        self.assertIn("User: Build me a landing page", block)
        self.assertIn("Thomas: Want me to hand that", block)
        self.assertIn("make it blue", block)

    def test_limits_to_last_n_turns(self):
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        block = _handoff_block(msgs, limit=3)
        self.assertIn("msg 19", block)
        self.assertNotIn("msg 0", block)

    def test_skips_non_dialogue_roles(self):
        msgs = [
            {"role": "system", "content": "orchestrator routing prompt"},
            {"role": "user", "content": "do the thing"},
        ]
        block = _handoff_block(msgs)
        self.assertNotIn("orchestrator routing", block)
        self.assertIn("do the thing", block)


if __name__ == "__main__":
    unittest.main()
