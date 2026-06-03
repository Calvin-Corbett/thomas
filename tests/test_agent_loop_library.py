import asyncio

from thomas.agent.loop import AgentLoop
from thomas.agent.routing import RouteDecision
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.core.llm import StreamEvent, TokenUsage
from thomas.library import ResearchLibrary, default_library_root
from thomas.tools.registry import ToolRegistry


class CaptureLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=4096, max_tokens=256)
        self.session_usage = TokenUsage(prompt_tokens=400, completion_tokens=120, total_tokens=520)
        self.calls = []

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        self.calls.append({"messages": messages, "tools": tools})
        text = (
            "Based on the reference material, the best approach is bounded retries, "
            "exponential backoff, and selective retryable status codes for reliability."
        )
        yield StreamEvent(type="token", data={"text": text})
        yield StreamEvent(type="done", data={})


def test_research_route_injects_library_context_and_auto_captures(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "1")
    monkeypatch.setenv("THOMAS_LIBRARY_AUTO_CAPTURE_RESEARCH", "1")

    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "runtime")),
    )

    lib = ResearchLibrary(default_library_root(cfg))
    lib.add_entry(
        title="HTTP Retry Patterns",
        category="research",
        summary="Practical retry design for HTTP clients.",
        source="https://example.com/http-retry",
        tags=["http", "retries"],
        content="Use exponential backoff and retry only transient status codes.",
    )

    llm = CaptureLLM()
    tools = ToolRegistry()
    agent = AgentLoop(cfg, llm, tools, conversation=[], memory=None, thread_id="t-lib")

    async def run_once():
        async for _ in agent.run("research best http retry strategy"):
            pass

    asyncio.run(run_once())

    assert len(llm.calls) >= 1
    first_messages = llm.calls[0]["messages"]
    system = next((m for m in first_messages if m.get("role") == "system"), {})
    text = str(system.get("content", ""))
    assert "<library_context>" in text
    assert "HTTP Retry Patterns" in text

    rows = lib.list_entries(query="http retry strategy", limit=20)
    assert len(rows) >= 2
    assert any(bool(r.get("auto_captured")) for r in rows)


def test_benchmark_mode_skips_library_context_and_auto_capture(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "1")
    monkeypatch.setenv("THOMAS_LIBRARY_AUTO_CAPTURE_RESEARCH", "1")

    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "runtime")),
    )

    lib = ResearchLibrary(default_library_root(cfg))
    lib.add_entry(
        title="Benchmark Note",
        category="research",
        summary="Prior benchmark note that must not be injected.",
        source="local",
        tags=["benchmark"],
        content="This prior benchmark note should stay out of benchmark prompts.",
    )

    llm = CaptureLLM()
    agent = AgentLoop(cfg, llm, ToolRegistry(), conversation=[], memory=None, thread_id="t-bench-lib")

    async def run_once():
        async for _ in agent.run(
            "fix the benchmark task using the task repository only",
            mode="thinking",
            tools_policy="never",
            job_type="benchmark",
        ):
            pass

    asyncio.run(run_once())

    assert len(llm.calls) >= 1
    first_messages = llm.calls[0]["messages"]
    system = next((m for m in first_messages if m.get("role") == "system"), {})
    text = str(system.get("content", ""))
    assert "<library_context>" not in text
    assert "Benchmark Note" not in text

    rows = lib.list_entries(query="benchmark task", limit=20)
    assert not any(bool(r.get("auto_captured")) for r in rows)


def test_auto_capture_skips_benchmark_prompts(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "1")
    monkeypatch.setenv("THOMAS_LIBRARY_AUTO_CAPTURE_RESEARCH", "1")

    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "runtime")),
    )
    llm = CaptureLLM()
    agent = AgentLoop(cfg, llm, ToolRegistry(), conversation=[], memory=None, thread_id="t-bench")
    lib = ResearchLibrary(default_library_root(cfg))
    route = RouteDecision(
        path="research",
        confidence=1.0,
        reasons=["test"],
        mode="auto",
        tools_policy="auto",
        include_purpose=False,
        memory_include_global=True,
        memory_include_profile=False,
        memory_budget_tokens=900,
        is_followup=False,
    )
    query = (
        "You are solving an official HumanEval task.\n"
        "Entry point: increment\n"
        "---PROMPT START---\n"
        "def increment(n):\n"
        "---PROMPT END---"
    )
    answer = "Use a return statement with proper indentation for the function body."

    agent._auto_capture_research(route=route, query=query, answer=answer, job_type="benchmark")

    rows = lib.list_entries(query="official HumanEval task", limit=20)
    assert not any(bool(r.get("auto_captured")) for r in rows)
