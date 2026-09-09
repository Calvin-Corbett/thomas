"""Token-progressive streaming for Forge Code's transcript.

These cover the Performance fixes that make the transcript stream like a frontier
agent rather than in ~400ms quantized blocks:

  * the claude invocation asks for partial messages so prose arrives as token
    deltas, and the translator maps each ``content_block_delta`` text delta to an
    incremental ``say`` (``delta: True``) WITHOUT swallowing inter-token spaces;
  * the deltas SUPPRESS the duplicate complete text block that follows (the deltas
    already carried it) so prose renders exactly once, not twice;
  * the GPT in-process path forwards ``TEXT_DELTA`` promptly (not buffered to the
    next tool boundary) and does not re-emit the same text as a whole block;
  * the SSE payload carries the ``delta`` flag through to the browser;
  * a multibyte glyph split across two reads still decodes to the real char (never
    ``�``) — the incremental decoder must hold the partial sequence across the
    delta boundary.
"""

import json


def test_claude_cmd_requests_partial_messages(tmp_path):
    """The live claude invocation must opt into token-progressive partial messages.

    Needs a REAL repository to dispatch into. This used to pass ``cwd="/repo"``,
    a path that exists nowhere, and a later guard began refusing to dispatch
    into a workspace ``git status`` cannot inspect -- so the run was refused
    before the injected runner was ever reached and the test failed with a bare
    ``KeyError: 'cmd'``, which says nothing about why. The guard is right; the
    fixture had simply never been updated to satisfy it.
    """
    import subprocess

    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    captured = {}

    def runner(cmd, cwd, to):
        captured["cmd"] = cmd
        return 0, ""

    dispatch_via_claude_cli("do x", cwd=str(tmp_path), dry_run=False, runner=runner, claude_bin="claude")
    assert "cmd" in captured, "the runner was never reached; dispatch refused before invoking claude"
    cmd = captured["cmd"]
    assert "--include-partial-messages" in cmd
    # It only makes sense alongside the structured stream-json + verbose flags.
    assert "stream-json" in cmd and "--verbose" in cmd


def test_stream_event_text_delta_becomes_progressive_say():
    """A ``content_block_delta`` text delta maps to an incremental ``say`` delta."""
    from thomas.forge.anvil.evolve_claude_bridge import translate_claude_event

    out = translate_claude_event(
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello"},
                },
            }
        )
    )
    assert out == [{"fc": "say", "text": "Hello", "delta": True}]


def test_text_delta_preserves_inter_token_spaces():
    """Delta text is forwarded RAW — a leading space token is never stripped away."""
    from thomas.forge.anvil.evolve_claude_bridge import translate_claude_event

    out = translate_claude_event(
        json.dumps(
            {
                "type": "stream_event",
                "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " world"}},
            }
        )
    )
    assert out == [{"fc": "say", "text": " world", "delta": True}]


def test_non_text_block_deltas_are_ignored():
    """Thinking/tool-arg deltas are NOT forwarded as say (they flush as whole blocks)."""
    from thomas.forge.anvil.evolve_claude_bridge import translate_claude_event

    for dtype in ("thinking_delta", "input_json_delta"):
        out = translate_claude_event(
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": dtype, "thinking": "x", "partial_json": "{"},
                    },
                }
            )
        )
        assert out == []


def test_partial_deltas_suppress_the_duplicate_complete_block():
    """After streaming token deltas, the COMPLETE assistant text block is dropped.

    With one stateful translator (the live path), the deltas carry the prose live;
    re-emitting the whole block would double the message. The shared run state lets
    the complete block be suppressed so it renders exactly once.
    """
    from thomas.forge.anvil.evolve_claude_bridge import ClaudeStreamTranslator

    tr = ClaudeStreamTranslator()
    d1 = tr(
        json.dumps(
            {
                "type": "stream_event",
                "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "I'll "}},
            }
        )
    )
    d2 = tr(
        json.dumps(
            {
                "type": "stream_event",
                "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "edit it."}},
            }
        )
    )
    # the complete block for the SAME text arrives right after the deltas
    whole = tr(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "I'll edit it."}]}}))

    assert d1 == [{"fc": "say", "text": "I'll ", "delta": True}]
    assert d2 == [{"fc": "say", "text": "edit it.", "delta": True}]
    assert whole == []  # suppressed — the deltas already carried it


def test_complete_block_emitted_when_no_deltas_preceded_it():
    """Backward-compatible: with NO partial deltas, the whole block still emits.

    The buffered fallback (tests / injection) and any client without partial
    messages must keep getting the complete ``say`` block.
    """
    from thomas.forge.anvil.evolve_claude_bridge import ClaudeStreamTranslator

    tr = ClaudeStreamTranslator()
    whole = tr(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}}))
    assert whole == [{"fc": "say", "text": "Done."}]


def test_gpt_path_streams_progressive_say_deltas_then_does_not_duplicate():
    """The in-process GPT translator forwards TEXT_DELTA promptly, no double-emit.

    Each token is emitted as a ``say`` delta as it arrives (not buffered to the
    tool boundary), and the boundary flush does not re-emit the same prose as a
    whole block.
    """
    from thomas.core.events import EventType
    from thomas.forge.anvil.evolve_claude_bridge import _AgentLoopForgeTranslator

    events: list[dict] = []
    tr = _AgentLoopForgeTranslator(events.append)
    tr.feed(EventType.TEXT_DELTA.value, {"text": "Editing "})
    tr.feed(EventType.TEXT_DELTA.value, {"text": "now."})
    # the deltas surfaced IMMEDIATELY, before any boundary
    says = [e for e in events if e.get("fc") == "say"]
    assert says == [
        {"fc": "say", "text": "Editing ", "delta": True},
        {"fc": "say", "text": "now.", "delta": True},
    ]
    # a tool boundary flushes — but must NOT re-emit the streamed prose as a block
    tr.feed(EventType.TOOL_START.value, {"tool_name": "fs.write_file", "args": {"file_path": "a.py"}})
    block_says = [e for e in events if e.get("fc") == "say" and not e.get("delta")]
    assert block_says == []  # nothing re-emitted as a whole block
    assert any(e.get("fc") == "tool" for e in events)


def test_line_to_sse_payload_forwards_the_delta_flag():
    """The SSE layer carries the ``delta`` flag so the browser appends incrementally."""
    from thomas.server.routes.evolve_agent_routes import _line_to_sse_payload

    payload = _line_to_sse_payload(json.dumps({"fc": "say", "text": "tok", "delta": True}))
    assert payload["type"] == "output"
    assert payload["kind"] == "say"
    assert payload["text"] == "tok"
    assert payload["delta"] is True

    # a whole-block say carries no delta flag (the browser renders it as a block)
    whole = _line_to_sse_payload(json.dumps({"fc": "say", "text": "done"}))
    assert "delta" not in whole


def test_multibyte_glyph_split_across_two_deltas_still_renders():
    """An em-dash whose 3 bytes straddle a read boundary decodes to ``—``, not ``�``.

    The incremental decoder must hold the partial multibyte sequence until the
    bytes that complete it arrive on the next feed — so a glyph split across two
    streamed chunks is never mangled into the replacement char.
    """
    from thomas.forge.anvil.evolve_claude_bridge import _HybridByteDecoder

    dec = _HybridByteDecoder()
    emdash = "—".encode()  # b"\xe2\x80\x94"
    out = dec.feed(emdash[:2])  # first delta ends mid-glyph
    out += dec.feed(emdash[2:])  # second delta completes it
    out += dec.flush()
    assert out == "—"
    assert "�" not in out
