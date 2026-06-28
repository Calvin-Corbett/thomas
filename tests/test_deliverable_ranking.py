"""The deliverable ranker must surface the user's real output, not a build script.

A worker that writes ``build_cookie_pdf.py`` + ``cookies.pdf`` must present the PDF,
and one that writes ``index.html`` + ``scripts/forge/gates/monolith_guard.py`` must
present the web page — never the script. ``deliverable_kind`` must classify the entry
so the UI knows whether to open a right-side live preview (web) vs. inline (pdf/image/
text) vs. download (file). These had no unit coverage (adversarial review 2026-06-17).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.server.routes import deliverable_aiohttp as da


def _make_workspace(monkeypatch: pytest.MonkeyPatch, base: Path, exec_id: str, files: dict[str, str]) -> str:
    """Create a fake workspace under a monkeypatched base and return the exec id."""
    monkeypatch.setattr(da, "_WORKSPACES_BASE", base)
    wd = base / exec_id
    for rel, content in files.items():
        target = wd / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return exec_id


def test_rank_prefers_real_deliverable_over_build_script() -> None:
    pdf = da._deliverable_rank(Path("cookies.pdf"))
    script = da._deliverable_rank(Path("build_cookie_pdf.py"))
    assert pdf < script, "a produced PDF must outrank the script that built it"


def test_rank_prefers_web_then_pdf_then_image() -> None:
    html = da._deliverable_rank(Path("index.html"))
    pdf = da._deliverable_rank(Path("doc.pdf"))
    png = da._deliverable_rank(Path("shot.png"))
    assert html < pdf < png


def test_rank_build_filenames_lose_to_real_output() -> None:
    real = da._deliverable_rank(Path("index.html"))
    reqs = da._deliverable_rank(Path("requirements.txt"))
    assert real < reqs


def test_entry_picks_pdf_over_build_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-pdfcase",
        {"build_cookie_pdf.py": "print('x')", "cookies.pdf": "%PDF-1.4 fake"},
    )
    assert da.deliverable_entry(eid) == "cookies.pdf"
    assert da.deliverable_kind(eid) == "pdf"


def test_entry_picks_html_over_offtask_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real Pong/Starfield scenario: worker wrote index.html AND an off-task gate script."""
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-webcase",
        {
            "index.html": "<title>Game</title><canvas></canvas>",
            "scripts/forge/gates/monolith_guard.py": "# off-task scaffolding",
        },
    )
    assert da.deliverable_entry(eid) == "index.html"
    assert da.deliverable_kind(eid) == "web"


def test_kind_classifies_each_family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = {
        "exec-web": ({"index.html": "x"}, "web"),
        "exec-img": ({"chart.png": "x"}, "image"),
        "exec-txt": ({"notes.md": "x"}, "text"),
        "exec-bin": ({"report.docx": "x"}, "file"),
    }
    for eid, (files, expected) in cases.items():
        _make_workspace(monkeypatch, tmp_path, eid, files)
        assert da.deliverable_kind(eid) == expected, f"{eid} should classify as {expected}"


def test_empty_workspace_has_no_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(da, "_WORKSPACES_BASE", tmp_path)
    (tmp_path / "exec-empty").mkdir(parents=True)
    assert da.deliverable_entry("exec-empty") is None
    assert da.deliverable_kind("exec-empty") == ""


def test_deliverable_in_subdir_beats_root_build_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real deliverable in a build-output subdir must still beat a root build script
    (regression: the old dotfile filter hid it and surfaced the script)."""
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-subdir",
        {"dist/index.html": "<title>app</title>", "build_site.py": "print(1)"},
    )
    assert da.deliverable_entry(eid) == "dist/index.html"
    assert da.deliverable_kind(eid) == "web"


def test_junk_dir_files_are_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-junk",
        {"index.html": "<title>x</title>", ".git/config": "noise", "node_modules/p/i.js": "noise"},
    )
    assert da.deliverable_entry(eid) == "index.html"


def test_lone_output_in_dotdir_is_not_reported_as_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the only content sits under a junk dir, fall back to it rather than report
    'nothing to show' for a build that did produce a file."""
    eid = _make_workspace(monkeypatch, tmp_path, "exec-fallback", {".cache/report.pdf": "%PDF-1.4"})
    # .cache is not in _JUNK_DIRS, so it's surfaced directly; either way it must not be None.
    assert da.deliverable_entry(eid) is not None
    assert da.deliverable_kind(eid) == "pdf"


def test_entry_preference_is_case_insensitive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker that wrote 'Index.html' must resolve on Linux CI and Windows alike."""
    eid = _make_workspace(monkeypatch, tmp_path, "exec-case", {"Index.html": "<title>x</title>"})
    assert da.deliverable_entry(eid) == "Index.html"
    assert da.deliverable_kind(eid) == "web"


def test_entry_prefers_successful_attempt_artifact_over_stale_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later successful attempt must not open an old preferred index.html."""
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-attempt-boundary",
        {
            "index.html": "<title>broken stale attempt</title>",
            "game-v2.html": "<title>successful retry</title><canvas></canvas>",
        },
    )
    monkeypatch.setattr(
        da.task_bot_runtime,
        "get_execution",
        lambda execution_id: {
            "execution_id": execution_id,
            "proof": {"artifacts": [{"path": "game-v2.html", "type": "html"}]},
        },
    )

    assert da.deliverable_entry(eid) == "game-v2.html"
    assert da.deliverable_kind(eid) == "web"
    assert da.deliverable_url(eid) == "/deliverable/exec-attempt-boundary/game-v2.html"


@pytest.mark.asyncio
async def test_route_default_serves_successful_attempt_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eid = _make_workspace(
        monkeypatch,
        tmp_path,
        "exec-route-attempt",
        {
            "index.html": "<title>stale</title>",
            "game-v2.html": "<title>fresh</title>",
        },
    )
    monkeypatch.setattr(
        da.task_bot_runtime,
        "get_execution",
        lambda execution_id: {"proof": {"artifacts": [{"path": "game-v2.html"}]}},
    )
    served: list[Path] = []

    def _file_response(path: Path):
        served.append(Path(path))
        return da.web.Response(text="ok")

    class _Transport:
        def get_extra_info(self, name: str):
            return ("127.0.0.1", 12345) if name == "peername" else None

    class _Request:
        transport = _Transport()
        match_info = {"execution_id": eid, "tail": ""}

    monkeypatch.setattr(da.web, "FileResponse", _file_response)

    response = await da.handle_deliverable(_Request())

    # HTML deliverables are served via web.Response with an in-memory storage shim
    # injected (so sandboxed games/apps using localStorage don't crash on init), NOT
    # FileResponse. Verify the SUCCESSFUL attempt's artifact is the one served.
    body = response.text or ""
    assert "fresh" in body and "stale" not in body  # served game-v2.html, not stale index.html
    assert "localStorage" in body  # storage shim injected
    assert response.headers["Content-Security-Policy"] == "sandbox allow-scripts allow-forms"
