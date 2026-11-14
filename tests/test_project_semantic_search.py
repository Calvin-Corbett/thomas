"""A project's semantic lookup cannot index the running Thomas source or another project."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from thomas.core import rag_index
from thomas.core.rag_project_index import ProjectRagIndex
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.semantic_search import SemanticSearchTool


@pytest.fixture(autouse=True)
def offline_index(monkeypatch):
    def unavailable(**_kwargs):
        raise RuntimeError("Offline test uses the real SQLite lexical fallback")

    def forbidden_global():
        raise AssertionError("A project index touched global persistence or the global singleton")

    monkeypatch.setattr(rag_index, "_make_chroma_collection", unavailable)
    monkeypatch.setattr(rag_index, "get_persistence", forbidden_global)
    monkeypatch.setattr(rag_index, "get_rag_index", forbidden_global)


def registry(root):
    tools = ToolRegistry()
    register_code_search_tools(tools, root)
    return tools


@pytest.mark.asyncio
async def test_empty_project_does_not_read_the_running_source_or_create_global_index(tmp_path, monkeypatch):
    project = tmp_path / "empty"
    project.mkdir()
    elsewhere = tmp_path / "process-cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    tools = registry(project)
    result = await tools.execute("code.semantic_search", {"query": "AGENTS"})
    assert result.ok and result.data["results"] == []
    index = tools.get("code.semantic_search")._get_index()
    status = index.status()
    assert status["root_dir"] == str(project.resolve())
    assert status["manifest_files"] == 0
    assert index._worker is None
    assert index.persist_dir == project / ".thomas" / "rag-index"
    assert not (project / "thomas_rag_index").exists()
    assert list(elsewhere.iterdir()) == []
    manifest = json.loads((index.persist_dir / "manifest.json").read_text())
    assert manifest["root_dir"] == str(project.resolve())
    assert manifest["files"] == {}


@pytest.mark.asyncio
async def test_two_projects_with_same_filename_keep_search_and_updates_separate(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "notes.md").write_text("Moonstone apples grow here.")
    (second / "notes.md").write_text("Sapphire pears grow here.")
    one, two = registry(first), registry(second)
    a = await one.execute("code.semantic_search", {"query": "Moonstone"})
    b = await two.execute("code.semantic_search", {"query": "Sapphire"})
    assert a.ok and "Moonstone" in a.data["results"][0]["snippet"]
    assert b.ok and "Sapphire" in b.data["results"][0]["snippet"]
    assert (await one.execute("code.semantic_search", {"query": "Sapphire"})).data["results"] == []
    assert (await two.execute("code.semantic_search", {"query": "Moonstone"})).data["results"] == []
    (first / "notes.md").write_text("Garnet berries replace the old fruit.")
    updated = await one.execute("code.semantic_search", {"query": "Garnet"})
    assert "Garnet" in updated.data["results"][0]["snippet"]
    assert (await one.execute("code.semantic_search", {"query": "Moonstone"})).data["results"] == []
    (second / "notes.md").unlink()
    assert (await two.execute("code.semantic_search", {"query": "Sapphire"})).data["results"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["engine.js", "page.html", "style.css", "view.tsx"])
async def test_registered_project_search_indexes_existing_code_extensions(tmp_path, name):
    (tmp_path / name).write_text("Moonstone voxel rendering")
    result = await registry(tmp_path).execute("code.semantic_search", {"query": "Moonstone"})
    assert result.ok and result.data["backend"] == "lexical"
    assert result.data["results"][0]["file"].startswith(name + "#")


@pytest.mark.asyncio
async def test_same_project_independent_indexes_serialize_refresh_and_reload_manifest(tmp_path, monkeypatch):
    (tmp_path / "notes.md").write_text("Moonstone project content")
    first, second = registry(tmp_path), registry(tmp_path)
    one, two = first.get("code.semantic_search")._get_index(), second.get("code.semantic_search")._get_index()
    assert one is not two and one.persist_dir == two.persist_dir
    active = maximum = 0
    guard = threading.Lock()
    original = ProjectRagIndex._do_build

    def measured_build(self, root, extensions):
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        try:
            time.sleep(0.05)
            return original(self, root, extensions)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(ProjectRagIndex, "_do_build", measured_build)
    results = await asyncio.gather(
        *(tool.execute("code.semantic_search", {"query": "Moonstone"}) for tool in (first, second))
    )
    assert maximum == 1, "Two independent indexes wrote the same manifest concurrently"
    assert all(result.ok and result.data["results"] for result in results)
    (tmp_path / "notes.md").write_text("Sapphire replaces the old material")
    assert (await first.execute("code.semantic_search", {"query": "Sapphire"})).data["results"]
    assert (await second.execute("code.semantic_search", {"query": "Moonstone"})).data["results"] == []
    assert one._manifest == two._manifest


def directory_alias(link: Path, target: Path):
    if os.name == "nt":

        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"New-Item -ItemType Junction -Path {quote(link)} -Target {quote(target)} | Out-Null",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.asyncio
async def test_search_never_traverses_a_directory_alias_to_another_project(tmp_path):
    project, outside = tmp_path / "project", tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (outside / "secret.md").write_text("Quasar foreign project content")
    directory_alias(project / "visible", outside)
    result = await registry(project).execute("code.semantic_search", {"query": "Quasar"})
    assert result.ok and result.data["results"] == []
    manifest = json.loads((project / ".thomas/rag-index/manifest.json").read_text())
    assert manifest["files"] == {}


@pytest.mark.asyncio
async def test_search_never_reads_a_file_symlink_outside_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("Quasar foreign project content")
    try:
        (project / "secret.md").symlink_to(outside)
    except OSError:
        pytest.skip("File symlink privileges unavailable")
    result = await registry(project).execute("code.semantic_search", {"query": "Quasar"})
    assert result.ok and result.data["results"] == []


def test_index_storage_cannot_escape_through_a_directory_alias(tmp_path):
    project, outside = tmp_path / "project", tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    directory_alias(project / ".thomas", outside)
    with pytest.raises(ValueError, match="linked paths"):
        ProjectRagIndex(project)
    assert list(outside.iterdir()) == []


def test_foreign_manifest_cannot_be_reused(tmp_path):
    cache = tmp_path / ".thomas/rag-index"
    cache.mkdir(parents=True)
    (cache / "manifest.json").write_text(json.dumps({"root_dir": str(tmp_path.parent), "files": {}}))
    with pytest.raises(ValueError, match="different project"):
        ProjectRagIndex(tmp_path)


@pytest.mark.parametrize("broken", [None, "{broken", "{}", "[]", "null", '{"root_dir": 42}'])
def test_orphaned_index_cannot_return_deleted_content(tmp_path, broken):
    source = tmp_path / "notes.md"
    source.write_text("Quasar content to be deleted")
    index = ProjectRagIndex(tmp_path)
    assert index.search("Quasar")
    source.unlink()
    manifest = index.persist_dir / "manifest.json"
    if broken is None:
        manifest.unlink()
    else:
        manifest.write_text(broken)
    with pytest.raises(ValueError, match="ownership manifest"):
        ProjectRagIndex(tmp_path)
    with pytest.raises(ValueError, match="ownership manifest"):
        index.search("Quasar")


def test_source_hardlink_does_not_import_external_content(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("Quasar foreign content")
    os.link(outside, project / "linked.md")
    assert ProjectRagIndex(project).search("Quasar") == []


def test_deleted_content_in_orphaned_fts_rows_is_not_returned(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("Quasar content to be deleted")
    index = ProjectRagIndex(tmp_path)
    assert index.search("Quasar")
    manifest = index.persist_dir / "manifest.json"
    data = json.loads(manifest.read_text())
    data["files"] = {}  # A crash after the FTS commit but before the manifest commit.
    manifest.write_text(json.dumps(data))
    source.unlink()
    assert ProjectRagIndex(tmp_path).search("Quasar") == []


@pytest.mark.skipif(os.name != "nt", reason="Windows path anchoring regression")
def test_windows_rooted_and_drive_relative_cache_paths_are_refused(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "notes.md"
    outside.write_text("Quasar external content")
    (project / "notes.md").write_text("Ordinary project text")
    index = ProjectRagIndex(project)
    for raw in (str(outside)[len(outside.drive) :], outside.drive + "notes.md"):
        assert not Path(raw).is_absolute(), "This regression must exercise non-absolute anchored paths"
        assert index._scoped_hits([{"relpath": raw}]) == []
    assert index._scoped_hits([{"relpath": "notes.md"}]) == [{"relpath": "notes.md"}]


@pytest.mark.parametrize("filename", ["manifest.json", "rag_fts.sqlite3", "rag_fts.sqlite3-wal", "chroma.sqlite3"])
def test_writable_index_files_cannot_alias_external_files(tmp_path, filename):
    project = tmp_path / "project"
    cache = project / ".thomas/rag-index"
    cache.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_bytes(b"external bytes must stay unchanged")
    os.link(outside, cache / filename)
    with pytest.raises(ValueError, match="hard-linked"):
        ProjectRagIndex(project)
    assert outside.read_bytes() == b"external bytes must stay unchanged"


@pytest.mark.asyncio
@pytest.mark.parametrize("python_fallback", [False, True])
async def test_lexical_search_does_not_surface_legacy_generated_index_metadata(tmp_path, python_fallback):
    legacy = tmp_path / "thomas_rag_index"
    legacy.mkdir()
    (legacy / "manifest.json").write_text('"Quasar foreign source paths"')
    tool = registry(tmp_path).get("code.search")
    if python_fallback:
        tool._has_rg = False
    result = await tool.execute({"pattern": "Quasar", "glob": "*.json"})
    assert result.ok and "Quasar" not in str(result.data)


@pytest.mark.asyncio
async def test_unscoped_generic_callers_keep_the_existing_singleton_contract(monkeypatch):
    class ExistingIndex:
        def search(self, query, k=5, filter_ext=None):
            return [{"file": "old.md", "chunk": query, "score": 1}]

        def status(self):
            return {"vector_count": 0, "fts_enabled": True}

    index = ExistingIndex()
    monkeypatch.setattr(rag_index, "get_rag_index", lambda: index)
    tool = SemanticSearchTool()
    result = await tool.execute({"query": "existing global caller"})
    assert result.ok and result.data["results"][0]["file"] == "old.md"
    assert tool._get_index() is index
