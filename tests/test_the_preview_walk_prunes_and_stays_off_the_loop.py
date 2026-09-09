"""The preview allowlist walk prunes as it goes and never serves the source tree.

py-spy caught the old ``root.rglob("*")`` mid-freeze on the event loop
(2026-08-05): its filter excluded ``.git``/``node_modules`` entries from the
RESULTS while the walk still descended into them, so a conversation pointed at
a big checkout froze every request on the server -- including "/" -- for the
length of a ~1.5M-entry walk, fired automatically by artifact-thumbnail
hydration. The walk now prunes excluded directories in place, runs in a worker
thread, and the preview refuses Thomas's own source root outright, the same
refusal the edit path already makes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from thomas.server.routes import evolve_agent_routes


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pages").mkdir(parents=True)
    (root / "pages" / "app.js").write_text("// app", encoding="utf-8")
    (root / "index.html").write_text("<p>hi</p>", encoding="utf-8")
    (root / "notes.py").write_text("# not a web asset", encoding="utf-8")
    for pruned in (".git", "node_modules", ".thomas", ".venv"):
        nest = root / pruned / "deep"
        nest.mkdir(parents=True)
        (nest / "inner.html").write_text("<p>never served</p>", encoding="utf-8")
    return root


def test_the_allowlist_holds_web_assets_and_nothing_from_pruned_trees(tmp_path: Path) -> None:
    allowed = evolve_agent_routes._preview_allowlist(_project(tmp_path))
    assert allowed == {"index.html", "pages/app.js"}


def test_the_walk_never_enters_a_pruned_directory(tmp_path: Path, monkeypatch: Any) -> None:
    # The measured defect was not wrong RESULTS -- the old filter got those
    # right -- it was the descent itself: a million entries enumerated and
    # discarded, on the event loop. Record every directory os.walk yields and
    # assert none of them is inside a pruned tree.
    root = _project(tmp_path)
    visited: list[str] = []
    real_walk = os.walk

    def recording_walk(top: Any, *args: Any, **kwargs: Any):
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
            visited.append(str(dirpath))
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(os, "walk", recording_walk)
    evolve_agent_routes._preview_allowlist(root)
    pruned_hits = [
        d for d in visited
        if any(part in evolve_agent_routes._PREVIEW_PRUNED_DIRS for part in Path(d).relative_to(root).parts)
    ]
    assert pruned_hits == [], f"walk descended into pruned trees: {pruned_hits}"
