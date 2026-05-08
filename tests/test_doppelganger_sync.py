from __future__ import annotations

from pathlib import Path


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_sync_tree_mirrors_and_deletes(tmp_path: Path) -> None:
    from thomas.forge.anvil.doppelganger import _sync_tree

    src = tmp_path / "src"
    dst = tmp_path / "dst"

    _write(src / "a.txt", "one")
    _write(src / "nested" / "b.txt", "two")

    _write(dst / "extra.txt", "delete-me")
    _write(dst / "__pycache__" / "x.pyc", "cache")

    _sync_tree(src, dst)

    assert (dst / "a.txt").read_text(encoding="utf-8") == "one"
    assert (dst / "nested" / "b.txt").read_text(encoding="utf-8") == "two"
    assert not (dst / "extra.txt").exists()
    assert not (dst / "__pycache__").exists()

    # Updates propagate
    _write(src / "a.txt", "changed")
    _sync_tree(src, dst)
    assert (dst / "a.txt").read_text(encoding="utf-8") == "changed"

