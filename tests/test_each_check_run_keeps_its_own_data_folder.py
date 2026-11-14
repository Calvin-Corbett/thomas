"""Two checks of one change never share a data folder, so one finishing cannot delete what the other still reads.

Every check kept its reports and selection files in <data root>/<execution id> and removed that folder when it ended.
tests/test_a_change_is_checked_before_your_card.py and tests/test_every_hand_in_records_its_clocks.py check the same
execution id, and the shards of a real check share one temporary folder, so the first to finish deleted the other's
selection file: "pytest exited 4 ... shard-1.select.json ... FileNotFoundError" (d79480, 2026-10-28), a failure with
nothing to do with the change. On 2026-10-29 three of four such tests failed run side by side, and passed one by one.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.server.precard import check, slot

GREEN = SimpleNamespace(execution_id="thomas-same", blue="blue")


@pytest.fixture
def quiet_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The check around its data folder, with no copies, no sweep and room on the disk."""
    monkeypatch.setenv(slot.DATA_ROOT_ENV, str(tmp_path / "data"))
    monkeypatch.setattr(check.slot, "clear_leftovers", lambda _age: [])
    monkeypatch.setattr(check.slot, "too_little_room", lambda *_a, **_k: "")
    monkeypatch.setattr(check.scratch, "copy_of_dev", lambda *_a: SimpleNamespace(work="copy"))
    monkeypatch.setattr(check.scratch, "discard_all", lambda *_a: None)


def _run() -> check.Checked:
    return check._against_dev(GREEN, "tip", "patch", ["pkg/adder.py"], "python", True)


@pytest.mark.usefixtures("quiet_check")
def test_a_check_ending_beside_another_of_the_same_change_leaves_its_files_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folders: list[Path] = []
    survived: list[bool] = []

    def steps(*args: object) -> check.Checked:
        data = Path(args[7])  # _steps(green, tip, patch, changed, python, base, with_change, data, ...)
        folders.append(data)
        selection = data / "base" / "reports" / "shard-1.select.json"
        selection.parent.mkdir(parents=True, exist_ok=True)
        selection.write_text("{}", encoding="utf-8")
        if len(folders) == 1:  # the second check of this change starts and ends while the first still runs
            _run()
        survived.append(selection.is_file())  # not an assert: _against_dev holds any exception as "unavailable"
        return check.Checked(check.PASSED, "")

    monkeypatch.setattr(check, "_steps", steps)

    assert _run().state == check.PASSED
    assert survived == [True, True]
    assert folders[0] != folders[1]


@pytest.mark.usefixtures("quiet_check")
def test_each_run_cleans_up_after_itself_and_its_folder_names_the_change(monkeypatch: pytest.MonkeyPatch) -> None:
    folders: list[Path] = []

    def steps(*args: object) -> check.Checked:
        data = Path(args[7])
        data.mkdir(parents=True)
        folders.append(data)
        return check.Checked(check.PASSED, "")

    monkeypatch.setattr(check, "_steps", steps)
    _run()

    assert folders[0].parent == slot.data_root() and folders[0].name.startswith("thomas-same-")
    assert list(slot.data_root().iterdir()) == []
