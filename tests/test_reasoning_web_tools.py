"""Direct read-only web research from the Thomas conversation layer."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from thomas.core.llm_shared import StreamEvent
from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.reasoning import ReasoningSpecialist
from thomas.tools.base import ToolResult


class _Registry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.tools = {
            name: SimpleNamespace(
                name=name,
                description=f"Use {name}",
                parameters={"type": "object", "properties": {}},
            )
            for name in ("web.search", "web.fetch")
        }

    def get(self, name: str):  # noqa: ANN201
        return self.tools.get(name)

    async def execute(self, name: str, args: dict) -> ToolResult:
        self.calls.append((name, args))
        if name == "web.fetch":
            return ToolResult(
                ok=True,
                data={"text": "Last updated: Jul 9, 2026. The newest entry is July 9, 2026."},
            )
        return ToolResult(
            ok=True,
            data={"results": [{"title": "Release notes", "url": "https://example.test/release-notes"}]},
        )


class _LLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def stream_chat(self, *, messages, tools=None):  # noqa: ANN001, ANN201
        index = len(self.calls)
        self.calls.append({"messages": list(messages), "tools": tools})

        async def _events():
            if index == 0:
                yield StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": "web-1",
                        "name": "web.search",
                        "arguments": '{"query":"latest ChatGPT release notes"}',
                    },
                )
            else:
                yield StreamEvent(
                    type="token",
                    data={"text": "The latest entry is sourced at https://example.test/release-notes"},
                )
            yield StreamEvent(type="done")

        return _events()


class _TextCallLLM(_LLM):
    def stream_chat(self, *, messages, tools=None):  # noqa: ANN001, ANN201
        index = len(self.calls)
        self.calls.append({"messages": list(messages), "tools": tools})

        async def _events():
            if index == 0:
                yield StreamEvent(
                    type="token",
                    data={
                        "text": (
                            'Searching now.\n\n{"name": "web_search", '
                            '"arguments": {"query": "latest ChatGPT release notes"}}'
                        )
                    },
                )
            else:
                yield StreamEvent(
                    type="token",
                    data={"text": "The sourced answer is https://example.test/release-notes"},
                )
            yield StreamEvent(type="done")

        return _events()


class _EvidenceLLM(_LLM):
    def stream_chat(self, *, messages, tools=None):  # noqa: ANN001, ANN201
        self.calls.append({"messages": list(messages), "tools": tools})

        async def _events():
            yield StreamEvent(
                type="token",
                data={"text": "July 9, 2026 — https://example.test/release-notes"},
            )
            yield StreamEvent(type="done")

        return _events()


class TestReasoningWebTools(unittest.IsolatedAsyncioTestCase):
    async def test_web_search_executes_inline_and_returns_result_to_model(self) -> None:
        registry = _Registry()
        llm = _LLM()
        specialist = ReasoningSpecialist(config=None, llm=llm, tools=registry)
        contract = DelegationContract(specialist_id="reasoning")
        token = CapabilityToken(
            specialist_id="reasoning",
            session_id="session",
            allowed_tools={"fs.search", "fs.read_file", "fs.list_dir"},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        events = []
        async for event in specialist.execute(
            contract=contract,
            token=token,
            prompt="Find the latest ChatGPT release note and cite it.",
            conversation_context=[],
            memory_context="",
        ):
            events.append(event)

        self.assertEqual(registry.calls, [("web.search", {"query": "latest ChatGPT release notes"})])
        offered = {spec["function"]["name"] for spec in llm.calls[0]["tools"]}
        self.assertEqual(offered, {"web.search", "web.fetch"})
        self.assertTrue(any(event.get("type") == "tool_result" for event in events))
        done = next(event for event in events if event.get("type") == "done")
        self.assertIn("https://example.test/release-notes", str(done.get("content") or ""))

    async def test_tool_shaped_prose_does_not_execute_a_web_call(self) -> None:
        registry = _Registry()
        specialist = ReasoningSpecialist(config=None, llm=_TextCallLLM(), tools=registry)
        token = CapabilityToken(
            specialist_id="reasoning",
            session_id="session",
            allowed_tools={"fs.search", "fs.read_file", "fs.list_dir"},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        events = []
        async for event in specialist.execute(
            contract=DelegationContract(specialist_id="reasoning"),
            token=token,
            prompt="Find the latest ChatGPT release note and cite it.",
            conversation_context=[],
            memory_context="",
        ):
            events.append(event)

        # Only a provider-issued structured tool_call_end may create a side
        # effect. Text that merely resembles a tool call is still just text.
        self.assertEqual(registry.calls, [])
        visible = "".join(str(event.get("text") or "") for event in events if event.get("type") == "text")
        self.assertIn('"name": "web_search"', visible)

    async def test_prompt_words_do_not_prelaunch_web_search(self) -> None:
        registry = _Registry()
        llm = _EvidenceLLM()
        specialist = ReasoningSpecialist(config=None, llm=llm, tools=registry)
        token = CapabilityToken(
            specialist_id="reasoning",
            session_id="session",
            allowed_tools={"fs.search", "fs.read_file", "fs.list_dir"},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        events = []
        async for event in specialist.execute(
            contract=DelegationContract(specialist_id="reasoning"),
            token=token,
            prompt="Use web.search to find the latest ChatGPT release note and cite it.",
            conversation_context=[],
            memory_context="",
        ):
            events.append(event)

        # Naming a capability in natural language does not bypass the model.
        # The capability is offered, and the model remains the only component
        # that can choose a structured call.
        self.assertEqual(registry.calls, [])
        offered = {spec["function"]["name"] for spec in llm.calls[0]["tools"]}
        self.assertEqual(offered, {"web.search", "web.fetch"})
        self.assertFalse(any(event.get("type") == "tool_result" for event in events))
        visible = "".join(str(event.get("text") or "") for event in events if event.get("type") == "text")
        self.assertIn("July 9, 2026", visible)

    def test_reasoning_read_capabilities_authorize_only_matching_web_reads(self) -> None:
        full_read_token = CapabilityToken(
            specialist_id="reasoning",
            allowed_tools={"fs.read_file", "fs.list_dir", "fs.search"},
        )
        partial_read_token = CapabilityToken(
            specialist_id="reasoning",
            allowed_tools={"fs.read_file", "fs.search"},
        )

        self.assertTrue(full_read_token.permits_tool("web.search"))
        self.assertTrue(full_read_token.permits_tool("web.fetch"))
        self.assertFalse(partial_read_token.permits_tool("web.search"))
        self.assertFalse(partial_read_token.permits_tool("web.fetch"))

    def test_web_read_aliases_do_not_expand_non_reasoning_tokens(self) -> None:
        token = CapabilityToken(
            specialist_id="coding",
            allowed_tools={"fs.search", "fs.read_file"},
        )

        self.assertFalse(token.permits_tool("web.search"))
        self.assertFalse(token.permits_tool("web.fetch"))


if __name__ == "__main__":
    unittest.main()
