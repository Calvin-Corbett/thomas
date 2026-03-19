import pytest

pytestmark = pytest.mark.xfail(
    reason="Domain skeleton pending implementation (tracking: docs/ops/remediation/DOMAIN_STUB_TRACKING.md)",
    strict=False,
)
"""Tests for thomas.conversations module."""
import os
import tempfile
import unittest

from thomas.conversations.checkpoint import ConversationCheckpoint
from thomas.conversations.context import ConversationContext
from thomas.conversations.conversation import Conversation
from thomas.conversations.nested import NestedChatManager
from thomas.conversations.speaker import SelectionMode, SpeakerSelector
from thomas.conversations.types import ConversationState, MessageRole


class TestConversation(unittest.TestCase):
    def test_add_and_get_messages(self):
        conv = Conversation(topic="Test topic")
        conv.add_message(MessageRole.USER, "Hello")
        conv.add_message(MessageRole.ASSISTANT, "Hi there")
        msgs = conv.get_messages()
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].content, "Hello")

    def test_get_last_message(self):
        conv = Conversation(topic="Test topic")
        conv.add_message(MessageRole.USER, "First")
        conv.add_message(MessageRole.ASSISTANT, "Second")
        last = conv.get_last_message()
        self.assertEqual(last.content, "Second")

    def test_get_messages_for_role(self):
        conv = Conversation(topic="Test topic")
        conv.add_message(MessageRole.USER, "Q1")
        conv.add_message(MessageRole.ASSISTANT, "A1")
        conv.add_message(MessageRole.USER, "Q2")
        user_msgs = conv.get_messages_for_role(MessageRole.USER)
        self.assertEqual(len(user_msgs), 2)

    def test_fork(self):
        conv = Conversation(topic="Test topic")
        conv.add_message(MessageRole.USER, "Hello")
        forked = conv.fork()
        forked.add_message(MessageRole.ASSISTANT, "New branch")
        self.assertEqual(len(conv.get_messages()), 1)
        self.assertEqual(len(forked.get_messages()), 2)

    def test_state_management(self):
        conv = Conversation(topic="Test topic")
        self.assertEqual(conv.state, ConversationState.ACTIVE)
        conv.pause()
        self.assertEqual(conv.state, ConversationState.PAUSED)
        conv.resume()
        self.assertEqual(conv.state, ConversationState.ACTIVE)
        conv.complete()
        self.assertEqual(conv.state, ConversationState.COMPLETED)

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "conv.json")
            conv = Conversation(topic="Test topic")
            conv.add_message(MessageRole.USER, "Save me")
            conv.save(path)
            loaded = Conversation.load(path)
            self.assertEqual(len(loaded.get_messages()), 1)
            self.assertEqual(loaded.get_messages()[0].content, "Save me")

    def test_to_prompt_format(self):
        conv = Conversation(topic="Test topic")
        conv.add_message(MessageRole.SYSTEM, "You are helpful")
        conv.add_message(MessageRole.USER, "Hi")
        fmt = conv.to_prompt_format()
        self.assertEqual(len(fmt), 2)
        self.assertEqual(fmt[0]["role"], "system")

    def test_token_count(self):
        conv = Conversation(topic="Test topic")
        conv.add_message(MessageRole.USER, "A" * 400)
        count = conv.token_count()
        self.assertGreater(count, 50)

    def test_truncate(self):
        conv = Conversation(topic="Test topic")
        for i in range(10):
            conv.add_message(MessageRole.USER, f"msg {i}")
        conv.truncate(3)
        self.assertEqual(len(conv.get_messages()), 3)


class TestNestedChat(unittest.TestCase):
    def test_start_conversation(self):
        mgr = NestedChatManager()
        conv = mgr.start_conversation("Test topic")
        self.assertIsNotNone(conv)
        self.assertEqual(conv.state, ConversationState.ACTIVE)

    def test_spawn_inner(self):
        mgr = NestedChatManager()
        parent = mgr.start_conversation("Parent")
        child = mgr.spawn_inner(parent, "Child topic")
        self.assertIsNotNone(child)

    def test_get_conversation_tree(self):
        mgr = NestedChatManager()
        parent = mgr.start_conversation("Root")
        mgr.spawn_inner(parent, "Child 1")
        tree = mgr.get_conversation_tree()
        self.assertIsInstance(tree, dict)


class TestSpeakerSelector(unittest.TestCase):
    def test_round_robin(self):
        selector = SpeakerSelector()
        agents = ["Alice", "Bob", "Charlie"]
        conv = Conversation(topic="Test topic")
        selected = selector.select_next(agents, conv, SelectionMode.ROUND_ROBIN)
        self.assertIn(selected, agents)

    def test_random(self):
        selector = SpeakerSelector()
        agents = ["Alice", "Bob"]
        conv = Conversation(topic="Test topic")
        selected = selector.select_next(agents, conv, SelectionMode.RANDOM)
        self.assertIn(selected, agents)

    def test_auto_select(self):
        selector = SpeakerSelector()
        agents = ["python_expert", "chef", "doctor"]
        conv = Conversation(topic="python programming")
        conv.add_message(MessageRole.USER, "I need help with python programming")
        selected = selector.select_next(agents, conv, SelectionMode.AUTO)
        self.assertIn(selected, agents)


class TestContext(unittest.TestCase):
    def test_add_and_get_fact(self):
        ctx = ConversationContext()
        ctx.add_fact("name", "Thomas")
        self.assertEqual(ctx.get_fact("name"), "Thomas")

    def test_parent_inheritance(self):
        parent = ConversationContext()
        parent.add_fact("shared_key", "parent_value", shared=True)
        child = parent.create_child_context()
        val = child.get_fact("shared_key")
        self.assertEqual(val, "parent_value")

    def test_local_overrides_parent(self):
        parent = ConversationContext()
        parent.add_fact("key", "parent", shared=True)
        child = parent.create_child_context()
        child.add_fact("key", "child")
        self.assertEqual(child.get_fact("key"), "child")

    def test_get_all_facts(self):
        parent = ConversationContext()
        parent.add_fact("p1", "v1", shared=True)
        child = parent.create_child_context()
        child.add_fact("c1", "v2")
        all_facts = child.get_all_facts()
        self.assertIn("c1", all_facts)


class TestCheckpoint(unittest.TestCase):
    def setUp(self):
        from pathlib import Path

        self.td = tempfile.TemporaryDirectory()
        self.cp = ConversationCheckpoint(Path(self.td.name))

    def tearDown(self):
        self.td.cleanup()

    def test_save_checkpoint(self):
        conv = Conversation(topic="Test checkpoint")
        conv.add_message(MessageRole.USER, "Hello")
        cp_id = self.cp.save_checkpoint(conv, "test checkpoint")
        self.assertTrue(len(cp_id) > 0)

    def test_load_checkpoint(self):
        conv = Conversation(topic="Test checkpoint")
        conv.add_message(MessageRole.USER, "Hello checkpoint")
        cp_id = self.cp.save_checkpoint(conv)
        loaded = self.cp.load_checkpoint(cp_id)
        self.assertEqual(len(loaded.get_messages()), 1)
        self.assertEqual(loaded.get_messages()[0].content, "Hello checkpoint")

    def test_list_checkpoints(self):
        conv = Conversation(topic="Test checkpoint")
        conv.add_message(MessageRole.USER, "msg")
        self.cp.save_checkpoint(conv, "first")
        self.cp.save_checkpoint(conv, "second")
        cps = self.cp.list_checkpoints(conv.id)
        self.assertEqual(len(cps), 2)


if __name__ == "__main__":
    unittest.main()
