"""Phase 3.4: a failed install leaves nothing behind.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`.

The defect: ``install_agent_plugin_bytes`` writes the installed record *last*,
after copying the plugin tree, installing skills into the user's skills root and
registering MCP servers. A failure in between left those on disk with no record
naming them — and ``cleanup_agent_plugin_extras`` reads that record to know what
to remove, so nothing could ever reach them again.

These tests pin the transaction that fixes it, and the ordering property that
makes a rollback correct rather than merely present.
"""

from __future__ import annotations

import pytest

from thomas.server.install_transaction import InstallTransaction, install_transaction


def test_a_clean_run_keeps_its_effects() -> None:
    undone: list[str] = []

    with install_transaction("ok") as tx:
        tx.undo(lambda: undone.append("tree"))
        tx.undo(lambda: undone.append("skills"))

    assert undone == []


def test_a_failure_unwinds_everything_recorded() -> None:
    undone: list[str] = []

    with pytest.raises(RuntimeError, match="step three"):
        with install_transaction("boom") as tx:
            tx.undo(lambda: undone.append("tree"))
            tx.undo(lambda: undone.append("skills"))
            raise RuntimeError("step three exploded")

    assert undone == ["skills", "tree"]


def test_the_original_failure_still_reaches_the_caller() -> None:
    """A rollback must not swallow the reason it is running."""
    with pytest.raises(ValueError, match="the real problem"):
        with install_transaction("boom") as tx:
            tx.undo(lambda: None)
            raise ValueError("the real problem")


def test_effects_unwind_newest_first() -> None:
    """Order is the whole correctness argument: later effects may depend on earlier ones."""
    order: list[int] = []

    with pytest.raises(RuntimeError):
        with install_transaction("order") as tx:
            for step in range(4):
                tx.undo(lambda step=step: order.append(step))
            raise RuntimeError("fail")

    assert order == [3, 2, 1, 0]


def test_only_effects_that_actually_happened_are_reversed() -> None:
    """An undo recorded before its effect would delete work never done."""
    undone: list[str] = []

    with pytest.raises(RuntimeError):
        with install_transaction("partial") as tx:
            tx.undo(lambda: undone.append("tree"))
            # skills never installed, so no undo was recorded for them
            raise RuntimeError("failed before skills")

    assert undone == ["tree"]


def test_one_failing_reversal_does_not_strand_the_others() -> None:
    undone: list[str] = []

    def bad() -> None:
        raise OSError("could not remove")

    with pytest.raises(RuntimeError):
        with install_transaction("messy") as tx:
            tx.undo(lambda: undone.append("first"))
            tx.undo(bad)
            tx.undo(lambda: undone.append("third"))
            raise RuntimeError("fail")

    assert undone == ["third", "first"]


def test_rollback_after_commit_does_nothing() -> None:
    undone: list[str] = []
    tx = InstallTransaction("done")
    tx.undo(lambda: undone.append("tree"))
    tx.commit()

    assert tx.rollback() == []
    assert undone == []


def test_recording_an_undo_after_commit_is_refused() -> None:
    tx = InstallTransaction("done")
    tx.commit()
    with pytest.raises(RuntimeError):
        tx.undo(lambda: None)


def test_rollback_is_idempotent() -> None:
    undone: list[str] = []
    tx = InstallTransaction("twice")
    tx.undo(lambda: undone.append("tree"))

    tx.rollback()
    tx.rollback()

    assert undone == ["tree"]


# ---------------------------------------------------------------------------
# the install path is actually wrapped
# ---------------------------------------------------------------------------


def test_the_agent_plugin_install_records_undos_for_every_outside_effect() -> None:
    """Guards the wiring, not the transaction.

    The three effects that land outside the temp directory — the plugin tree,
    the skills, the MCP rows — must each have a reversal recorded, or a failed
    install orphans them exactly as before. Asserted on the source because
    standing up a real bundle install proves the same one fact far more slowly.
    """
    import inspect

    from thomas.server import agent_plugins_adapter

    source = inspect.getsource(agent_plugins_adapter.install_agent_plugin_bytes)

    assert "install_transaction(" in source, "install is no longer transactional"
    assert source.count("tx.undo(") >= 3, "an outside effect lost its reversal"
    # The record is still written inside the transaction, so a failure writing
    # it unwinds the rest rather than leaving a half-installed plugin.
    assert source.index("install_transaction(") < source.index("_replace_installed_record(")


@pytest.mark.parametrize(
    "function_name",
    ["install_bundled_plugin", "install_plugin_bundle_bytes"],
)
def test_the_desktop_install_paths_are_wrapped_too(function_name: str) -> None:
    """The same defect, in the installer next door.

    Both copy the plugin tree and write the installed record last. The record is
    the only handle anything has: ``uninstall_plugin`` needs an id it can only
    read from a record, and ``_prune_orphan_dependency_plugins`` iterates
    records rather than the filesystem. A failure in between therefore left a
    tree nothing could see or remove. ``install_plugin_from_store`` delegates to
    ``install_plugin_bundle_bytes`` and is covered by it.
    """
    import inspect

    from thomas.server import desktop_plugins_runtime

    source = inspect.getsource(getattr(desktop_plugins_runtime, function_name))

    assert "install_transaction(" in source, f"{function_name} is no longer transactional"
    assert "tx.undo(" in source, f"{function_name} copies a tree with no recorded reversal"
    assert source.index("install_transaction(") < source.index("_replace_installed_record(")
