from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.library import ResearchLibrary, default_library_root


def test_library_add_list_and_context(tmp_path) -> None:  # noqa: ANN001
    lib = ResearchLibrary(tmp_path / "library")
    row = lib.add_entry(
        title="Rust Async Runtime Comparison",
        category="research",
        content="Tokio and async-std have different scheduler models and ecosystem support.",
        summary="Compares Rust async runtime tradeoffs.",
        source="https://example.com/rust-async",
        tags=["rust", "async", "runtime"],
    )
    assert row["id"]
    assert (lib.root / row["path"]).exists()

    rows = lib.list_entries(query="rust async runtime", limit=5)
    assert len(rows) >= 1
    assert rows[0]["title"] == "Rust Async Runtime Comparison"

    ctx = lib.build_context(query="rust async runtime", max_tokens=300, limit=3)
    assert "Library Context" in ctx
    assert "Rust Async Runtime Comparison" in ctx


def test_library_auto_dedupe_research_notes(tmp_path) -> None:  # noqa: ANN001
    lib = ResearchLibrary(tmp_path / "library")
    first = lib.add_research_note(
        query="latest httpx retry patterns",
        answer="Use bounded retries with exponential backoff and selective status retry lists.",
        source="assistant:test",
    )
    second = lib.add_research_note(
        query="latest httpx retry patterns",
        answer="Use bounded retries with exponential backoff and selective status retry lists.",
        source="assistant:test",
    )
    assert first["id"] == second["id"]
    rows = lib.list_entries(query="httpx retry", limit=10)
    assert len(rows) == 1


def test_library_add_entry_id_collision_uses_unique_suffix(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    lib = ResearchLibrary(tmp_path / "library")

    monkeypatch.setattr("thomas.library.store.time.time", lambda: 1_762_000_000)
    first = lib.add_entry(
        title="Same title",
        category="research",
        content="first payload",
        summary="first",
        source="unit:test",
    )
    second = lib.add_entry(
        title="Same title",
        category="research",
        content="second payload",
        summary="second",
        source="unit:test",
    )

    assert first["id"] != second["id"]
    assert first["path"] != second["path"]

    first_row = lib.get_entry(first["id"])
    second_row = lib.get_entry(second["id"])
    assert first_row is not None
    assert second_row is not None
    assert "first payload" in str(first_row.get("content", ""))
    assert "second payload" in str(second_row.get("content", ""))


def test_default_library_root_for_runtime_memory(tmp_path) -> None:  # noqa: ANN001
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "runtime")),
    )
    root = default_library_root(cfg)
    assert root == (tmp_path / "library").resolve()
