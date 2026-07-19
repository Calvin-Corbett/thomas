import asyncio
import threading
import time
import unittest
from types import SimpleNamespace

from thomas.chat.conversation import ConversationManager
from thomas.chat.memory_layers import MemoryCoordinator
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.memory.autonomy import AutonomyMemoryEngine


class _EventMemory:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str, dict]] = []

    def add_event(self, thread: str, etype: str, text: str, metadata: dict | None = None) -> int:
        self.events.append((thread, etype, text, dict(metadata or {})))
        return len(self.events)


class _FabricStyleMemory:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int | None]] = []

    def retrieve(self, thread_id: str, query: str, budget_tokens: int | None = None):
        self.calls.append((thread_id, query, budget_tokens))
        return SimpleNamespace(pack_text=f"fabric memory: {thread_id} / {query} / {budget_tokens}")


class _BlockingMemory:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def retrieve(self, **_kwargs: object) -> str:
        self.entered.set()
        self.release.wait(timeout=1.0)
        return "memory result"


class _PinsMemory:
    def __init__(self) -> None:
        self.policy: dict[str, object] = {}

    def set_thread_memory_policy(self, thread_id: str, **policy: object) -> None:
        self.policy = {"thread_id": thread_id, **policy}

    def retrieve(self, **_kwargs: object) -> str:
        return "PIN(note:favorite): burnt orange"


class _RowsCursor:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, str]]:
        return self._rows


class _RowsDb:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows
        self.params: tuple[object, ...] | None = None

    def execute(self, _sql: str, params: tuple[object, ...]) -> _RowsCursor:
        self.params = params
        return _RowsCursor(self.rows)


class _FabricStyleMemoryWithRows(_FabricStyleMemory):
    def __init__(self, rows: list[dict[str, str]]) -> None:
        super().__init__()
        self.db = _RowsDb(rows)

    def retrieve(self, thread_id: str, query: str, budget_tokens: int | None = None):
        self.calls.append((thread_id, query, budget_tokens))
        return SimpleNamespace(pack_text="[Episodes]\n  [user] What was the code phrase?")


class TestMemoryCoordinator(unittest.IsolatedAsyncioTestCase):
    async def test_sync_retrieval_does_not_block_the_event_loop(self) -> None:
        memory = _BlockingMemory()
        coordinator = MemoryCoordinator(memory, "session-responsive")
        started = time.monotonic()

        task = asyncio.create_task(
            coordinator._retrieve_memory_text(
                query="slow retrieval",
                thread_id="session-responsive",
                budget=300,
                mode="auto",
            )
        )
        while not memory.entered.is_set() and time.monotonic() - started < 0.25:
            await asyncio.sleep(0.01)

        elapsed = time.monotonic() - started
        memory.release.set()
        self.assertTrue(memory.entered.is_set())
        self.assertLess(elapsed, 0.25)
        self.assertEqual("memory result", await task)

    async def test_refresh_reads_fabric_v2_retrieve_signature(self) -> None:
        memory = _FabricStyleMemory()
        coordinator = MemoryCoordinator(memory, "session-fabric", context_budget=900)
        conversation = ConversationManager().append_message("user", "What phrase did I store?")

        ctx = await coordinator.refresh("What phrase did I store?", conversation, iteration=0)

        self.assertIn("fabric memory: session-fabric / What phrase did I store? / 300", ctx.episodic)
        self.assertIn("fabric memory: session-fabric / What phrase did I store? / 450", ctx.semantic)
        self.assertEqual(
            [
                ("session-fabric", "What phrase did I store?", 300),
                ("session-fabric", "What phrase did I store?", 450),
            ],
            memory.calls,
        )

    async def test_pins_only_policy_injects_pinned_context_automatically(self) -> None:
        memory = _PinsMemory()
        policy = SimpleNamespace(
            include_thread=True,
            include_global=False,
            include_profile=False,
            pins_only=True,
            context_budget=900,
        )
        coordinator = MemoryCoordinator(memory, "session-pins", context_budget=900, policy=policy)
        conversation = ConversationManager().append_message("user", "What should I use?")

        ctx = await coordinator.refresh("What should I use?", conversation, iteration=0)

        self.assertIn("burnt orange", ctx.episodic)
        self.assertEqual(memory.policy["thread_id"], "session-pins")
        self.assertTrue(memory.policy["pins_only"])
        self.assertFalse(ctx.semantic)

    async def test_pins_only_fails_closed_when_backend_cannot_apply_scope(self) -> None:
        policy = SimpleNamespace(
            include_thread=True,
            include_global=False,
            include_profile=False,
            pins_only=True,
            context_budget=900,
        )
        memory = _FabricStyleMemory()
        coordinator = MemoryCoordinator(memory, "session-pins", context_budget=900, policy=policy)
        conversation = ConversationManager().append_message("user", "What should I use?")

        ctx = await coordinator.refresh("What should I use?", conversation, iteration=0)

        self.assertFalse(ctx.episodic)
        self.assertFalse(memory.calls)

    async def test_pins_only_real_backend_excludes_unpinned_profile_hints(self) -> None:
        config = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=str(self._temporaryDirectory.name)),
        )
        memory = AutonomyMemoryEngine(config, enable_legacy=False, enable_v2=True)
        memory.start()
        try:
            memory.pin("favorite.color", "burnt orange")
            memory._fabric_v2.upsert_profile_hints(
                thread_id=None,
                hints=[{"key": "unapproved.private", "value": "SHOULD_NOT_APPEAR", "confidence": 1.0}],
                source_episode_id=None,
            )
            policy = SimpleNamespace(
                include_thread=True,
                include_global=False,
                include_profile=False,
                pins_only=True,
                context_budget=900,
            )
            coordinator = MemoryCoordinator(memory, "session-real-pins", context_budget=900, policy=policy)
            conversation = ConversationManager().append_message("user", "What should I use?")

            ctx = await coordinator.refresh("What should I use?", conversation, iteration=0)

            self.assertIn("burnt orange", ctx.episodic)
            self.assertNotIn("SHOULD_NOT_APPEAR", ctx.episodic)
            self.assertFalse(ctx.semantic)
        finally:
            memory.close()

    def setUp(self) -> None:
        import tempfile

        self._temporaryDirectory = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._temporaryDirectory.cleanup()

    async def test_recall_prompt_includes_recent_thread_memory_fallback(self) -> None:
        memory = _FabricStyleMemoryWithRows(
            [
                {"role": "assistant", "content": "stored"},
                {
                    "role": "user",
                    "content": "Remember that the temporary code phrase is SILVER MAPLE 482.",
                },
            ]
        )
        coordinator = MemoryCoordinator(memory, "session-fabric", context_budget=900)
        conversation = ConversationManager().append_message("user", "What was the code phrase?")

        ctx = await coordinator.refresh("What was the code phrase?", conversation, iteration=0)

        self.assertIn("[Recent thread memory]", ctx.episodic)
        self.assertIn("SILVER MAPLE 482", ctx.episodic)
        self.assertEqual(("session-fabric", 8), memory.db.params)

    async def test_capture_episode_persists_to_add_event_memory_backend(self) -> None:
        memory = _EventMemory()
        coordinator = MemoryCoordinator(memory, "session-memory-smoke")

        await coordinator.capture_episode(
            turn_number=2,
            user_message="Remember that the QA phrase is blue cedar.",
            assistant_response="stored",
            specialist="reasoning",
        )

        self.assertEqual(
            [
                ("session-memory-smoke", "user_message", "Remember that the QA phrase is blue cedar."),
                ("session-memory-smoke", "assistant_message", "stored"),
            ],
            [(thread, etype, text) for thread, etype, text, _meta in memory.events],
        )
        self.assertEqual(memory.events[0][3]["turn"], 2)
        self.assertEqual(memory.events[0][3]["specialist"], "reasoning")


if __name__ == "__main__":
    unittest.main()
