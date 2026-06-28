"""Tests for the Forge Code "My Stuff" deliverables registry.

Core contract: a run that produced a coherent deliverable registers a My Stuff
entry that points back at the originating conversation, and a code-only run does
NOT register anything.
"""

from __future__ import annotations

from thomas.forge.anvil import forge_code_store
from thomas.forge.anvil.forge_code_deliverables import (
    deliverables_path,
    list_deliverables,
    register_from_run,
)


def test_deliverable_run_registers_entry_pointing_at_conversation(tmp_path):
    entry = register_from_run(
        tmp_path,
        conversation_id="fc_123",
        changed_files=["thomas/server/web/build/index.html", "thomas/util.py"],
        title="Landing page for the launch",
    )

    # A genuine deliverable was registered...
    assert entry is not None
    assert entry["conversation_id"] == "fc_123"
    assert entry["title"] == "Landing page for the launch"
    # ...featuring the HTML page (the detector promotes HTML to the front)...
    assert entry["kind"] == "html"
    assert entry["file"] == "thomas/server/web/build/index.html"
    # ...with a real, openable target and a deep-link back to the conversation.
    assert entry["open_url"] == ("/api/evolve/agent/artifact/fc_123/thomas/server/web/build/index.html")
    assert entry["deep_link"] == "/?forge_code=fc_123"

    # And it PERSISTS: a fresh read of the on-disk registry finds it.
    assert deliverables_path(tmp_path).exists()
    listed = list_deliverables(tmp_path)
    assert len(listed) == 1
    assert listed[0]["id"] == entry["id"]
    assert listed[0]["conversation_id"] == "fc_123"


def test_code_only_run_registers_nothing(tmp_path):
    # Only source files changed -> the detector finds no renderable output.
    assert forge_code_store.detect_artifacts(["thomas/a.py", "thomas/b.py"]) == []

    entry = register_from_run(
        tmp_path,
        conversation_id="fc_999",
        changed_files=["thomas/a.py", "thomas/b.py"],
        title="Refactor the loop",
    )

    assert entry is None
    assert list_deliverables(tmp_path) == []


def test_image_deliverable_uses_itself_as_thumbnail(tmp_path):
    entry = register_from_run(
        tmp_path,
        conversation_id="fc_img",
        changed_files=["assets/logo.png"],
        title="",  # blank title falls back to the filename
    )
    assert entry is not None
    assert entry["kind"] == "image"
    assert entry["title"] == "logo.png"
    assert entry["thumbnail"] == entry["open_url"]


def test_re_running_the_same_build_updates_not_duplicates(tmp_path):
    first = register_from_run(
        tmp_path,
        conversation_id="fc_dup",
        changed_files=["site/index.html"],
        title="First pass",
    )
    second = register_from_run(
        tmp_path,
        conversation_id="fc_dup",
        changed_files=["site/index.html"],
        title="Second pass",
    )

    listed = list_deliverables(tmp_path)
    assert len(listed) == 1  # same conversation + file -> one entry, upserted
    assert first["id"] == second["id"]
    assert listed[0]["title"] == "Second pass"
    # The original creation time is preserved across the update.
    assert second["created_at"] == first["created_at"]


def test_missing_underlying_file_is_reported_unavailable(tmp_path):
    # A genuine build wrote a REAL html file under the workspace root...
    built = tmp_path / "site" / "index.html"
    built.parent.mkdir(parents=True)
    built.write_text("<!doctype html><title>live</title>", encoding="utf-8")

    entry = register_from_run(
        tmp_path,
        conversation_id="fc_live",
        changed_files=["site/index.html"],
        title="Live build",
    )
    assert entry is not None

    # ...while the file is present, the deliverable lists as available (openable).
    live = list_deliverables(tmp_path)
    assert len(live) == 1
    assert live[0]["available"] is True

    # Now the built file is reverted/deleted out from under the registry...
    built.unlink()

    # ...the entry PERSISTS (its card greys, it does not vanish) but is reported
    # UNAVAILABLE, so the UI guards "Open" instead of serving a broken 404 target.
    dangling = list_deliverables(tmp_path)
    assert len(dangling) == 1
    assert dangling[0]["id"] == entry["id"]
    assert dangling[0]["available"] is False
    # The same open_url is still recorded -- availability, not the link, gates Open.
    assert dangling[0]["open_url"] == entry["open_url"]


def test_path_escaping_the_root_is_not_reported_available(tmp_path):
    # A deliverable whose recorded path tries to climb out of the workspace must
    # never be treated as a live, openable artifact.
    entry = register_from_run(
        tmp_path,
        conversation_id="fc_escape",
        changed_files=["../../etc/passwd.html"],
        title="Escape attempt",
    )
    assert entry is not None
    listed = list_deliverables(tmp_path)
    assert len(listed) == 1
    assert listed[0]["available"] is False


def test_empty_conversation_id_registers_nothing(tmp_path):
    assert (
        register_from_run(
            tmp_path,
            conversation_id="",
            changed_files=["index.html"],
            title="x",
        )
        is None
    )
    assert list_deliverables(tmp_path) == []
