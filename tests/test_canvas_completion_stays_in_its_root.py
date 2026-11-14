"""Canvas completion writes index.html only inside its workspace.

The workspace is the files-slot root. A link or junction named index.html that leads out of it is refused before
anything is written; an ordinary workspace still delivers.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from thomas.core import task_bot_runtime
from thomas.server import chat_delegation_canvas_completion as mod

HTML = "<!doctype html><title>Chart</title>"


def _execution(repo: Path) -> str:
    return str(
        task_bot_runtime.create_execution(session_id="canvas-session", summary="Create a chart", repo_root=repo)[
            "execution_id"
        ]
    )


def _run(repo: Path, work: Path, **extra):
    return mod.complete_canvas_delivery(
        execution_id=_execution(repo),
        prompt="Create an interactive chart",
        html=HTML,
        actor="Taylor",
        repo_root=repo,
        workspace_for=lambda _: work,
        **extra,
    )


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_MEMORY_ROOT", str(tmp_path / "mem"))


def _link_file(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("no symlink privilege on this account")


def test_an_ordinary_workspace_delivers(tmp_path: Path) -> None:
    work = tmp_path / "work"
    record, _ = _run(tmp_path, work)
    assert (work / "index.html").read_text(encoding="utf-8") == HTML
    assert record["state"] == "completed"


def test_an_index_link_out_of_the_workspace_is_refused(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("keep", encoding="utf-8")
    _link_file(work / "index.html", outside)
    with pytest.raises(PermissionError, match="BLOCKED"):
        _run(tmp_path, work)
    assert outside.read_text(encoding="utf-8") == "keep"


def test_an_index_link_to_a_shared_prefix_sibling_is_refused(tmp_path: Path) -> None:
    work = tmp_path / "work"
    sibling = tmp_path / "work2"
    work.mkdir()
    sibling.mkdir()
    target = sibling / "index.html"
    target.write_text("keep", encoding="utf-8")
    _link_file(work / "index.html", target)
    with pytest.raises(PermissionError, match="BLOCKED"):
        _run(tmp_path, work)
    assert target.read_text(encoding="utf-8") == "keep"


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows thing")
def test_a_junction_named_index_html_out_of_the_workspace_is_refused(tmp_path: Path) -> None:
    work = tmp_path / "work"
    outside = tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(work / "index.html"), str(outside)], capture_output=True, check=False
    )
    if made.returncode != 0:
        pytest.skip("could not make a junction")
    with pytest.raises(PermissionError, match="BLOCKED"):
        _run(tmp_path, work)
    assert not any(outside.iterdir())


def test_the_slot_is_looked_up_at_call_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Path] = []

    class Spy:
        def scope(self, root):
            seen.append(Path(root))
            raise ValueError("spy refuses")

    monkeypatch.setattr(mod, "scopes", lambda: Spy())
    work = tmp_path / "work"
    with pytest.raises(PermissionError, match="spy refuses"):
        _run(tmp_path, work)
    assert seen == [work]
    assert not work.exists()


def test_read_only_still_wins_for_an_ordinary_path(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="read-only"):
        _run(tmp_path, tmp_path / "work", file_access=0)
