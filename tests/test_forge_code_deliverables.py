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
    list_deliverables_across,
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


def test_deliverables_are_found_in_the_projects_they_were_built_in(tmp_path):
    """My Stuff must look where the builds are, not only at the catalog root.

    ``register_from_run`` writes ``deliverables.json`` into the PROJECT the run
    worked in. Since every Code task now gets its own folder, that is almost
    never the catalog root -- and the endpoint read the catalog root alone, so
    it answered with an empty list and the Library showed nothing.

    Measured on a live workspace before this change: 16 deliverables existed
    across 4 project roots and ``/api/evolve/agent/deliverables`` returned 0,
    including two apps built minutes earlier that both open and work.

    An empty list is exactly what "you have not built anything" looks like, so
    nothing anywhere reported a problem.
    """

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    project_a = tmp_path / "project-a"
    project_a.mkdir()
    project_b = tmp_path / "project-b"
    project_b.mkdir()
    for project, cid, title in (
        (project_a, "fc_a", "Countdown timer"),
        (project_b, "fc_b", "Tip calculator"),
    ):
        (project / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
        assert register_from_run(project, conversation_id=cid, changed_files=["index.html"], title=title)

    # Nothing was ever written to the catalog root -- that is the whole point.
    assert not deliverables_path(catalog).exists()

    found = list_deliverables_across(catalog, [project_a, project_b])
    titles = {entry["title"] for entry in found}
    assert titles == {"Countdown timer", "Tip calculator"}
    # Availability must be judged against the project each entry came from,
    # or every entry greys out as a dangling artifact.
    assert all(entry["available"] is True for entry in found)


def test_the_same_deliverable_in_two_roots_is_listed_once(tmp_path):
    """Roots overlap in practice, so a merge must not double-count.

    ``conversation_roots`` returns the catalog, the shared drawer and every
    registered project; a build recorded in a root reachable two ways would
    otherwise appear twice in the Library.
    """

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    register_from_run(project, conversation_id="fc_dup", changed_files=["index.html"], title="Only once")

    found = list_deliverables_across(catalog, [project, project, catalog])
    assert [entry["title"] for entry in found] == ["Only once"]
