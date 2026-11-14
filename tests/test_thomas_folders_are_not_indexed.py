"""Windows Search leaves Thomas's own busy folders alone (2026-10-28).

Windows Search used 18-19% of your processor re-indexing the files Thomas writes every few seconds, and a product
cannot ask you to stop it. Thomas marks his own folders not to be indexed (no administrator needed); what he writes
inside them later inherits the mark.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from thomas.core import unindexed

pytestmark = pytest.mark.skipif(os.name != "nt", reason="a Windows file attribute")


def _marked(path: Path) -> bool:
    return bool(os.stat(path).st_file_attributes & unindexed.NOT_CONTENT_INDEXED)


def test_every_folder_is_marked_and_what_is_made_later_inherits_it(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "old.txt").write_text("x", encoding="utf-8")

    assert unindexed.mark_folders([root, tmp_path / "missing"]) == [str(root)]

    assert all(_marked(folder) for folder in (root, root / "a", root / "a" / "b"))
    later = root / "a" / "b" / "new"
    later.mkdir()
    (later / "log.txt").write_text("x", encoding="utf-8")
    assert _marked(later) and _marked(later / "log.txt"), "made inside a marked folder, so never indexed"
    assert (root / unindexed.DONE).is_file()


def test_a_root_already_walked_is_not_walked_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    (root / unindexed.DONE).write_text("done\n", encoding="utf-8")

    def no_walk(*_args, **_kwargs):
        raise AssertionError("walked again")

    monkeypatch.setattr(unindexed.os, "walk", no_walk)

    assert unindexed.mark_folders([root]) == []
    assert _marked(root)


def test_the_folders_are_thomass_own() -> None:
    checkout = Path(unindexed.__file__).resolve().parents[2]
    folders = unindexed.thomas_folders()
    assert folders[:2] == [checkout / "runtime", checkout / ".thomas"]
    assert checkout not in folders, "the checkout itself, your code, is never marked"
