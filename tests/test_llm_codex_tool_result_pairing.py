"""Codex/Responses API tool-call <-> tool-output pairing invariant.

The Responses API rejects a ``function_call_output`` whose ``call_id`` has no
matching ``function_call`` earlier in the same request, returning HTTP 400
("No tool call found for function call output with call_id ..."). That 400
kills the entire worker turn and forces a failover to an often-unauthenticated
provider, leaving a real task hung in 'executing' with no deliverable.

History trimming (dropping the assistant tool-call message while keeping its
tool result) and streamed tool_calls that arrive without a ``name`` both orphan
an output that way. ``_responses_input_from_messages`` defensively drops the
orphan so a long multi-tool task survives. These tests lock that in.
"""

from __future__ import annotations

import json

from thomas.core.llm_streaming_codex import _responses_input_from_messages


class _Owner:
    def _sanitize_tool_name(self, name: str) -> str:
        # Mirror the real sanitizer: dots are illegal in Responses tool names.
        return name.replace(".", "_")


def test_orphaned_tool_output_is_dropped() -> None:
    """A tool result whose declaring assistant message was trimmed must not be sent."""
    owner = _Owner()
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "build a game"},
        # The assistant message that declared call_x was trimmed out of history.
        {"role": "tool", "tool_call_id": "call_x", "content": "wrote index.html"},
        {"role": "user", "content": "continue"},
    ]
    _instructions, items = _responses_input_from_messages(owner, messages)
    assert not any(i.get("type") == "function_call_output" for i in items), (
        "orphaned function_call_output (no matching function_call) must be dropped"
    )


def test_paired_call_and_output_are_preserved() -> None:
    """A properly paired tool call + result survives intact, names sanitized."""
    owner = _Owner()
    messages = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_y", "function": {"name": "fs.write_file", "arguments": json.dumps({"path": "x"})}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_y", "content": "ok"},
    ]
    _instructions, items = _responses_input_from_messages(owner, messages)
    call = next((i for i in items if i.get("type") == "function_call" and i.get("call_id") == "call_y"), None)
    output = next((i for i in items if i.get("type") == "function_call_output" and i.get("call_id") == "call_y"), None)
    assert call is not None, "declared function_call must be preserved"
    assert output is not None, "matching function_call_output must be preserved"
    assert call["name"] == "fs_write_file", "tool name must be sanitized for the Responses API"


def test_tool_call_missing_name_orphans_then_drops_output() -> None:
    """A streamed tool_call with no name is skipped; its now-orphaned output drops too."""
    owner = _Owner()
    messages = [
        {"role": "user", "content": "go"},
        # name never arrived in the stream -> the function_call cannot be emitted.
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_z", "function": {"arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_z", "content": "result"},
    ]
    _instructions, items = _responses_input_from_messages(owner, messages)
    assert not any(i.get("type") == "function_call" for i in items)
    assert not any(i.get("type") == "function_call_output" for i in items), (
        "output for an un-emitted call must be dropped, not sent orphaned"
    )


def test_chat_style_image_blocks_are_normalized_for_responses() -> None:
    """The Codex OAuth transport must send Responses-native multimodal input."""
    owner = _Owner()
    data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is shown?"},
                {
                    "type": "image_url",
                    "image_url": {"url": data_url, "detail": "high"},
                },
            ],
        }
    ]

    _instructions, items = _responses_input_from_messages(owner, messages)

    assert items == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "What is shown?"},
                {"type": "input_image", "image_url": data_url, "detail": "high"},
            ],
        }
    ]


def test_responses_native_image_blocks_remain_native() -> None:
    owner = _Owner()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Inspect it."},
                {"type": "input_image", "image_url": "https://example.test/image.png"},
            ],
        }
    ]

    _instructions, items = _responses_input_from_messages(owner, messages)

    assert items[0]["content"] == messages[0]["content"]
