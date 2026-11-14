"""Phase 3.4 — an installation that knows its own undo.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`.

Phase 3.2's idea was that a registration records its reversal, so teardown is
never a second implementation drifting out of step with setup. That idea is not
specific to in-process services, and this module is the proof: the same
``DisposalStack`` the kernel uses for event subscriptions works for effects that
land on disk.

**The defect it fixes.** ``install_agent_plugin_bytes`` performs five side
effects in order — copy the plugin tree, write its manifest, install skills into
the user's skills root, register MCP servers, and *last* write the installed
record. Nothing wraps them. So when a later step raises, the earlier ones stay:
a plugin directory and a set of skills exist on disk, but no installed record
was ever written. ``cleanup_agent_plugin_extras`` reads that record to know what
to remove, so it can never find them. The skills outlive the plugin
permanently, and no uninstall can reach them.

Under a transaction each effect pushes its undo the moment it succeeds. A
failure anywhere unwinds them in reverse and the install leaves nothing behind —
the same property ``Fork._apply`` gives a plugin that dies mid-mount.

**What rollback does not promise.** A failed *reinstall* leaves the plugin
uninstalled rather than restored to its previous version. That is deliberate:
the previous version's skills and MCP rows are removed before the new tree is
copied, so putting the old directory back would restore a plugin whose extras
are already gone — a worse lie than a clean absence.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from thomas.core.kernel import DisposalStack

log = logging.getLogger(__name__)


class InstallTransaction:
    """Effects recorded as they succeed, unwound in reverse if one fails."""

    def __init__(self, label: str = "install") -> None:
        self.label = label
        self._stack = DisposalStack()
        self._committed = False

    def __repr__(self) -> str:
        state = "committed" if self._committed else "open"
        return f"<InstallTransaction {self.label!r} {state}>"

    @property
    def committed(self) -> bool:
        return self._committed

    def undo(self, reversal: Callable[[], None]) -> None:
        """Record how to reverse the effect that just succeeded.

        Call this *after* the effect, never before: an undo recorded for
        something that then failed to happen is how a rollback deletes work it
        did not do.
        """
        if self._committed:
            raise RuntimeError(f"transaction {self.label!r} is already committed")
        self._stack.push(reversal)

    def commit(self) -> None:
        """Keep the effects. Recorded undos are dropped, not run."""
        self._committed = True

    def rollback(self) -> list[BaseException]:
        """Unwind every recorded effect, newest first.

        Returns the failures rather than raising them: a rollback is already
        running because something went wrong, and the original exception is the
        one the caller needs to see.
        """
        if self._committed:
            return []
        errors = self._stack.dispose()
        if errors:
            log.warning(
                "%d effect(s) could not be reversed while rolling back %r",
                len(errors),
                self.label,
            )
        return errors


@contextmanager
def install_transaction(label: str = "install") -> Iterator[InstallTransaction]:
    """Run a body whose effects reverse themselves if it raises.

        with install_transaction("my-plugin") as tx:
            copy_the_tree()
            tx.undo(lambda: remove_the_tree())
            register_the_rows()
            tx.undo(lambda: remove_the_rows())

    Leaving the block normally commits. Any exception rolls back first and then
    propagates unchanged, so the caller still sees the real failure.
    """
    transaction = InstallTransaction(label)
    try:
        yield transaction
    except BaseException as exc:
        log.warning("%s failed (%s); rolling back everything it had done", label, exc)
        transaction.rollback()
        raise
    transaction.commit()
