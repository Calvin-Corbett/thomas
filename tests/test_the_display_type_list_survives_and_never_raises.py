"""The list of block types you switched off: saved in the data folder, and a broken file means every type is on."""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.core import display_types


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path))
    return tmp_path


def test_a_type_switched_off_stays_off_and_back_on_leaves_the_list() -> None:
    assert display_types.disabled() == []
    assert display_types.set_enabled("table", False) == ["table"]
    assert display_types.disabled() == ["table"]
    assert display_types.set_enabled("table", True) == []
    assert display_types.disabled() == []


def test_a_broken_file_means_every_type_is_on() -> None:
    display_types.types_path().write_text("{not json", encoding="utf-8")
    assert display_types.disabled() == []
    display_types.types_path().write_text('{"disabled": "table"}', encoding="utf-8")
    assert display_types.disabled() == []


def test_a_bad_type_name_is_refused() -> None:
    with pytest.raises(ValueError):
        display_types.set_enabled("../table", False)
    assert display_types.disabled() == []
