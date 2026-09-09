import asyncio

from thomas.agent.loop import AgentLoop
from thomas.agent.loop_streaming import _LIBRARY_CAPTURE_ROUTES, _LIBRARY_CONTEXT_ROUTES
from thomas.agent.routing import IntentRouter, RouteDecision
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
        yield StreamEvent(type="token", data={"text": ANSWER})
        yield StreamEvent(type="done", data={})


# The answer the fake model returns. It has to clear the auto-capture floor for
# an unclassified turn, which is 200 characters (_LIBRARY_CAPTURE_MIN_CHARS).
# The previous 145-character version cleared only the "research" floor of 80 --
# a floor that stopped being reachable when 69bbbab0 removed prompt-derived
# route classification. See the docstring below for the measurement.
ANSWER = (
    "Based on the reference material, the best approach is bounded retries, "
    "exponential backoff, and selective retryable status codes for reliability. "
    "Cap the total elapsed retry window, prefer idempotent requests, and add "
    "jitter so simultaneous clients do not resynchronise into a thundering herd."
)


def test_research_route_injects_library_context_and_auto_captures(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """An ordinary chat turn reaches the research library, both ways.

    Historical name: there is no "research route" any more. 69bbbab0 ("land
    model-owned routing, removing the prompt classifiers") made IntentRouter
    return path="model_owned" for every natural-language turn, and the two
    allowlists in loop_streaming.py were never updated -- so the library was
    dead code for every real turn. That commit DID add "model_owned" to the
    sibling route allowlists in loop_core.py, which is why this reads as an
    omission rather than a deliberate removal; the library is also absent from
    the commit's own list of what it removes and its two known losses.

    Measured with a path="research" RouteDecision as the control, which is the
    path the router produced before 69bbbab0:

        route path    library context   auto-captured rows
        model_owned   False             0        <- before, every real turn
        research      True              1        <- control, machinery works
        model_owned   True              1        <- after this fix

    The token-economy dial (RuntimeOverheadPolicy.include_library_context) and
    benchmark_mode still decide whether the context is affordable. Nothing here
    reads the user's prose, so the prompt wording is incidental -- this passes
    for any non-benchmark prompt, which is the current contract.
    """
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


def test_the_library_accepts_the_route_the_router_actually_produces(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """The library allowlists must contain the live router's path, not a dead one.

    This is the regression guard for the defect above, stated without going
    through AgentLoop.run: whatever path IntentRouter emits for a plain turn has
    to be admitted by both library gates. Before the fix IntentRouter emitted
    "model_owned" while both allowlists listed only the classifier-era paths
    ("research", "planning", "debug_audit", "coding_task"), so retrieve_library
    returned "" and auto_capture_research returned early on every real turn:
    library context False / 0 captured rows, versus True / 1 for a hand-built
    path="research" control.

    Asserting against IntentRouter's live output rather than the literal string
    "model_owned" means renaming or re-adding a route cannot silently re-orphan
    the library again.
    """
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "1")
    monkeypatch.setenv("THOMAS_LIBRARY_AUTO_CAPTURE_RESEARCH", "1")

    live_path = IntentRouter().decide("anything at all").path

    assert live_path in _LIBRARY_CONTEXT_ROUTES, (
        f"router emits {live_path!r} but retrieve_library only admits {sorted(_LIBRARY_CONTEXT_ROUTES)}"
    )
    assert live_path in _LIBRARY_CAPTURE_ROUTES, (
        f"router emits {live_path!r} but auto-capture only admits {sorted(_LIBRARY_CAPTURE_ROUTES)}"
    )

    # Control: the machinery, not just the allowlist, still works end to end.
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
    agent = AgentLoop(cfg, CaptureLLM(), ToolRegistry(), conversation=[], memory=None, thread_id="t-live-route")
    live_route = IntentRouter().decide("best http retry strategy")

    assert "<library_context>" in agent._retrieve_library("best http retry strategy", live_route)

    agent._auto_capture_research(route=live_route, query="best http retry strategy", answer=ANSWER, job_type=None)
    rows = lib.list_entries(query="http retry strategy", limit=20)
    assert any(bool(r.get("auto_captured")) for r in rows)


def test_an_empty_library_adds_nothing_to_the_prompt(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """A library with no matching entry contributes no text, not a warning string.

    retrieve_library used to treat "no matching entry" the same as "retrieval
    raised", returning the literal "[Library context unavailable]". That was
    harmless while the function was unreachable for ordinary turns. Once
    model-owned turns became eligible it would have put that string into the
    system prompt of every turn on a fresh install, where the library is empty
    by definition -- measured: build_context() returns '' for an empty library,
    so the old code returned "[Library context unavailable]" 100% of the time.

    retrieve_memory, two functions up in the same file, had the identical bug
    and it was fixed on 2026-03-18 for the identical reason ("Empty string = no
    memory context, which is the honest state"). That fix never reached
    retrieve_library because the stale route allowlist kept it unreachable.

    A genuine exception still reports "[Library context unavailable]"; that path
    is unchanged and is asserted below so this test cannot pass by the function
    simply never reporting anything.
    """
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "1")

    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "runtime")),
    )
    agent = AgentLoop(cfg, CaptureLLM(), ToolRegistry(), conversation=[], memory=None, thread_id="t-empty-lib")
    route = IntentRouter().decide("anything at all")

    assert agent._retrieve_library("nothing is stored yet", route) == ""

    # Control: a real failure is still surfaced, so the assertion above is not
    # just measuring a function that returns "" no matter what.
    class Boom:
        def build_context(self, **_kwargs):  # noqa: ANN003
            raise RuntimeError("library backend down")

    agent._library = Boom()
    assert agent._retrieve_library("nothing is stored yet", route) == "[Library context unavailable]"
