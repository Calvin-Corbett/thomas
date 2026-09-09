from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.llm import LLMError, TokenUsage
from thomas.core.llm_streaming_codex import _build_openai_codex_request, _responses_input_from_messages
from thomas.core.tokens import estimate_messages_tokens, fit_messages_to_hard_cap
from thomas.tools.registry import ToolRegistry


class _LLM:
    def __init__(self, context_window: int = 2048) -> None:
        self.config = ModelConfig(
            name="openai_codex",
            provider="openai_codex",
            model="gpt-5.6-sol",
            context_window=context_window,
            max_tokens=128,
        )
        self.session_usage = TokenUsage()


class _ResponsesOwner:
    config = SimpleNamespace(model="gpt-5.6-sol", reasoning_effort="xhigh")

    def _sanitize_tool_name(self, name: str) -> str:
        return name.replace(".", "_")


def _large_write_exchange(call_id: str = "call_big") -> list[dict[str, object]]:
    arguments = json.dumps({"path": "index.html", "content": "x" * 30_000})
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "fs.write_file", "arguments": arguments},
                }
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "content": "Wrote 30000 chars to index.html"},
    ]


def test_agent_loop_preserves_nonempty_paired_responses_input_after_large_write() -> None:
    config = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    conversation = [
        {"role": "user", "content": "Build a polished browser game and verify it."},
        *_large_write_exchange(),
    ]
    agent = AgentLoop(config, _LLM(), ToolRegistry(), conversation=conversation, memory=None)

    messages = agent._build_messages(
        SimpleNamespace(token_estimate=0),
        memory_text="",
        tool_specs=[],
        include_purpose=False,
        include_autonomy_profile=False,
        include_editing_policy=False,
        include_project_instructions=False,
    )
    _instructions, items = _responses_input_from_messages(_ResponsesOwner(), messages)

    assert estimate_messages_tokens(messages) <= 2048
    assert any(item.get("role") == "user" for item in items)
    calls = [item for item in items if item.get("type") == "function_call"]
    outputs = [item for item in items if item.get("type") == "function_call_output"]
    assert [item["call_id"] for item in calls] == ["call_big"]
    assert [item["call_id"] for item in outputs] == ["call_big"]
    compacted = json.loads(calls[0]["arguments"])
    assert compacted["path"] == "index.html"
    assert compacted["original_chars"] > 30_000


def test_hard_cap_drops_old_tool_exchange_atomically_and_keeps_latest_user() -> None:
    old_turn = [{"role": "user", "content": "old request"}, *_large_write_exchange("call_old")]
    latest = {"role": "user", "content": "Now explain the current status."}

    fitted = fit_messages_to_hard_cap(
        [{"role": "system", "content": "s" * 3250}, *old_turn, latest],
        hard_cap=1000,
    )
    _instructions, items = _responses_input_from_messages(_ResponsesOwner(), fitted)

    assert any(item.get("role") == "user" and "current status" in str(item.get("content")) for item in items)
    declared = {str(item.get("call_id")) for item in items if item.get("type") == "function_call"}
    assert all(str(item.get("call_id")) in declared for item in items if item.get("type") == "function_call_output")
    assert not any(item.get("call_id") == "call_old" for item in items)
    assert estimate_messages_tokens(fitted) <= 1000


def test_hard_cap_restores_user_anchor_when_soft_trim_left_only_orphan_output() -> None:
    source = [{"role": "user", "content": "Keep this task alive."}, *_large_write_exchange()]
    fitted = fit_messages_to_hard_cap(
        [
            {"role": "system", "content": "system"},
            {"role": "tool", "tool_call_id": "call_big", "content": "done"},
        ],
        hard_cap=1000,
        anchor_source=source,
    )
    _instructions, items = _responses_input_from_messages(_ResponsesOwner(), fitted)

    assert items == [{"role": "user", "content": "Keep this task alive."}]
    assert estimate_messages_tokens(fitted) <= 1000


def test_hard_cap_rejects_oversized_required_context_without_truncating_policy() -> None:
    marker = "CRITICAL_POLICY_MARKER_DO_NOT_REMOVE"
    messages = [
        {"role": "system", "content": f"{'system rules ' * 900}\n{marker}\n{'guardrails ' * 900}"},
        {"role": "user", "content": "latest request " * 1200},
    ]

    with pytest.raises(ValueError, match="Required system/developer instructions and latest user request"):
        fit_messages_to_hard_cap(messages, hard_cap=2048)

    assert marker in messages[0]["content"]
    assert messages[1]["content"] == "latest request " * 1200


def test_hard_cap_preserves_system_policy_between_conversation_turns() -> None:
    marker = "MID_CONVERSATION_POLICY_MARKER_DO_NOT_REMOVE"
    fitted = fit_messages_to_hard_cap(
        [
            {"role": "system", "content": "base policy"},
            {"role": "user", "content": "obsolete request"},
            {"role": "assistant", "content": "disposable history " * 2000},
            {"role": "system", "content": marker},
            {"role": "user", "content": "latest request"},
        ],
        hard_cap=1000,
    )

    assert [message["content"] for message in fitted if message["role"] == "system"] == [
        "base policy",
        marker,
    ]
    assert fitted[-1] == {"role": "user", "content": "latest request"}


def test_hard_cap_preserves_mid_history_developer_instruction_byte_for_byte() -> None:
    developer = {"role": "developer", "content": "DEVELOPER_POLICY_DO_NOT_DROP"}
    fitted = fit_messages_to_hard_cap(
        [
            {"role": "system", "content": "base policy"},
            {"role": "user", "content": "obsolete request"},
            {"role": "assistant", "content": "disposable history " * 300},
            developer,
            {"role": "user", "content": "latest request"},
        ],
        hard_cap=100,
    )

    assert developer in fitted
    assert fitted[-1] == {"role": "user", "content": "latest request"}


def test_hard_cap_preserves_every_developer_instruction() -> None:
    developer_messages = [
        {"role": "developer", "content": "first developer policy"},
        {"role": "developer", "content": "second developer policy"},
    ]
    fitted = fit_messages_to_hard_cap(
        [
            {"role": "system", "content": "base policy"},
            developer_messages[0],
            {"role": "user", "content": "obsolete request"},
            {"role": "assistant", "content": "disposable history " * 300},
            developer_messages[1],
            {"role": "user", "content": "latest request"},
        ],
        hard_cap=100,
    )

    assert [message for message in fitted if message["role"] == "developer"] == developer_messages


def test_hard_cap_rejects_oversized_required_developer_instruction() -> None:
    developer = {"role": "developer", "content": "required policy " * 1000}

    with pytest.raises(ValueError, match="Required system/developer instructions and latest user request"):
        fit_messages_to_hard_cap([developer, {"role": "user", "content": "latest request"}], hard_cap=100)

    assert developer["content"] == "required policy " * 1000


def test_codex_transport_keeps_developer_content_in_instructions() -> None:
    instructions, items = _responses_input_from_messages(
        _ResponsesOwner(),
        [
            {"role": "system", "content": "system policy"},
            {"role": "developer", "content": "developer policy"},
            {"role": "user", "content": "owner request"},
        ],
    )

    assert instructions == "system policy\ndeveloper policy"
    assert items == [{"role": "user", "content": "owner request"}]


def test_codex_transport_restores_real_user_anchor_after_tool_only_compaction() -> None:
    owner = _ResponsesOwner()
    compacted = _build_openai_codex_request(
        owner,
        [
            {"role": "system", "content": "policy"},
            {"role": "tool", "tool_call_id": "orphaned", "content": "read result"},
        ],
        None,
        turn_user_content="Build the Viking game.",
    )

    assert compacted["input"] == [{"role": "user", "content": "Build the Viking game."}]
    assert not any("anchor" in key for key in vars(owner))


def test_codex_transport_restores_user_anchor_after_matched_tool_history() -> None:
    body = _build_openai_codex_request(
        _ResponsesOwner(),
        [
            {
                "role": "assistant",
                "content": "I inspected the first file.",
                "tool_calls": [
                    {
                        "id": "call-read",
                        "function": {"name": "fs.read_file", "arguments": '{"path":"index.html"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-read", "content": "<main>Trey</main>"},
        ],
        None,
        turn_user_content="Finish and verify all three game files.",
    )

    assert body["input"] == [
        {"role": "assistant", "content": "I inspected the first file."},
        {
            "type": "function_call",
            "call_id": "call-read",
            "name": "fs_read_file",
            "arguments": '{"path":"index.html"}',
        },
        {"type": "function_call_output", "call_id": "call-read", "output": "<main>Trey</main>"},
        {"role": "user", "content": "Finish and verify all three game files."},
    ]


def test_codex_transport_places_current_anchor_after_stale_surviving_user() -> None:
    body = _build_openai_codex_request(
        _ResponsesOwner(),
        [
            {"role": "user", "content": "OLD unrelated request"},
            {"role": "assistant", "content": "I am still working."},
        ],
        None,
        turn_user_content="CURRENT Viking game request",
    )

    assert body["input"] == [
        {"role": "user", "content": "OLD unrelated request"},
        {"role": "assistant", "content": "I am still working."},
        {"role": "user", "content": "CURRENT Viking game request"},
    ]


def test_codex_transport_does_not_duplicate_matching_current_anchor() -> None:
    body = _build_openai_codex_request(
        _ResponsesOwner(),
        [{"role": "user", "content": "CURRENT Viking game request"}],
        None,
        turn_user_content="CURRENT Viking game request",
    )

    assert body["input"] == [{"role": "user", "content": "CURRENT Viking game request"}]


def test_codex_transport_never_reuses_another_turns_user_anchor() -> None:
    owner = _ResponsesOwner()
    _build_openai_codex_request(
        owner,
        [{"role": "user", "content": "TOP_SECRET_A"}],
        None,
        turn_user_content="TOP_SECRET_A",
    )

    with pytest.raises(LLMError, match="no usable current-turn input"):
        _build_openai_codex_request(
            owner,
            [{"role": "tool", "tool_call_id": "orphaned", "content": "done"}],
            None,
        )

    assert "TOP_SECRET_A" not in repr(vars(owner))


def test_codex_transport_normalizes_explicit_multimodal_turn_anchor() -> None:
    owner = _ResponsesOwner()
    body = _build_openai_codex_request(
        owner,
        [{"role": "tool", "tool_call_id": "orphaned", "content": "done"}],
        None,
        turn_user_content=[
            {"type": "text", "text": "Inspect this image."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc", "detail": "high"}},
        ],
    )

    assert body["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Inspect this image."},
                {"type": "input_image", "image_url": "data:image/png;base64,abc", "detail": "high"},
            ],
        }
    ]
    assert "data:image" not in repr(vars(owner))


def test_codex_transport_rejects_empty_explicit_multimodal_anchor() -> None:
    invalid_anchors = [
        [{"type": "text", "text": "   "}, {"type": "image_url", "image_url": {"url": ""}}],
        [{}],
        [{"type": "bogus"}],
        [0],
        [False],
    ]
    for anchor in invalid_anchors:
        with pytest.raises(LLMError, match="no usable current-turn input"):
            _build_openai_codex_request(
                _ResponsesOwner(),
                [{"role": "tool", "tool_call_id": "orphaned", "content": "done"}],
                None,
                turn_user_content=anchor,
            )


def test_codex_transport_rejects_unusable_current_anchor_beside_stale_user() -> None:
    invalid_anchors = [
        "   ",
        [{"type": "text", "text": "   "}],
        [{"type": "bogus", "payload": "CURRENT_SECRET"}],
    ]
    stale_history = [{"role": "user", "content": "STALE_ONLY"}]

    for anchor in invalid_anchors:
        with pytest.raises(LLMError, match="no usable current-turn input"):
            _build_openai_codex_request(
                _ResponsesOwner(),
                stale_history,
                None,
                turn_user_content=anchor,
            )


def _tool_specs(count: int, *, description_chars: int) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": f"tool_{index}",
                "description": "d" * description_chars,
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string", "description": "p" * description_chars}},
                },
            },
        }
        for index in range(count)
    ]


def test_agent_loop_rejects_tool_schemas_that_exhaust_the_provider_window() -> None:
    config = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    agent = AgentLoop(
        config,
        _LLM(context_window=2048),
        ToolRegistry(),
        conversation=[{"role": "user", "content": "Use the right tool and explain the result."}],
        memory=None,
    )

    with pytest.raises(ValueError, match="tool-schema tokens"):
        agent._build_messages(
            SimpleNamespace(token_estimate=0),
            memory_text="",
            tool_specs=_tool_specs(80, description_chars=250),
            include_purpose=False,
            include_autonomy_profile=False,
            include_editing_policy=False,
            include_project_instructions=False,
        )


def test_agent_loop_total_context_includes_tools_and_response_reserve() -> None:
    context_window = 2048
    llm = _LLM(context_window=context_window)
    config = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    agent = AgentLoop(
        config,
        llm,
        ToolRegistry(),
        conversation=[{"role": "user", "content": "Summarize this result."}],
        memory=None,
    )
    state = SimpleNamespace(token_estimate=0)

    agent._build_messages(
        state,
        memory_text="",
        tool_specs=_tool_specs(1, description_chars=32),
        include_purpose=False,
        include_autonomy_profile=False,
        include_editing_policy=False,
        include_project_instructions=False,
    )

    response_reserve = min(llm.config.max_tokens, context_window // 4)
    assert state.token_estimate + response_reserve <= context_window


def test_agent_loop_drops_optional_memory_before_required_system_policy() -> None:
    marker = "CRITICAL_POLICY_MARKER_DO_NOT_REMOVE"
    llm = _LLM(context_window=2048)
    config = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    agent = AgentLoop(
        config,
        llm,
        ToolRegistry(),
        system_prompt=marker,
        conversation=[{"role": "user", "content": "Complete this safely."}],
        memory=None,
    )
    state = SimpleNamespace(token_estimate=0)

    messages = agent._build_messages(
        state,
        memory_text="OPTIONAL_MEMORY_MARKER " * 1000,
        tool_specs=[],
        include_purpose=False,
        include_autonomy_profile=False,
        include_editing_policy=False,
        include_project_instructions=False,
    )

    assert marker in messages[0]["content"]
    assert "OPTIONAL_MEMORY_MARKER" not in messages[0]["content"]
    assert state.token_estimate + llm.config.max_tokens <= llm.config.context_window
