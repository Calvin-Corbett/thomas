"""One board, one lock, and a write that refuses a stale snapshot.

Messages were vanishing from plans/thomas/WORKBOARD.md minutes after being
delivered, with no error and no ack. Measured 2026-09-09: sha 3642ddeb (1609
lines) -> 727b3493 (1611 lines, a message arrived) -> 3642ddeb, byte-identical
to the earlier state.

Three causes, all verified by reading the tree:

1. `board_io.validated_update` -- the only writer that refuses a stale read
   snapshot -- had ZERO callers. `grep -rn validated_update` returned its own
   definition and nothing else. The protection existed and was never wired up.
2. Every board mutation instead went through `issue._validate_and_write`, which
   wrote the whole file with no lock and, on a validation failure, wrote
   `original_text` back -- erasing anything delivered in between.
3. There were THREE lock files for one board: workboard.lock (board_io),
   workboard_claim.lock (claim_utils) and workboard_message.lock (message). A
   message send and a claim write never excluded each other, so each could
   revert the other's whole-file write.

board_io's lock is reentrant per thread, which is what lets the hub take it
while callers that already hold it nest instead of deadlocking. That nesting is
the risk this change introduces, so it is tested directly.
"""

from __future__ import annotations

import threading
from pathlib import Path

from scripts.crew.workboard import board_io, claim_utils
from scripts.crew.workboard import issue as workboard_issue
from scripts.crew.workboard import message as message_core

BOARD = (
    "# Thomas Workboard\n\n## Agent Claims\n\n- none\n\n## Active Tasks\n\n- none\n\n"
    "## Issues / Blockers\n\n- none\n\n## Up For Grabs\n\n- none\n"
)


def test_every_board_writer_uses_the_same_lock_file() -> None:
    """Separate lock files mean no mutual exclusion at all."""
    assert board_io.LOCK_FILE == message_core.LOCK_FILE
    assert board_io.LOCK_FILE == claim_utils.LOCK_FILE


def test_the_hub_takes_the_lock_and_nesting_does_not_deadlock(tmp_path: Path) -> None:
    """The regression this change could introduce: a caller already holding the
    lock calls the hub, which takes it again."""
    board = tmp_path / "WORKBOARD.md"
    board.write_text(BOARD, encoding="utf-8")
    new_text = BOARD.replace("## Up For Grabs\n\n- none\n", "## Up For Grabs\n\n- none\n\n")

    done: list[tuple[bool, list[str]]] = []

    def nested() -> None:
        with board_io.file_lock():  # a caller that already holds it
            done.append(
                workboard_issue._validate_and_write(
                    board, BOARD, new_text, require_claims_to_have_active_task=False
                )
            )

    t = threading.Thread(target=nested)
    t.start()
    t.join(20.0)
    assert not t.is_alive(), "nested board write deadlocked on the shared lock"
    assert done and done[0][0] is True, done


def test_a_write_built_on_a_stale_snapshot_is_refused(tmp_path: Path) -> None:
    """The defect this file exists for: the rollback wrote back a board that
    predated another agent's message, and nothing noticed."""
    board = tmp_path / "WORKBOARD.md"
    board.write_text(BOARD, encoding="utf-8")
    stale = BOARD.replace("- none", "- stale snapshot", 1)

    ok, violations = workboard_issue._validate_and_write(
        board, stale, BOARD, require_claims_to_have_active_task=False
    )
    assert ok is False
    assert any("changed during update" in str(v) for v in violations), violations
    assert board.read_text(encoding="utf-8") == BOARD, "a refused write must not touch the board"
