"""Tests for the disk-persistent Forge Code conversation store."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from thomas.forge.anvil.forge_code_store import (
    append_agent_turn,
    append_user_turn,
    conversations_dir,
    delete_conversation,
    derive_title,
    detect_artifacts,
    group_by_day,
    history_turns,
    list_conversations,
    load_conversation,
    new_conversation,
    rename_conversation,
)


def test_new_conversation_writes_file_and_returns_dict(tmp_path):
    conv = new_conversation(tmp_path, title="Add a hello function")
    assert conv["id"]
    assert conv["title"] == "Add a hello function"
    assert conv["turns"] == []
    assert conv["created_at"] == conv["updated_at"]

    # The JSON file exists on disk under the conversations dir.
    path = conversations_dir(tmp_path) / f"{conv['id']}.json"
    assert path.exists()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["id"] == conv["id"]


def test_derive_title_real_and_empty():
    assert derive_title("Add a hello function") == "Add a hello function"
    assert derive_title("") == "Untitled build"
    assert derive_title("   \n  ") == "Untitled build"
    # First non-empty line wins; long titles are truncated with an ellipsis.
    assert derive_title("\n\nSecond line is the title") == "Second line is the title"
    long_title = derive_title("x" * 200)
    assert long_title.endswith("…")
    assert len(long_title) <= 61


def test_history_turns_extracts_clean_multi_turn_text(tmp_path):
    """history_turns yields a plain user/assistant transcript for the prompt:

    * user text verbatim,
    * the agent's reply pulled from its `say` forge events (NOT tool calls/results),
    * and the CURRENT (final) user turn dropped so it is not duplicated as the goal.
    """
    conv = new_conversation(tmp_path)
    cid = conv["id"]
    append_user_turn(tmp_path, cid, "hi")
    # An agent transcript as it is really stored: forge-event JSON lines (a say plus
    # a tool call) mixed with the dispatch CLI's own echo. Only the say is history.
    transcript = "\n".join(
        [
            json.dumps({"fc": "say", "text": "Hey! How can I help?"}),
            json.dumps({"fc": "tool", "name": "Read", "text": "file_path: a.py"}),
            "NO-OP (claude ran but changed nothing): nothing to review",
        ]
    )
    append_agent_turn(
        tmp_path,
        cid,
        model="claude:sonnet",
        transcript=transcript,
        changed_files=[],
        returncode=0,
        ok=False,
        noop=True,
        reason="no change made",
    )
    append_user_turn(tmp_path, cid, "now add a hello function")  # the current turn

    hist = history_turns(tmp_path, cid)
    # The current user turn is dropped; the prior pair survives as clean text.
    assert hist == [
        {"role": "user", "text": "hi"},
        {"role": "assistant", "text": "Hey! How can I help?"},
    ]
    # Tool plumbing and CLI echo never leak into the assistant's history text.
    assert "file_path" not in hist[1]["text"]
    assert "NO-OP" not in hist[1]["text"]


def test_detect_artifacts_only_for_renderable_output():
    """The artifact detector emits a descriptor for a RENDERABLE file (html/image/
    markdown/data) and NOTHING for a code-only run -- an ordinary edit never gets a
    fabricated preview. An HTML page is promoted to the front as the headline."""
    # A run that wrote an HTML page yields exactly one html artifact descriptor.
    arts = detect_artifacts(["site/index.html"])
    assert arts == [{"file": "site/index.html", "kind": "html", "ext": "html"}]

    # A .py-only run produces NO artifact card -- the diff card stays the output.
    assert detect_artifacts(["thomas/server/foo.py"]) == []
    assert detect_artifacts([]) == []
    assert detect_artifacts(None) == []

    # Each renderable family is classified, and HTML sorts ahead of the rest.
    mixed = detect_artifacts(["data/rows.csv", "notes.md", "chart.png", "app/index.html", "thomas/x.py"])
    assert mixed[0]["kind"] == "html"  # html promoted to the front
    kinds = {a["file"]: a["kind"] for a in mixed}
    assert kinds == {
        "app/index.html": "html",
        "chart.png": "image",
        "notes.md": "markdown",
        "data/rows.csv": "data",
    }
    assert "thomas/x.py" not in kinds  # code is never an artifact

    # Finished document families are first-class output artifacts too.
    documents = detect_artifacts(["report.pdf", "brief.docx", "forecast.xlsx", "deck.pptx", "notes.txt"])
    assert {artifact["file"]: artifact["kind"] for artifact in documents} == {
        "report.pdf": "pdf",
        "brief.docx": "document",
        "forecast.xlsx": "spreadsheet",
        "deck.pptx": "presentation",
    }


def test_agent_turn_records_artifacts_for_html_not_for_code(tmp_path):
    """A recorded agent turn carries the artifact descriptors so a resumed
    conversation re-renders the preview; a code-only turn carries an empty list."""
    conv = new_conversation(tmp_path)
    cid = conv["id"]
    append_user_turn(tmp_path, cid, "build a landing page")
    append_agent_turn(
        tmp_path,
        cid,
        model="claude:sonnet",
        transcript="built",
        changed_files=["index.html", "thomas/x.py"],
        returncode=0,
        ok=True,
        noop=False,
        reason="2 file(s) changed",
    )
    turn = load_conversation(tmp_path, cid)["turns"][-1]
    assert turn["artifacts"] == [{"file": "index.html", "kind": "html", "ext": "html"}]

    # A code-only build records no artifacts.
    append_user_turn(tmp_path, cid, "tweak the server")
    append_agent_turn(
        tmp_path,
        cid,
        model="claude:sonnet",
        transcript="done",
        changed_files=["thomas/server/foo.py"],
        returncode=0,
        ok=True,
        noop=False,
        reason="1 file changed",
    )
    assert load_conversation(tmp_path, cid)["turns"][-1]["artifacts"] == []


def test_history_turns_unknown_conversation_is_empty(tmp_path):
    assert history_turns(tmp_path, "does-not-exist") == []
    assert history_turns(tmp_path, "") == []


def test_turns_persist_with_title_and_model(tmp_path):
    conv = new_conversation(tmp_path)
    assert conv["title"] == "Untitled build"

    # First user message titles the conversation.
    after_user = append_user_turn(tmp_path, conv["id"], "Add a hello function")
    assert after_user["title"] == "Add a hello function"

    append_agent_turn(
        tmp_path,
        conv["id"],
        model="claude:opus",
        transcript="done",
        changed_files=["thomas/x.py"],
        returncode=0,
        ok=True,
        noop=False,
        reason="dispatched via claude CLI (1 file changed)",
    )

    loaded = load_conversation(tmp_path, conv["id"])
    assert [t["role"] for t in loaded["turns"]] == ["user", "agent"]
    assert loaded["turns"][0]["text"] == "Add a hello function"
    assert loaded["turns"][1]["model"] == "claude:opus"
    assert loaded["turns"][1]["changed_files"] == ["thomas/x.py"]


def test_rename_conversation_sets_title_without_reordering(tmp_path):
    """Rename relabels in place: the title changes but updated_at is preserved so
    the conversation keeps its position in the history list."""
    conv = new_conversation(tmp_path, title="Original label")
    original_updated_at = conv["updated_at"]

    renamed = rename_conversation(tmp_path, conv["id"], "  A clearer name  ")
    assert renamed is not None
    assert renamed["title"] == "A clearer name"  # trimmed
    assert renamed["updated_at"] == original_updated_at  # NOT bumped

    # Persisted to disk, not just returned.
    assert load_conversation(tmp_path, conv["id"])["title"] == "A clearer name"


def test_rename_conversation_caps_length_and_defaults_blank(tmp_path):
    conv = new_conversation(tmp_path, title="Start")
    long_title = rename_conversation(tmp_path, conv["id"], "y" * 200)
    assert long_title["title"].endswith("…")
    assert len(long_title["title"]) <= 61

    blank = rename_conversation(tmp_path, conv["id"], "   ")
    assert blank["title"] == "Untitled build"


def test_rename_missing_conversation_returns_none(tmp_path):
    assert rename_conversation(tmp_path, "fc_nope_000000", "x") is None


def test_delete_conversation_removes_file_and_is_idempotent(tmp_path):
    conv = new_conversation(tmp_path, title="Doomed")
    cid = conv["id"]
    path = conversations_dir(tmp_path) / f"{cid}.json"
    assert path.exists()

    # First delete removes the file and drops it from the listing.
    assert delete_conversation(tmp_path, cid) is True
    assert not path.exists()
    assert load_conversation(tmp_path, cid) is None
    assert all(s["id"] != cid for s in list_conversations(tmp_path))

    # Deleting an already-gone conversation is a safe False, never a raise.
    assert delete_conversation(tmp_path, cid) is False
    assert delete_conversation(tmp_path, "fc_never_existed") is False


def test_load_missing_returns_none(tmp_path):
    assert load_conversation(tmp_path, "fc_nope_000000") is None
    assert append_user_turn(tmp_path, "fc_nope_000000", "hi") is None


def test_list_conversations_sorted_with_counts(tmp_path):
    older = new_conversation(tmp_path, title="Older")
    newer = new_conversation(tmp_path, title="Newer")

    # Make `older` genuinely older, then give `newer` two turns.
    _force_updated_at(tmp_path, older["id"], "2026-06-20T10:00:00+00:00")
    append_user_turn(tmp_path, newer["id"], "do a thing")
    append_agent_turn(
        tmp_path,
        newer["id"],
        model="claude:sonnet",
        transcript="ok",
        changed_files=[],
        returncode=0,
        ok=True,
        noop=False,
        reason="no changes",
    )

    summaries = list_conversations(tmp_path)
    assert [s["id"] for s in summaries] == [newer["id"], older["id"]]
    newer_summary = summaries[0]
    assert newer_summary["turn_count"] == 2
    assert newer_summary["last_model"] == "claude:sonnet"
    assert summaries[1]["turn_count"] == 0
    assert summaries[1]["last_model"] == ""


def test_persistence_across_restart(tmp_path):
    conv = new_conversation(tmp_path)
    append_user_turn(tmp_path, conv["id"], "Build it")
    append_agent_turn(
        tmp_path,
        conv["id"],
        model="claude:opus",
        transcript="built",
        changed_files=["a.py"],
        returncode=0,
        ok=True,
        noop=False,
        reason="ok",
    )

    # Simulate a server restart: no in-memory cache, read straight from disk.
    reloaded = load_conversation(tmp_path, conv["id"])
    assert len(reloaded["turns"]) == 2
    assert reloaded["turns"][0]["text"] == "Build it"
    assert reloaded["turns"][1]["transcript"] == "built"


def test_group_by_day_buckets_relative_to_now(tmp_path):
    now = datetime(2026, 6, 24, 16, 0, 0, tzinfo=timezone.utc)
    summaries = [
        {"id": "a", "updated_at": "2026-06-24T09:00:00+00:00"},  # today
        {"id": "b", "updated_at": "2026-06-23T22:00:00+00:00"},  # yesterday
        {"id": "c", "updated_at": "2026-06-01T08:00:00+00:00"},  # older
    ]
    groups = group_by_day(summaries, now=now)
    assert [g["day"] for g in groups] == ["Today", "Yesterday", "2026-06-01"]
    assert groups[0]["items"][0]["id"] == "a"
    assert groups[1]["items"][0]["id"] == "b"
    assert groups[2]["items"][0]["id"] == "c"


def _force_updated_at(root, cid, updated_at: str) -> None:
    """Test helper: rewrite a conversation's updated_at on disk."""
    conv = load_conversation(root, cid)
    conv["updated_at"] = updated_at
    path = conversations_dir(root) / f"{cid}.json"
    path.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
