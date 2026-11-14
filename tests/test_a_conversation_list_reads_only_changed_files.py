"""Listing Code conversations reads again only the files that changed (2026-10-27).

Every listing read and parsed every conversation file, transcripts and all: 26 to 177 s for 709 files on a busy
2026-10-27, holding a server thread the whole time.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_store, forge_code_summary_cache


def _conversation(cid: str, title: str, turns: int = 3) -> dict[str, object]:
    return {
        "id": cid,
        "title": title,
        "created_at": "2026-10-27T10:00:00+00:00",
        "updated_at": f"2026-10-27T10:00:0{cid[-1]}+00:00",
        "turns": [{"role": "agent", "model": "m", "text": "x" * 2000} for _ in range(turns)],
    }


@pytest.fixture(autouse=True)
def _fresh() -> None:
    forge_code_summary_cache.forget()


def test_a_second_listing_reads_no_file_and_a_change_is_read_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(3):
        forge_code_store.write_conversation(tmp_path, _conversation(f"fc_{i}", f"title {i}"))
    first = forge_code_store.list_conversations(tmp_path)
    loads: list[str] = []
    real = forge_code_store.load_conversation

    def counted(root: str | Path, cid: str) -> dict | None:
        loads.append(cid)
        return real(root, cid)

    monkeypatch.setattr(forge_code_store, "load_conversation", counted)
    assert forge_code_store.list_conversations(tmp_path) == first and loads == []
    time.sleep(0.05)
    forge_code_store.write_conversation(tmp_path, _conversation("fc_1", "renamed", turns=5))
    third = forge_code_store.list_conversations(tmp_path)
    assert loads == ["fc_1"]
    renamed = next(row for row in third if row["id"] == "fc_1")
    assert renamed["title"] == "renamed" and renamed["turn_count"] == 5


def test_a_cached_listing_is_what_an_uncached_one_says(tmp_path: Path) -> None:
    for i in range(4):
        forge_code_store.write_conversation(tmp_path, _conversation(f"fc_{i}", f"title {i}", turns=i + 1))
    cached = forge_code_store.list_conversations(tmp_path)
    forge_code_summary_cache.forget()
    assert forge_code_store.list_conversations(tmp_path) == cached
    assert forge_code_store.list_conversations(tmp_path) == cached
