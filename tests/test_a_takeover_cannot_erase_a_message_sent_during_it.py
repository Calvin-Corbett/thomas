"""A takeover transaction holds the board lock for its whole operation.

Measured on the live board 2026-09-09: sha 3642ddeb (1609 lines) -> 727b3493
(1611 lines, a message was delivered) -> 3642ddeb, byte-identical to the earlier
state. The message written in between was gone, with no error and no ack. Two
coordination messages died that way inside two minutes, and a codex agent
independently reported "Workboard restoration lost acknowledged recovery
instructions".

Eight concurrent `message.py --send` processes against a scratch board all
survived, so the send path does not race. The loss came from a multi-step
operation that captured the board, wrote, and on failure restored what it had
captured -- with no lock held ACROSS those steps. Its rollback does check that
the board still matches what it wrote, but the check and the restore are two
operations, so the guard narrows the window rather than closing it.

These tests pin the property that closes it: while the transaction runs, no
other writer can take the board lock.
"""

from __future__ import annotations

import threading

from scripts.crew.workboard import takeover_transaction as mod
from scripts.crew.workboard.board_io import LOCK_FILE, file_lock


def _lock_is_free_to_another_thread(timeout: float = 0.4) -> bool:
    """Whether a DIFFERENT thread can take the board lock right now.

    The lock is reentrant per thread, so asking from this thread would always
    say yes and prove nothing.
    """
    got: list[bool] = []

    def attempt() -> None:
        try:
            with file_lock(LOCK_FILE, timeout):
                got.append(True)
        except (TimeoutError, OSError):
            got.append(False)

    t = threading.Thread(target=attempt)
    t.start()
    t.join(timeout + 2.0)
    return bool(got and got[0])


def test_the_lock_is_free_when_no_transaction_runs() -> None:
    """Control: without this the next test could pass on a permanently held lock."""
    assert _lock_is_free_to_another_thread() is True


def test_no_other_writer_can_touch_the_board_mid_transaction() -> None:
    """The regression this file exists for.

    check_barrier is called between the transaction's steps -- exactly where
    another agent's delivery used to slip in -- so it is the honest place to ask
    whether the board is still exclusively held.
    """
    observed: list[bool] = []

    def check_barrier(_token: str) -> None:
        observed.append(_lock_is_free_to_another_thread())
        raise RuntimeError("stop the transaction here; the barrier is the probe")

    ok, _message = mod.execute_takeover_transaction(
        workboard_path=_board(),
        original_text=_board().read_text(encoding="utf-8"),
        intermediate_text="",
        successor_text="",
        agent="probe",
        holders=(),
        task="",
        scope="probe",
        reason="",
        authorization_id="",
        evidence={},
        validate_write=lambda *_a, **_k: (True, []),
        append_audit=lambda *_a, **_k: None,
        check_barrier=check_barrier,
        require_claims_to_have_active_task=False,
        allow_blocked_without_issue=True,
    )
    assert ok is False  # the barrier stopped it on purpose
    assert observed, "check_barrier never ran; the probe proved nothing"
    assert observed[0] is False, (
        "another writer could take the board lock mid-transaction; a message "
        "delivered there is what the rollback erases"
    )


def test_the_public_entry_point_takes_the_lock() -> None:
    """Renaming or re-exporting the unlocked body would silently undo this."""
    import inspect

    src = inspect.getsource(mod.execute_takeover_transaction)
    assert "file_lock()" in src
    assert "_execute_takeover_transaction_unlocked" in src


def _board():
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "plans" / "thomas" / "WORKBOARD.md"
