"""A check copy left by an earlier try that Windows still holds open never stops the next check.

On 2026-11-04 the gates change and the voice settings panel both stopped before your approval card with
"[WinError 32] The process cannot access the file because it is being used by another process:
...precard-thomas-...-change", the voice one four times. Each retry first removed the copy its last try had
left, and the removal raised because something still had that folder open, so the check never ran.

Now the retry ends what the last try left running in that copy, removes it, and when Windows still refuses,
marks it for the sweep and checks in a fresh copy beside it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from thomas.server import green_checkout, green_handoff
from thomas.server.precard import scratch


def _wire(monkeypatch, *, held: bool) -> SimpleNamespace:
    seen = SimpleNamespace(ended=[], removed=[], settled=[], created=[])
    taken = {scratch.scratch_id("thomas-x", scratch.WITH_CHANGE)}  # the copy the last try left behind

    def find_green(name: str):
        return SimpleNamespace(execution_id=name) if name in taken else None

    def remove_green(green) -> None:
        seen.removed.append(green.execution_id)
        if held:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        taken.discard(green.execution_id)

    def create_green(*, blue: Path, execution_id: str, checkout_tip: str):
        seen.created.append(execution_id)
        taken.add(execution_id)
        return SimpleNamespace(execution_id=execution_id)

    monkeypatch.setattr(green_checkout, "find_green", find_green)
    monkeypatch.setattr(green_checkout, "remove_green", remove_green)
    monkeypatch.setattr(green_checkout, "create_green", create_green)
    monkeypatch.setattr(green_checkout, "mark_settled", lambda green: seen.settled.append(green.execution_id))
    monkeypatch.setattr(green_handoff, "end_green_processes", lambda name: seen.ended.append(name))
    return seen


def test_a_held_leftover_copy_is_left_for_the_sweep_and_the_check_gets_a_fresh_one(monkeypatch) -> None:
    seen = _wire(monkeypatch, held=True)
    name = scratch.scratch_id("thomas-x", scratch.WITH_CHANGE)

    copy = scratch.copy_of_dev(Path("blue"), "tip", "thomas-x", scratch.WITH_CHANGE)

    assert seen.ended == [name], "what the last try left running in its copy is ended first"
    assert seen.settled == [name], "the copy Windows still holds is left for the sweep to take"
    assert copy.execution_id != name and copy.execution_id.startswith(scratch.PREFIX)
    assert len(copy.execution_id) <= 80


def test_a_leftover_copy_that_can_go_is_replaced_under_its_own_name(monkeypatch) -> None:
    seen = _wire(monkeypatch, held=False)
    name = scratch.scratch_id("thomas-x", scratch.WITH_CHANGE)

    copy = scratch.copy_of_dev(Path("blue"), "tip", "thomas-x", scratch.WITH_CHANGE)

    assert seen.removed == [name] and seen.settled == []
    assert copy.execution_id == name
