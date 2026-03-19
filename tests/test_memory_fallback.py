from __future__ import annotations

import pytest

from thomas import memory as memory_mod


def test_fallback_retriever_returns_thread_matches_when_active() -> None:
    if not getattr(memory_mod, "_EPISODIC_FALLBACK_ACTIVE", False):
        pytest.skip("real episodic memory module is active")

    memory = memory_mod.EpisodicMemory()
    memory.add(memory_mod.Episode(text="alpha reminder for launch", thread_id="thread-a"))
    memory.add(memory_mod.Episode(text="beta follow-up", thread_id="thread-b"))

    retriever = memory_mod.MemoryRetriever(memory)
    results = retriever.retrieve("alpha", thread_id="thread-a")

    assert [episode.text for episode in results] == ["alpha reminder for launch"]
