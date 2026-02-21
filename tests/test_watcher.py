\
from pathlib import Path

import pytest

pytest.importorskip("watchdog")

from thomas.watcher.api import patch_watcher_section
from thomas.watcher.ingest import ingest_file, WatcherConfig, is_supported_file


def test_patch_watcher_section_inserts_when_missing():
    original = "[server]\nport = 8000\n"
    cfg = WatcherConfig(paths=["A", "B"])
    patched = patch_watcher_section(original, cfg)
    assert "[watcher]" in patched
    assert '"A"' in patched and '"B"' in patched
    assert "enabled = true" in patched
    assert "[server]" in patched


def test_patch_watcher_section_updates_existing_and_preserves_unknown():
    original = """
[server]
port = 8000

[watcher]
paths = ["OLD1", "OLD2"]
other_key = 1

[other]
x = 2
""".lstrip()
    cfg = WatcherConfig(paths=["NEW"], enabled=False, recursive=True)
    patched = patch_watcher_section(original, cfg)
    assert '"NEW"' in patched
    assert "OLD1" not in patched and "OLD2" not in patched
    assert "other_key = 1" in patched
    assert "enabled = false" in patched
    assert "recursive = true" in patched


def test_supported_file_override_exts(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_text("hi", encoding="utf-8")
    assert is_supported_file(str(f), include_exts=[".bin"]) is True
    assert is_supported_file(str(f), include_exts=["bin"]) is False  # must include dot in override list after load/normalize


def test_ingest_text_file_indexes_and_persistent_dedup(monkeypatch, tmp_path: Path):
    f = tmp_path / "note.txt"
    f.write_text("hello thomas\n", encoding="utf-8")

    calls = {"n": 0}

    def fake_index(path: str, text: str, metadata: dict):
        calls["n"] += 1

    import thomas.watcher.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "index_into_library", fake_index)

    config_path = str(tmp_path / "thomas.toml")
    cfg = WatcherConfig(paths=[str(tmp_path)], dedupe=True, max_file_size_mb=8, max_hash_bytes_mb=8)

    r1 = ingest_file(str(f), config_path=config_path, cfg=cfg)
    assert r1.indexed is True
    assert calls["n"] == 1

    r2 = ingest_file(str(f), config_path=config_path, cfg=cfg)
    assert r2.indexed is False
    assert r2.skipped is True
    assert calls["n"] == 1


