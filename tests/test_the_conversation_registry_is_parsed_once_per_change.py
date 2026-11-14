"""The Build conversation registry is parsed once per change to its file, and every caller still gets its own copy.

Measured 2026-11-06: each lookup parsed the whole registry (536 rows, 1.37 MB, 27.7 ms) from 23 call sites, while the
server read about 1 GB from disk every two minutes. Regression for the parse cache in
thomas.forge.anvil.forge_code_conversations._load_registry.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_conversations as conversations


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[int]]:
    conversations.reset_conversation_roots_cache()
    path = conversations._registry_path(tmp_path)
    path.write_text(json.dumps({"c1": {"project_root": "A", "settings": {"model": "x"}}}), encoding="utf-8")
    parses: list[int] = []
    real = conversations._parse_registry

    def counted(*args, **kwargs):
        parses.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(conversations, "_parse_registry", counted)
    return tmp_path, parses


def test_an_unchanged_registry_is_parsed_once(catalog: tuple[Path, list[int]]) -> None:
    root, parses = catalog
    for _ in range(5):
        assert conversations._load_registry(root)["c1"]["project_root"] == "A"
    assert len(parses) == 1


def test_each_caller_gets_a_copy_of_its_own(catalog: tuple[Path, list[int]]) -> None:
    root, _parses = catalog
    first = conversations._load_registry(root)
    first["c1"]["settings"]["model"] = "changed by one caller"
    first["c2"] = {"project_root": "B"}
    again = conversations._load_registry(root)
    assert again == {"c1": {"project_root": "A", "settings": {"model": "x"}}}


def test_a_write_here_is_read_back(catalog: tuple[Path, list[int]]) -> None:
    root, _parses = catalog
    registry = conversations._load_registry(root)
    registry["c2"] = {"project_root": "B", "settings": {}}
    conversations._write_registry(root, registry)
    assert set(conversations._load_registry(root)) == {"c1", "c2"}


def test_a_change_by_another_process_is_read_back(catalog: tuple[Path, list[int]]) -> None:
    root, parses = catalog
    conversations._load_registry(root)
    path = conversations._registry_path(root)
    path.write_text(json.dumps({"c9": {"project_root": "Z"}}), encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000))  # a later timestamp, as another writer leaves
    assert set(conversations._load_registry(root)) == {"c9"}
    assert len(parses) == 2
