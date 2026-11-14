"""The writer audit reads real Windows permissions and refuses anything you did not pin.

Before the promoter asks you anything it lists who can write Thomas's code
(scripts/cage/writer_audit.py). These run it against a folder with real ACLs:
a baseline that matches is clean, a writer missing from the baseline is named,
and no baseline refuses everything.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from scripts.cage import writer_audit

pytestmark = pytest.mark.skipif(os.name != "nt", reason="reads Windows ACLs")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "thomas").mkdir(parents=True)
    (root / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    return root


def _pin(folder: Path, sids: set[str]) -> Path:
    folder.mkdir(exist_ok=True)
    (folder / writer_audit.ALLOW_NAME).write_text("\n".join(sorted(sids)), encoding="utf-8")
    return folder


def test_a_baseline_that_matches_is_clean(repo: Path, tmp_path: Path) -> None:
    writers = writer_audit.current_writers(repo)

    assert writers, "a folder the test created has writers"
    assert any(set(paths) == {"thomas", "AGENTS.md"} for paths in writers.values())
    assert writer_audit.unexpected_writers(repo, pin_root=_pin(tmp_path / "pins", set(writers))) == []


def test_a_writer_missing_from_the_baseline_is_named(repo: Path, tmp_path: Path) -> None:
    writers = writer_audit.current_writers(repo)
    surprise = next(sid for sid in writers if sid not in {"S-1-5-18", "S-1-5-32-544"})

    found = writer_audit.unexpected_writers(repo, pin_root=_pin(tmp_path / "pins", set(writers) - {surprise}))

    assert len(found) == 1 and found[0].startswith(surprise)


def test_no_baseline_refuses_everything(repo: Path, tmp_path: Path) -> None:
    found = writer_audit.unexpected_writers(repo, pin_root=tmp_path / "nothing-pinned")

    assert found and "not pinned" in found[0]
