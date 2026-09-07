"""The repair snapshot must not crash a fix pass on a path it cannot stat (2026-09-06).

Every self-edit run on the Thomas checkout was filed as failed at the start of
its fix pass with "[WinError 1920] The file cannot be accessed by the system"
on a Linux venv link copied onto Windows under runtime/doppelganger. The
orphan scan had the same bug and was fixed first; this one hid behind it:
``_snapshot_repair_files`` walked the whole project with rglob and called
``is_file()`` on every entry before anything was pruned. Five landed
self-edits were recorded as failures by these two walks.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from thomas.forge.anvil import build_verify


def test_a_path_whose_stat_raises_does_not_crash_the_snapshot(tmp_path: Path, monkeypatch: Any) -> None:
    (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")
    venv = tmp_path / "runtime" / "doppelganger" / "venvs" / "green"
    venv.mkdir(parents=True)
    (venv / "lib64").write_text("", encoding="utf-8")
    (venv / "vendored.js").write_text("// never ours", encoding="utf-8")
    real_stat = os.stat

    def exploding_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        if str(path).endswith("lib64"):
            raise OSError(1920, "The file cannot be accessed by the system")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", exploding_stat)
    snapshot = build_verify._snapshot_repair_files(tmp_path, ["index.html"])
    names = sorted(p.name for p in snapshot)
    assert names == ["app.js", "index.html"], names  # the venv's file is not the project's
