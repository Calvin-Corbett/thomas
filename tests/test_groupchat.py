"""Tests for thomas.groupchat module."""
import unittest

from thomas.groupchat.types import GroupChatConfig, GroupMessage, ParticipantInfo, SpeakerSelectionMode
from thomas.groupchat.participant import ChatParticipant, UserParticipant
from thomas.groupchat.selector import SpeakerSelector, SelectionHistory
from thomas.groupchat.chat import GroupChat
from thomas.groupchat.manager import GroupChatManager


class TestParticipant(unittest.TestCase):
    def test_create_participant(self):
        p = ChatParticipant(name="Alice", role="researcher", description="Research specialist", capabilities=["research", "analysis"])
        self.assertEqual(p.name, "Alice")
        self.assertEqual(p.role, "researcher")

    def test_can_handle(self):
        p = ChatParticipant(name="Alice", role="python developer", description="Codes in python", capabilities=["python", "coding", "debugging"])
        score = p.can_handle("help me write python code")
        self.assertGreater(score, 0)

    def test_get_introduction(self):
        p = ChatParticipant(name="Bob", role="designer", description="UI expert", capabilities=["design"])
        intro = p.get_introduction()
        self.assertIn("Bob", intro)

    def test_generate_response(self):
        p = ChatParticipant(name="Alice", role="assistant", description="Helper", capabilities=[])
        msgs = [GroupMessage(sender="User", content="Hello", round_num=1)]
        response = p.generate_response(msgs)
        self.assertIsInstance(response, str)
        self.assertGreater(len(response), 0)

    def test_user_participant_with_callback(self):
        p = UserParticipant(name="Human", role="user", description="Human user", capabilities=[], callback=lambda prompt: "Human says hi")
        msgs = [GroupMessage(sender="Bot", content="Hello human", round_num=1)]
        response = p.generate_response(msgs)
        self.assertEqual(response, "Human says hi")


class TestSelector(unittest.TestCase):
    def setUp(self):
        self.participants = [
            ChatParticipant(name="Alice", role="coder", description="Codes", capabilities=["python"]),
            ChatParticipant(name="Bob", role="writer", description="Writes", capabilities=["writing"]),
            ChatParticipant(name="Charlie", role="tester", description="Tests", capabilities=["testing"]),
        ]
        self.selector = SpeakerSelector()
        self.config = GroupChatConfig()

    def test_round_robin(self):
        messages = []
        selected = self.selector.select(self.participants, messages, SpeakerSelectionMode.ROUND_ROBIN, self.config)
        self.assertIn(selected, self.participants)

    def test_random(self):
        messages = []
        selected = self.selector.select(self.participants, messages, SpeakerSelectionMode.RANDOM, self.config)
        self.assertIn(selected, self.participants)

    def test_auto_select(self):
        messages = [GroupMessage(sender="User", content="I need help with python code", round_num=1)]
        selected = self.selector.select(self.participants, messages, SpeakerSelectionMode.AUTO, self.config)
        self.assertIn(selected, self.participants)


class TestSelectionHistory(unittest.TestCase):
    def test_track_selections(self):
        history = SelectionHistory()
        history.record_selection("Alice")
        history.record_selection("Bob")
        history.record_selection("Alice")
        counts = history.get_statistics()
        self.assertEqual(counts["Alice"], 2)
        self.assertEqual(counts["Bob"], 1)


class TestGroupChat(unittest.TestCase):
    def setUp(self):
        self.p1 = ChatParticipant(name="Alice", role="assistant", description="Helper", capabilities=["general"])
        self.p2 = ChatParticipant(name="Bob", role="analyst", description="Analyzer", capabilities=["analysis"])

    def test_add_participant(self):
        chat = GroupChat(name="test_chat", config=GroupChatConfig(max_rounds=3))
        chat.add_participant(self.p1)
        chat.add_participant(self.p2)
        self.assertEqual(len(chat.participants), 2)

    def test_run(self):
        config = GroupChatConfig(max_rounds=2, send_introductions=False)
        chat = GroupChat(name="test_run_chat", config=config)
        chat.add_participant(self.p1)
        chat.add_participant(self.p2)
        messages = chat.run("Let's discuss AI")
        self.assertIsInstance(messages, list)
        self.assertGreater(len(messages), 0)

    def test_termination(self):
        config = GroupChatConfig(max_rounds=1, send_introductions=False)
        chat = GroupChat(name="test_termination_chat", config=config)
        chat.add_participant(self.p1)
        messages = chat.run("Quick chat")
        self.assertIsInstance(messages, list)

    def test_get_transcript(self):
        config = GroupChatConfig(max_rounds=1, send_introductions=False)
        chat = GroupChat(name="test_transcript_chat", config=config)
        chat.add_participant(self.p1)
        chat.run("Test")
        transcript = chat.get_transcript()
        self.assertIsInstance(transcript, str)

    def test_pause_resume(self):
        chat = GroupChat(name="test_pause_chat", config=GroupChatConfig(max_rounds=1, send_introductions=False))
        chat.add_participant(self.p1)
        chat.pause()
        self.assertEqual(chat.state, "paused")
        # Resume will run additional rounds and complete the chat
        messages = chat.resume()
        # State will be "completed" after resume runs the remaining rounds
        self.assertIsInstance(messages, list)


class TestGroupChatManager(unittest.TestCase):
    def test_create_chat(self):
        mgr = GroupChatManager()
        chat = mgr.create_chat("test_chat")
        self.assertIsNotNone(chat)

    def test_list_active(self):
        mgr = GroupChatManager()
        chat1 = mgr.create_chat("chat1")
        chat2 = mgr.create_chat("chat2")
        # Mark chats as active (normally happens when run() is called)
        chat1.state = "active"
        chat2.state = "active"
        active = mgr.list_active()
        self.assertEqual(len(active), 2)

    def test_stats(self):
        mgr = GroupChatManager()
        mgr.create_chat("s1")
        stats = mgr.stats()
        self.assertEqual(stats["total_chats"], 1)

    def test_create_debate(self):
        mgr = GroupChatManager()
        participants = [
            ChatParticipant(name="Pro", role="advocate", description="For", capabilities=[]),
            ChatParticipant(name="Con", role="critic", description="Against", capabilities=[]),
        ]
        chat = mgr.create_debate("debate1", "AI ethics", participants)
        self.assertIsNotNone(chat)


if __name__ == "__main__":
    unittest.main()
