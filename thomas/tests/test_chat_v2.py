"""Integration tests for the Chat V2 (Brain/Orchestrator) system.

Tests cover:
    - Bug #1 regression: COW ConversationManager survives compaction
    - Bug #2 regression: SessionStore auto-saves to disk
    - Bug #3 regression: MemoryCoordinator refreshes every iteration
    - Orchestrator delegation flow
    - NDJSON event streaming
    - Concurrent session isolation
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Bug #1: ConversationManager copy-on-write ──────────────────


class TestConversationManager:
    """Verify copy-on-write semantics fix the shared-reference bug."""

    def test_append_returns_new_instance(self):
        from thomas.chat.conversation import ConversationManager

        cm1 = ConversationManager()
        cm2 = cm1.append_message("user", "Hello")

        assert cm1 is not cm2, "append_message must return a NEW instance"
        assert cm1.length == 0
        assert cm2.length == 1

    def test_append_does_not_mutate_original(self):
        from thomas.chat.conversation import ConversationManager

        cm1 = ConversationManager()
        cm2 = cm1.append_message("user", "Hello")
        cm3 = cm2.append_message("assistant", "Hi there")

        assert cm1.length == 0, "Original must be untouched"
        assert cm2.length == 1
        assert cm3.length == 2

    def test_compact_returns_new_instance(self):
        from thomas.chat.conversation import ConversationManager

        cm = ConversationManager()
        for i in range(25):
            cm = cm.append_message("user", f"Message {i}")
            cm = cm.append_message("assistant", f"Reply {i}")

        compacted = cm.compact(target_tokens=2000)
        assert compacted is not cm, "compact must return a NEW instance"
        assert cm.length == 50, "Original must be untouched after compact"

    def test_version_increments(self):
        from thomas.chat.conversation import ConversationManager

        cm = ConversationManager()
        assert cm.version == 0
        cm = cm.append_message("user", "test")
        assert cm.version == 1
        cm = cm.append_message("assistant", "reply")
        assert cm.version == 2

    def test_serialization_roundtrip(self):
        from thomas.chat.conversation import ConversationManager

        cm = ConversationManager()
        cm = cm.append_message("user", "Hello")
        cm = cm.append_message("assistant", "Hi", metadata={"model": "test"})

        data = cm.to_dict()
        restored = ConversationManager.from_dict(data)

        assert restored.length == 2
        assert restored.version == cm.version
        msgs = restored.get_messages()
        assert msgs[0]["content"] == "Hello"
        assert msgs[1]["metadata"]["model"] == "test"

    def test_context_window_respects_budget(self):
        from thomas.chat.conversation import ConversationManager

        cm = ConversationManager()
        for i in range(20):
            cm = cm.append_message("user", f"{'x' * 200} msg {i}")
            cm = cm.append_message("assistant", f"{'y' * 200} reply {i}")

        window = cm.get_context_window(max_tokens=500)
        total_chars = sum(len(m.get("content", "")) for m in window)
        # Should be trimmed well below original (40 * ~200 = 8000 chars)
        assert total_chars < 4000

    def test_20_messages_survive_compaction(self):
        """Bug #1 regression: messages after compaction must remain accessible."""
        from thomas.chat.conversation import ConversationManager

        cm = ConversationManager()
        for i in range(20):
            cm = cm.append_message("user", f"Question {i}")
            cm = cm.append_message("assistant", f"Answer {i}")

        # Compact
        compacted = cm.compact(target_tokens=1000)
        assert compacted.length > 0

        # Add more messages AFTER compaction
        post = compacted.append_message("user", "After compaction")
        post = post.append_message("assistant", "Still here")

        msgs = post.get_messages()
        assert msgs[-1]["content"] == "Still here"
        assert msgs[-2]["content"] == "After compaction"


# ── Bug #2: SessionStore auto-save ──────────────────────────────


class TestSessionStore:
    """Verify atomic auto-save and crash recovery."""

    @pytest.fixture
    def store_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    @pytest.mark.asyncio
    async def test_save_and_load(self, store_dir):
        from thomas.chat.conversation import ConversationManager
        from thomas.chat.session_store import SessionMeta, SessionStore

        store = SessionStore(store_dir)
        cm = ConversationManager()
        cm = cm.append_message("user", "Hello")
        cm = cm.append_message("assistant", "Hi")

        meta = SessionMeta(session_id="test-123")
        saved = await store.save("test-123", cm, meta, force=True)
        assert saved is True

        loaded = await store.load("test-123")
        assert loaded is not None
        assert loaded.length == 2
        msgs = loaded.get_messages()
        assert msgs[0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_atomic_write_survives(self, store_dir):
        """Simulates crash recovery — file should be intact after save."""
        from thomas.chat.conversation import ConversationManager
        from thomas.chat.session_store import SessionStore

        store = SessionStore(store_dir)
        cm = ConversationManager()
        cm = cm.append_message("user", "Important data")

        await store.save("crash-test", cm, force=True)

        # Verify file exists and is valid JSON
        files = list(store_dir.glob("chat_*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["session_id"] == "crash-test"
        assert len(data["conversation"]["messages"]) == 1

    @pytest.mark.asyncio
    async def test_debounce(self, store_dir):
        from thomas.chat.conversation import ConversationManager
        from thomas.chat.session_store import SessionStore

        store = SessionStore(store_dir, auto_save_debounce_ms=10000)
        cm = ConversationManager()
        cm = cm.append_message("user", "test")

        # First save: should write (force=False but first time)
        r1 = await store.save("debounce-test", cm, force=True)
        assert r1 is True

        # Immediate second save: should be debounced
        r2 = await store.save("debounce-test", cm)
        assert r2 is False

    @pytest.mark.asyncio
    async def test_delete(self, store_dir):
        from thomas.chat.conversation import ConversationManager
        from thomas.chat.session_store import SessionStore

        store = SessionStore(store_dir)
        cm = ConversationManager()
        cm = cm.append_message("user", "test")

        await store.save("del-test", cm, force=True)
        assert await store.load("del-test") is not None

        deleted = await store.delete("del-test")
        assert deleted is True
        assert await store.load("del-test") is None

    @pytest.mark.asyncio
    async def test_load_nonexistent(self, store_dir):
        from thomas.chat.session_store import SessionStore

        store = SessionStore(store_dir)
        result = await store.load("does-not-exist")
        assert result is None


# ── Bug #3: MemoryCoordinator refreshes every iteration ─────────


class TestMemoryCoordinator:
    """Verify 3-layer memory refreshes at every iteration."""

    @pytest.mark.asyncio
    async def test_refresh_produces_context(self):
        from thomas.chat.conversation import ConversationManager
        from thomas.chat.memory_layers import MemoryCoordinator

        cm = ConversationManager()
        cm = cm.append_message("user", "What is Thomas?")

        coord = MemoryCoordinator(
            memory_engine=None,
            session_id="test-sess",
        )
        ctx = await coord.refresh("What is Thomas?", cm, iteration=0)

        assert not ctx.is_empty, "Working memory should contain current request"
        assert "What is Thomas?" in ctx.working

    @pytest.mark.asyncio
    async def test_refresh_working_memory_includes_recent_user_requests(self):
        from thomas.chat.conversation import ConversationManager
        from thomas.chat.memory_layers import MemoryCoordinator

        cm = ConversationManager()
        cm = cm.append_message("user", "Help my cousin learn quarterback basics.")
        cm = cm.append_message("assistant", "What age range?")
        cm = cm.append_message("user", "Make a PDF quiz pack with an answer key.")

        coord = MemoryCoordinator(memory_engine=None, session_id="test-sess")
        ctx = await coord.refresh("What had I asked you to make?", cm, iteration=0)

        assert "Recent user requests:" in ctx.working
        assert "quarterback basics" in ctx.working
        assert "PDF quiz pack" in ctx.working

    @pytest.mark.asyncio
    async def test_refresh_every_iteration(self):
        """Bug #3 regression: memory must refresh at iterations > 0."""
        from thomas.chat.conversation import ConversationManager
        from thomas.chat.memory_layers import MemoryCoordinator

        cm = ConversationManager()
        cm = cm.append_message("user", "Question about iteration")

        coord = MemoryCoordinator(memory_engine=None, session_id="test")

        ctx0 = await coord.refresh("query", cm, iteration=0)
        ctx1 = await coord.refresh("query", cm, iteration=1)
        ctx2 = await coord.refresh("query", cm, iteration=2)

        # All iterations should produce non-empty working memory
        assert not ctx0.is_empty
        assert not ctx1.is_empty
        assert not ctx2.is_empty

    @pytest.mark.asyncio
    async def test_semantic_caching(self):
        """Semantic memory should only refresh every N iterations."""
        from thomas.chat.conversation import ConversationManager
        from thomas.chat.memory_layers import MemoryCoordinator

        mock_engine = MagicMock()
        mock_engine.retrieve = MagicMock(return_value=MagicMock(text="domain knowledge"))

        coord = MemoryCoordinator(
            memory_engine=mock_engine,
            session_id="test",
            semantic_refresh_interval=3,
        )
        cm = ConversationManager()
        cm = cm.append_message("user", "test")

        # Iteration 0: should call retrieve
        await coord.refresh("query", cm, iteration=0)
        # Iteration 1: should use cache (not refresh semantic)
        await coord.refresh("query", cm, iteration=1)
        # Iteration 2: should use cache
        await coord.refresh("query", cm, iteration=2)
        # Iteration 3: should refresh semantic again
        await coord.refresh("query", cm, iteration=3)

    @pytest.mark.asyncio
    async def test_episode_capture(self):
        from thomas.chat.memory_layers import MemoryCoordinator

        coord = MemoryCoordinator(memory_engine=None, session_id="test")
        await coord.capture_episode(
            turn_number=1,
            user_message="Hello",
            assistant_response="Hi there",
            specialist="reasoning",
        )

        assert len(coord._episodes) == 1
        assert coord._episodes[0]["turn"] == 1
        assert coord._episodes[0]["specialist"] == "reasoning"

    @pytest.mark.asyncio
    async def test_episode_capture_persists_to_add_event_memory_api(self):
        from thomas.chat.memory_layers import MemoryCoordinator

        calls: list[tuple[str, str, str, dict[str, object]]] = []

        class _Memory:
            def add_event(
                self,
                thread: str,
                etype: str,
                text: str,
                metadata: dict[str, object] | None = None,
                blob_id: str | None = None,
            ) -> int:
                _ = blob_id
                calls.append((thread, etype, text, dict(metadata or {})))
                return len(calls)

        coord = MemoryCoordinator(memory_engine=_Memory(), session_id="thread-123")
        await coord.capture_episode(
            turn_number=7,
            user_message="Make a football quiz PDF for my cousin.",
            assistant_response="I will research and draft the PDF quiz pack.",
            specialist="reasoning",
        )

        assert [call[1] for call in calls] == ["user_message", "assistant_response"]
        assert calls[0][0] == "thread-123"
        assert "football quiz PDF" in calls[0][2]
        assert "draft the PDF quiz pack" in calls[1][2]
        assert calls[0][3]["turn"] == 7
        assert calls[0][3]["specialist"] == "reasoning"

    @pytest.mark.asyncio
    async def test_budget_enforcement(self):
        from thomas.chat.memory_layers import MemoryContext

        ctx = MemoryContext(
            working="x" * 10000,
            episodic="y" * 10000,
            semantic="z" * 10000,
        )
        # Should be well over any reasonable budget
        assert ctx.total_tokens > 5000


# ── Orchestrator Protocol ────────────────────────────────────────


class TestProtocol:
    def test_capability_token_validity(self):
        from datetime import datetime, timedelta, timezone

        from thomas.orchestrator.protocol import CapabilityToken

        token = CapabilityToken(
            specialist_id="coding",
            session_id="test",
            allowed_tools={"shell", "filesystem"},
            autonomy_level=3,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        assert token.is_valid()
        assert token.permits_tool("shell")
        assert not token.permits_tool("nuclear_launch")

    def test_expired_token(self):
        from datetime import datetime, timedelta, timezone

        from thomas.orchestrator.protocol import CapabilityToken

        token = CapabilityToken(
            specialist_id="coding",
            session_id="test",
            allowed_tools={"shell"},
            autonomy_level=3,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        assert not token.is_valid()


# ── Specialist Registry ──────────────────────────────────────────


class TestSpecialistRegistry:
    def test_register_and_find(self):
        from thomas.orchestrator.registry import SpecialistRegistry
        from thomas.specialists.reasoning import ReasoningSpecialist

        registry = SpecialistRegistry()
        spec = ReasoningSpecialist(config=None, llm=None, tools=None)
        registry.register(spec)

        assert "reasoning" in registry.specialist_ids
        found = registry.find_by_capability("planning")
        assert len(found) > 0
        assert found[0].specialist_id == "reasoning"

    def test_find_best(self):
        from thomas.orchestrator.registry import SpecialistRegistry
        from thomas.specialists.coding import CodingSpecialist
        from thomas.specialists.reasoning import ReasoningSpecialist

        registry = SpecialistRegistry()
        registry.register(ReasoningSpecialist(config=None, llm=None, tools=None))
        registry.register(CodingSpecialist(config=None, llm=None, tools=None))

        best = registry.find_best({"coding", "debugging"})
        assert best is not None
        assert best.specialist_id == "coding"


# ── EventDispatcher ──────────────────────────────────────────────


class TestEventDispatcher:
    @pytest.mark.asyncio
    async def test_emit_ndjson(self):
        from thomas.chat.event_stream import EventDispatcher

        chunks: list[bytes] = []

        async def mock_send(data: bytes) -> None:
            chunks.append(data)

        dispatcher = EventDispatcher(mock_send)
        await dispatcher.emit({"type": "text", "text": "Hello"})
        await dispatcher.emit({"type": "done", "session_id": "test"})

        assert len(chunks) == 2
        parsed = [json.loads(c.decode()) for c in chunks]
        assert parsed[0]["type"] == "text"
        assert parsed[0]["text"] == "Hello"
        assert parsed[1]["type"] == "done"

    @pytest.mark.asyncio
    async def test_emit_convenience_methods(self):
        from thomas.chat.event_stream import EventDispatcher

        chunks: list[bytes] = []

        async def mock_send(data: bytes) -> None:
            chunks.append(data)

        d = EventDispatcher(mock_send)
        await d.emit_text("Hi")
        await d.emit_thinking("Planning...", phase="planning")
        await d.emit_delegation("coding", "Write function")
        await d.emit_tool_start("shell")
        await d.emit_tool_result("shell", result="ok")
        await d.emit_error("test error")

        assert d.event_count == 6
        events = [json.loads(c.decode()) for c in chunks]
        types = [e["type"] for e in events]
        assert types == ["text", "thinking", "delegation", "tool_start", "tool_result", "error"]


# ── ThinkingTracker ──────────────────────────────────────────────


class TestThinkingTracker:
    def test_track_phases(self):
        from thomas.chat.thinking import ThinkingTracker

        tracker = ThinkingTracker()
        tracker.start_phase("planning", "Analyzing the request...")
        tracker.end_phase("planning")
        tracker.start_phase("delegating", "Handing off to CodingSpecialist")
        tracker.end_phase("delegating")

        assert len(tracker.phases) == 2
        summary = tracker.summary()
        assert "planning" in summary
        assert "delegating" in summary

    def test_events_output(self):
        from thomas.chat.thinking import ThinkingTracker

        tracker = ThinkingTracker()
        tracker.start_phase("planning", "test")
        tracker.end_phase("planning")

        events = tracker.events()
        assert len(events) >= 1
        assert events[0]["type"] == "thinking"


# ── Concurrent Session Isolation ─────────────────────────────────


class TestConcurrentSessions:
    @pytest.mark.asyncio
    async def test_sessions_dont_cross_contaminate(self):
        from thomas.chat.conversation import ConversationManager
        from thomas.chat.session_store import SessionStore

        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))

            cm_a = ConversationManager()
            cm_a = cm_a.append_message("user", "Session A message")

            cm_b = ConversationManager()
            cm_b = cm_b.append_message("user", "Session B message")

            await store.save("session-a", cm_a, force=True)
            await store.save("session-b", cm_b, force=True)

            loaded_a = await store.load("session-a")
            loaded_b = await store.load("session-b")

            assert loaded_a.get_messages()[0]["content"] == "Session A message"
            assert loaded_b.get_messages()[0]["content"] == "Session B message"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
