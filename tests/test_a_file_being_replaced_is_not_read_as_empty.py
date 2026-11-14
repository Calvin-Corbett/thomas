"""A file that cannot be read for a moment is waited for, not read as empty.

Windows refuses a read while another thread replaces the file. Measured under contention, 8% of plain reads failed that
way, and three readers took the failure for "nothing there". The conversation registry read as empty, so the next bind
wrote back one row and every other conversation lost its project. A green's hand-off record read as empty, so the next
hand-in reused an id and was refused with "submission already exists". A conversation read as missing, so a repair
round read as having nowhere to go.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.core import atomic_json
from thomas.forge.anvil import forge_code_conversations, forge_code_store
from thomas.server import green_handoff

THREADS = 2
SAVES = 400


@pytest.fixture
def refused_once(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The first read of each file is refused, as Windows refuses it during a replace."""
    real, refused = Path.read_text, []

    def read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.name not in refused:
            refused.append(self.name)
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    return refused


def test_the_registry_keeps_its_rows(tmp_path: Path, refused_once: list[str]) -> None:
    forge_code_conversations._write_registry(tmp_path, {"fc_kept": {"project_root": "somewhere"}})

    assert "fc_kept" in forge_code_conversations._load_registry(tmp_path)
    assert refused_once == ["project_registry.json"]


def test_a_conversation_is_still_there(tmp_path: Path, refused_once: list[str]) -> None:
    conversation = forge_code_store.new_conversation(tmp_path, title="Read at the wrong moment")

    assert forge_code_store.load_conversation(tmp_path, conversation["id"])["id"] == conversation["id"]
    assert refused_once


def test_a_hand_off_record_keeps_its_ids(tmp_path: Path, refused_once: list[str]) -> None:
    green_handoff._save(SimpleNamespace(git_dir=tmp_path), {"keep": True, "sids": ["self-x"]})

    assert green_handoff._read_state(tmp_path)["sids"] == ["self-x"]
    assert refused_once == [green_handoff.HANDOFF_NAME]


def test_a_file_that_stays_refused_still_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(self: Path, *args: object, **kwargs: object) -> str:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(Path, "read_text", refused)
    monkeypatch.setattr(atomic_json, "REPLACE_BACKOFF_SECONDS", 0)

    with pytest.raises(PermissionError):
        atomic_json.read_text_with_retry(tmp_path / "held.json")


def test_two_writers_of_the_registry_never_share_a_temporary_file(tmp_path: Path) -> None:
    together = threading.Barrier(THREADS)
    failed: list[OSError] = []

    def write(writer: int) -> None:
        together.wait()
        for n in range(SAVES):
            try:
                forge_code_conversations._write_registry(tmp_path, {f"fc_{writer}": {"n": n}})
            except OSError as exc:
                failed.append(exc)

    threads = [threading.Thread(target=write, args=(writer,)) for writer in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not failed, failed[:3]
    folder = forge_code_conversations._registry_path(tmp_path).parent
    assert [path.name for path in folder.iterdir()] == ["project_registry.json"], "nothing stranded beside it"
