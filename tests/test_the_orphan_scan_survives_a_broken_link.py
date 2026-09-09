"""The orphan scan must not crash a verify pass on a path it cannot stat (2026-09-06).

Every self-edit run on the Thomas checkout was filed as failed at the start
of its second pass with "[WinError 1920] The file cannot be accessed by the
system: ...runtime/doppelganger/venvs/green/lib64": a Linux venv link copied
onto Windows. ``orphaned_web_assets`` walked the whole checkout with rglob and
called ``is_file()`` before it pruned anything; that stat raised, the pass
crashed, and three landed self-edits were recorded as failures. The scan now
prunes the folders it never wanted and treats a path it cannot stat as absent.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from thomas.tools import web_preflight


def _project(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text('<script src="app.js"></script>', encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('hi')", encoding="utf-8")
    (tmp_path / "dead.js").write_text("export const x = 1", encoding="utf-8")
    venv = tmp_path / "runtime" / "doppelganger" / "venvs" / "green"
    venv.mkdir(parents=True)
    (venv / "lib64").write_text("", encoding="utf-8")  # stands in for the broken link
    (venv / "site.js").write_text("dead.js", encoding="utf-8")  # a mention that must NOT count
    return tmp_path


def test_a_path_whose_stat_raises_does_not_crash_the_scan(tmp_path: Path, monkeypatch: Any) -> None:
    root = _project(tmp_path)
    real_stat = os.stat

    def exploding_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        if str(path).endswith("lib64"):
            raise OSError(1920, "The file cannot be accessed by the system")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", exploding_stat)
    orphans = web_preflight.orphaned_web_assets(root, ["app.js", "dead.js"])
    assert len(orphans) == 1 and orphans[0].startswith("dead.js")


def test_the_scan_never_reads_inside_runtime_or_venv_folders(tmp_path: Path, monkeypatch: Any) -> None:
    root = _project(tmp_path)
    opened: list[str] = []
    real_read = Path.read_text

    def spy_read(self: Path, *args: Any, **kwargs: Any) -> str:
        opened.append(str(self))
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read)
    orphans = web_preflight.orphaned_web_assets(root, ["dead.js"])
    assert len(orphans) == 1 and orphans[0].startswith("dead.js")  # the venv's mention did not count
    assert not any("runtime" in p for p in opened), opened
