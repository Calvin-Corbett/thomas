import unittest
from types import SimpleNamespace

from thomas.chat.conversation import ConversationManager
from thomas.chat.memory_layers import MemoryCoordinator


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
