from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.library import ResearchLibrary, default_library_root
from thomas.memory.autonomy import AutonomyMemoryEngine


def _cfg(tmp_path) -> AppConfig:  # noqa: ANN001
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "runtime")),
    )


def test_curator_promotes_library_entries_into_global_facts(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_MEMORY_CURATOR_ENABLED", "1")
    monkeypatch.setenv("THOMAS_MEMORY_CURATOR_MIN_INTERVAL_SECONDS", "0")

    cfg = _cfg(tmp_path)
    lib = ResearchLibrary(default_library_root(cfg))
    lib.add_entry(
        title="HTTP Retry Blueprint",
        category="research",
        content="Use bounded retries and exponential backoff for transient failures.",
        summary="Retry only transient statuses, with capped backoff windows.",
        source="https://example.com/retry-blueprint",
        tags=["http", "retries"],
    )

    mem = AutonomyMemoryEngine(cfg, enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        result = mem.run_curator(force=True)
        assert result.get("ran") is True
        promoted = int(result.get("facts_promoted", 0))
        queued = int(result.get("queued_for_approval", 0))
        assert (promoted + queued) >= 1

        if promoted <= 0 and queued > 0:
            pending = mem.list_curator_approvals(status="pending", limit=20)
            assert pending
            aid = int(pending[0]["id"])
            decision = mem.decide_curator_approval(
                aid,
                approve=True,
                actor="test",
                reason="approve for retrieval assertion",
            )
            assert decision.get("ok") is True

        assert int(mem.stats().get("v2_facts", 0)) >= 1

        ctx = mem.retrieve(
            "HTTP Retry Blueprint",
            thread="telegram:1",
            budget=1000,
            mode="auto",
        )
        text = ctx.text.lower()
        assert "http retry blueprint" in text
    finally:
        mem.close()


def test_curator_interval_cooldown_skips_second_run(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_MEMORY_CURATOR_ENABLED", "1")
    monkeypatch.setenv("THOMAS_MEMORY_CURATOR_MIN_INTERVAL_SECONDS", "3600")

    cfg = _cfg(tmp_path)
    mem = AutonomyMemoryEngine(cfg, enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        first = mem.run_curator(force=False)
        second = mem.run_curator(force=False)
        assert first.get("ran") is True
        assert second.get("ran") is False
        assert second.get("reason") == "interval_cooldown"
    finally:
        mem.close()


def test_curator_promotes_episode_facts_incrementally(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_MEMORY_CURATOR_ENABLED", "1")
    monkeypatch.setenv("THOMAS_MEMORY_CURATOR_MIN_INTERVAL_SECONDS", "0")

    cfg = _cfg(tmp_path)
    mem = AutonomyMemoryEngine(cfg, enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        mem.add_event("telegram:7", "user_message", "my deployment target is cloudflare workers")

        immediate = mem.retrieve("deployment target", thread="telegram:8", budget=1000, mode="auto")
        assert "cloudflare workers" in immediate.text.lower()

        before = int(mem.stats().get("v2_facts", 0))
        first = mem.run_curator(force=True)
        after_first = int(mem.stats().get("v2_facts", 0))

        second = mem.run_curator(force=True)
        after_second = int(mem.stats().get("v2_facts", 0))

        assert before >= 1
        assert first.get("ran") is True
        assert int(first.get("facts_promoted", 0)) == 0
        assert after_first == before
        assert int(second.get("facts_promoted", 0)) == 0
        assert after_second == after_first
    finally:
        mem.close()


def test_curator_approval_queue_and_apply(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_MEMORY_CURATOR_ENABLED", "1")
    monkeypatch.setenv("THOMAS_MEMORY_CURATOR_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("THOMAS_MEMORY_CURATOR_APPROVAL_ENABLED", "1")
    monkeypatch.setenv("THOMAS_MEMORY_CURATOR_APPROVAL_AUTO_APPLY_CONFIDENCE", "0.95")

    cfg = _cfg(tmp_path)
    mem = AutonomyMemoryEngine(cfg, enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        fabric = mem._fabric_v2
        assert fabric is not None
        fabric.ingest_episode("telegram:11", "user", "I use zed for coding", ts_ms=1700000000000)

        before = int(mem.stats().get("v2_facts", 0))
        result = mem.run_curator(force=True)
        assert result.get("ran") is True
        assert int(result.get("queued_for_approval", 0)) >= 1

        pending = mem.list_curator_approvals(status="pending", limit=20)
        assert len(pending) >= 1
        aid = int(pending[0]["id"])

        decision = mem.decide_curator_approval(
            aid,
            approve=True,
            actor="test",
            reason="unit test approval",
        )
        assert decision.get("ok") is True
        assert str(decision.get("status") or "") in ("applied", "approved")

        after = int(mem.stats().get("v2_facts", 0))
        assert after >= before + 1

        ctx = mem.retrieve("zed for coding", thread="telegram:99", budget=1000, mode="auto")
        assert "zed" in ctx.text.lower()
    finally:
        mem.close()
