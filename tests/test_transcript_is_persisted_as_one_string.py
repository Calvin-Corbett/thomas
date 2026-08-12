"""A turn's transcript persists as ONE string, and a list-shaped one still reads.

Measured (w2-code-explain sweep, 2026-08-06): a persisted GPT turn arrived with
its transcript shaped as 2541 single-character array entries -- ``['{', '"',
'f', 'c', ...]`` -- instead of the one string every consumer is written for.
The store (``forge_code_store.append_agent_turn``) persisted whatever shape its
caller handed it, so one badly-shaped caller poisoned the durable record: any
consumer iterating transcript entries as events saw characters, and the store's
own reader (``_agent_reply_text``) ran the list through ``str()`` -- producing
``"['{', ...]"`` where no line starts with ``{``, so every forge event
vanished and the agent's produced answer fell out of history.

Two contracts, both against the store:

1. WRITE: ``append_agent_turn`` normalizes a list-shaped transcript (characters
   or lines) back into the one string it always meant to store. Nothing is
   dropped or rejected -- the same content, in the persistable shape.
2. READ: a conversation already on disk with a list-shaped transcript (written
   before the normalization existed) still yields its events -- existing data
   must keep rendering.
"""

from __future__ import annotations

import json

from thomas.forge.anvil.forge_code_store import (
    append_agent_turn,
    append_user_turn,
    conversations_dir,
    history_turns,
    new_conversation,
)

# The real stored shape: forge-event JSON lines mixed with the dispatch CLI's
# own echo, exactly as evolve_agent_runtime hands it over after a run.
TRANSCRIPT = "\n".join(
    [
        json.dumps({"fc": "tool_result", "name": "code.project_structure", "text": "empty project", "is_error": False}),
        json.dumps({"fc": "say", "text": "Looking at the project now."}),
        json.dumps({"fc": "final", "text": "THE-ANSWER: this project is empty."}),
    ]
)


def _appended_turn(root, transcript):
    conv = new_conversation(root, title="shape check")
    cid = conv["id"]
    append_user_turn(root, cid, "look at the project")
    append_agent_turn(
        root,
        cid,
        model="gpt-5.6-terra",
        transcript=transcript,
        changed_files=[],
        returncode=1,
        ok=False,
        noop=False,
        reason="exited 1",
    )
    on_disk = json.loads((conversations_dir(root) / f"{cid}.json").read_text(encoding="utf-8"))
    return cid, on_disk["turns"][-1]


def test_a_character_list_transcript_is_stored_as_the_one_string_it_was(tmp_path):
    """The measured bug shape: list(text) -- thousands of one-char entries."""
    _, turn = _appended_turn(tmp_path, list(TRANSCRIPT))
    assert isinstance(turn["transcript"], str)
    assert turn["transcript"] == TRANSCRIPT


def test_a_line_list_transcript_is_stored_as_newline_joined_text(tmp_path):
    """The other plausible list shape: one entry per event line."""
    _, turn = _appended_turn(tmp_path, TRANSCRIPT.split("\n"))
    assert isinstance(turn["transcript"], str)
    assert turn["transcript"] == TRANSCRIPT


def test_a_string_transcript_is_stored_verbatim(tmp_path):
    """Control: the correct shape passes through untouched."""
    _, turn = _appended_turn(tmp_path, TRANSCRIPT)
    assert turn["transcript"] == TRANSCRIPT


def test_history_still_reads_a_list_shaped_transcript_already_on_disk(tmp_path):
    """Existing data must keep rendering: a conversation persisted BEFORE the
    writer normalization, with its transcript as a character array, still
    yields the agent's final answer to the prompt composer."""
    cid, _ = _appended_turn(tmp_path, TRANSCRIPT)
    # Corrupt the durable record into the measured legacy shape by hand -- the
    # writer no longer produces it, but files like this exist.
    path = conversations_dir(tmp_path) / f"{cid}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["turns"][-1]["transcript"] = list(TRANSCRIPT)
    path.write_text(json.dumps(data), encoding="utf-8")
    append_user_turn(tmp_path, cid, "and now?")

    turns = history_turns(tmp_path, cid)
    replies = [t["text"] for t in turns if t["role"] == "assistant"]
    assert replies == ["THE-ANSWER: this project is empty."]
