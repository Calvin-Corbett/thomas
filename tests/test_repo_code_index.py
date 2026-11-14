"""Shared code map returns a definition, callers and importing tests in one lookup."""

import asyncio
import os
import shutil
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import thomas.tools.repo_code_index as code_index
from thomas.tools.repo_code_index import RepoIndexTool


def lookup(root: Path, symbol: str):
    return asyncio.run(RepoIndexTool(root).execute({"symbol": symbol}))


def test_registry_exposes_shared_lookup_to_build_team(tmp_path: Path) -> None:
    from thomas.core.config import load_config
    from thomas.forge.anvil.build_agent_team import _READ_TOOLS
    from thomas.server.app_helpers import _build_tools

    config = load_config()
    config.tools.sandbox_root = str(tmp_path)
    registry = _build_tools(config)
    assert "code.repo_index" in registry
    assert "code.repo_index" in _READ_TOOLS
    assert registry.get("code.repo_index")._root == tmp_path.resolve()


def test_isolated_builder_can_lookup_only_its_snapshot(tmp_path: Path) -> None:
    from thomas.core.config import load_config
    from thomas.forge.anvil.build_agent_team import review_tools
    from thomas.forge.anvil.build_agent_workspace import BuildWorkspace
    from thomas.forge.anvil.build_agent_writer import _builder_tools
    from thomas.server.app_helpers import _build_tools

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "service.py").write_text("def selected(): pass\n", encoding="utf-8")
    (tmp_path / "pkg" / "hidden.py").write_text("def excluded(): pass\n", encoding="utf-8")
    config = load_config()
    config.tools.sandbox_root = str(tmp_path)
    parent = _build_tools(config)
    workspace = BuildWorkspace.create(tmp_path, "child_123456789abc", "pkg/service.py", context_files=[])
    try:
        tools = _builder_tools(workspace, config, lambda base: review_tools(base))
        index = tools.get("code.repo_index")
        assert index is not None
        selected = asyncio.run(index.execute({"symbol": "selected"}))
        excluded = asyncio.run(index.execute({"symbol": "excluded"}))
        assert selected.ok and selected.data["definitions"][0]["path"] == "pkg/service.py"
        assert excluded.ok and excluded.data["definitions"] == []
        assert parent.get("code.repo_index") is not None
    finally:
        shutil.rmtree(workspace.root.parent)


def test_lookup_tracks_edits_deletions_and_shares_database_across_instances(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    source = tmp_path / "pkg" / "service.py"
    source.write_text("def process_request():\n    return 1\n", encoding="utf-8")
    caller = tmp_path / "pkg" / "client.py"
    caller.write_text("from pkg.service import process_request\nprocess_request()\n", encoding="utf-8")
    test = tmp_path / "tests" / "test_service.py"
    test.write_text("from pkg.service import process_request\n", encoding="utf-8")
    first = lookup(tmp_path, "process_request")
    assert first.ok
    assert {"name": "process_request", "path": "pkg/service.py", "line": 1} in first.data["definitions"]
    assert {"name": "process_request", "path": "pkg/client.py", "line": 2} in first.data["references"]
    assert "tests/test_service.py" in first.data["tests_importing_files"]
    assert (
        "tests/test_service.py"
        in asyncio.run(RepoIndexTool(tmp_path).execute({"path": "pkg/service.py"})).data["tests_importing_files"]
    )
    database = tmp_path / ".thomas" / "code_index.sqlite3"
    assert database.exists()
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM files").fetchone()[0] == 3

    source.write_text("\n\ndef process_request():\n    return 2\n", encoding="utf-8")
    assert lookup(tmp_path, "process_request").data["definitions"][0]["line"] == 3
    caller.unlink()
    assert all(ref["path"] != "pkg/client.py" for ref in lookup(tmp_path, "process_request").data["references"])
    test.unlink()
    assert lookup(tmp_path, "process_request").data["tests_importing_files"] == []
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM files").fetchone()[0] == 1


def test_concurrent_lookups_refresh_new_files_without_conflicting(tmp_path: Path, monkeypatch) -> None:
    assert lookup(tmp_path, "shared").ok  # Warm the schema before the new file arrives.
    (tmp_path / "service.py").write_text("def shared(): pass\n", encoding="utf-8")
    first_scanning = threading.Event()
    second_scanning = threading.Event()
    original_source_files = code_index._source_files

    def concurrent_sources(root):
        if not first_scanning.is_set():
            first_scanning.set()
            second_scanning.wait(timeout=1)
        else:
            second_scanning.set()
        yield from original_source_files(root)

    monkeypatch.setattr(code_index, "_source_files", concurrent_sources)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(lookup, tmp_path, "shared")
        assert first_scanning.wait(timeout=5)
        second = workers.submit(lookup, tmp_path, "shared")
        results = [first.result(timeout=10), second.result(timeout=10)]
    assert all(result.ok for result in results), [result.error for result in results]
    assert all(
        result.data["definitions"] == [{"name": "shared", "path": "service.py", "line": 1}] for result in results
    )


def test_concurrent_first_lookups_create_shared_index(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("def new_file(): pass\n", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: lookup(tmp_path, "new_file"), range(2)))
    assert all(result.ok for result in results), [result.error for result in results]
    assert all(result.data["definitions"][0]["path"] == "service.py" for result in results)
    assert (tmp_path / ".thomas" / "code_index.sqlite3").exists()


def test_lookup_reconciles_same_size_edit_even_with_restored_mtime(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("def before(): pass\n", encoding="utf-8")
    assert lookup(tmp_path, "before").data["definitions"]
    old_stat = source.stat()
    source.write_text("def after_(): pass\n", encoding="utf-8")
    os.utime(source, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert source.stat().st_size == old_stat.st_size
    assert lookup(tmp_path, "after_").data["definitions"]
    assert lookup(tmp_path, "before").data["definitions"] == []


def test_existing_index_schema_migrates_without_losing_lookups(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("def migrated(): pass\n", encoding="utf-8")
    folder = tmp_path / ".thomas"
    folder.mkdir()
    with sqlite3.connect(folder / "code_index.sqlite3") as db:
        db.execute("CREATE TABLE files (path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER)")
    assert lookup(tmp_path, "migrated").data["definitions"]
    with sqlite3.connect(folder / "code_index.sqlite3") as db:
        assert "digest" in {column[1] for column in db.execute("PRAGMA table_info(files)")}


def test_schema_upgrade_discards_stale_rows_before_reindexing(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("def old_name(): pass\n", encoding="utf-8")
    assert lookup(tmp_path, "old_name").data["definitions"]
    store = tmp_path / ".thomas" / "code_index.sqlite3"
    source.write_text("def new_name(): pass\n", encoding="utf-8")
    with sqlite3.connect(store) as db:
        db.execute("PRAGMA user_version = 0")
    assert lookup(tmp_path, "old_name").data["definitions"] == []
    assert lookup(tmp_path, "new_name").data["definitions"] == [{"name": "new_name", "path": "service.py", "line": 1}]


def test_existing_index_reparses_when_extractor_changes(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    source = tmp_path / "src" / "view.js"
    test = tmp_path / "tests" / "view.test.mjs"
    source.write_text("export function renderView() {}\n", encoding="utf-8")
    test.write_text('import "../src/view.js";\n', encoding="utf-8")
    assert lookup(tmp_path, "renderView").ok
    store = tmp_path / ".thomas" / "code_index.sqlite3"
    with sqlite3.connect(store) as db:
        db.execute("DELETE FROM imports")
        db.execute("PRAGMA user_version = 0")
    result = asyncio.run(RepoIndexTool(tmp_path).execute({"path": "src/view.js"}))
    assert result.ok
    assert "tests/view.test.mjs" in result.data["tests_importing_files"]


def test_path_lookup_and_excluded_directories(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "pkg" / "widget.py").write_text("class Widget: pass\n", encoding="utf-8")
    (tmp_path / "tests" / "test_widget.py").write_text("from pkg.widget import Widget\n", encoding="utf-8")
    (tmp_path / "node_modules" / "noise.py").write_text("class Widget: pass\n", encoding="utf-8")
    result = asyncio.run(RepoIndexTool(tmp_path).execute({"path": "pkg/widget.py"}))
    assert result.ok
    assert result.data["definitions"][0]["name"] == "Widget"
    assert "tests/test_widget.py" in result.data["tests_importing_files"]
    assert all(item["path"] != "node_modules/noise.py" for item in lookup(tmp_path, "Widget").data["definitions"])
    assert not asyncio.run(RepoIndexTool(tmp_path).execute({"path": "../outside.py"})).ok
    assert not asyncio.run(RepoIndexTool(tmp_path).execute({"path": "node_modules/noise.py"})).ok
    (tmp_path / "pkg" / "client.py").write_text("Widget()\n", encoding="utf-8")
    scoped = asyncio.run(RepoIndexTool(tmp_path).execute({"path": "pkg/widget.py", "symbol": "Widget"}))
    assert scoped.ok
    assert {"name": "Widget", "path": "pkg/client.py", "line": 1} in scoped.data["references"]
    assert scoped.data["definitions"][0]["path"] == "pkg/widget.py"


def test_lookup_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}_external_source.py"
    outside.write_text("def external(): pass\n", encoding="utf-8")
    link = tmp_path / "alias.py"
    try:
        link.symlink_to(outside)
    except OSError:
        outside.unlink()
        return  # Creating symlinks requires extra privileges on some Windows hosts.
    try:
        result = asyncio.run(RepoIndexTool(tmp_path).execute({"path": "alias.py"}))
        assert not result.ok
    finally:
        outside.unlink()


def test_renamed_symbol_invalidates_old_index_across_team_instances(tmp_path: Path) -> None:
    source = tmp_path / "entry.py"
    source.write_text("def original(): pass\n", encoding="utf-8")
    first = RepoIndexTool(tmp_path)
    second = RepoIndexTool(tmp_path)
    assert asyncio.run(first.execute({"symbol": "original"})).data["definitions"]
    source.write_text("def replacement(): pass\n", encoding="utf-8")
    assert asyncio.run(second.execute({"symbol": "replacement"})).data["definitions"]
    assert asyncio.run(first.execute({"symbol": "original"})).data["definitions"] == []


def test_python_assignment_definition(tmp_path: Path) -> None:
    (tmp_path / "settings.py").write_text("RETRY_LIMIT = 3\n", encoding="utf-8")
    result = lookup(tmp_path, "RETRY_LIMIT")
    assert result.data["definitions"] == [{"name": "RETRY_LIMIT", "path": "settings.py", "line": 1}]


def test_qualified_symbol_finds_real_callers_and_imports(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "worker.py").write_text("def handle(): pass\n", encoding="utf-8")
    (tmp_path / "pkg" / "other.py").write_text("def handle(): pass\n", encoding="utf-8")
    (tmp_path / "pkg" / "client.py").write_text("from pkg.worker import handle\nhandle()\n", encoding="utf-8")
    (tmp_path / "tests" / "test_worker.py").write_text("from pkg.worker import handle\n", encoding="utf-8")
    result = lookup(tmp_path, "pkg.worker.handle")
    assert result.ok
    assert result.data["definitions"] == [{"name": "handle", "path": "pkg/worker.py", "line": 1}]
    assert {"name": "handle", "path": "pkg/client.py", "line": 2} in result.data["references"]
    assert result.data["tests_importing_files"] == ["tests/test_worker.py"]


def test_package_qualified_symbol_finds_init_definition_and_relative_importers(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("from .worker import helper\ndef export(): pass\n", encoding="utf-8")
    (tmp_path / "pkg" / "worker.py").write_text("def helper(): pass\n", encoding="utf-8")
    (tmp_path / "tests" / "test_pkg.py").write_text("from pkg import export\n", encoding="utf-8")
    result = lookup(tmp_path, "pkg.export")
    assert result.ok
    assert result.data["definitions"] == [{"name": "export", "path": "pkg/__init__.py", "line": 2}]
    assert result.data["tests_importing_files"] == ["tests/test_pkg.py"]
    helper = asyncio.run(RepoIndexTool(tmp_path).execute({"path": "pkg/worker.py"}))
    assert helper.ok
    assert "pkg/__init__.py" not in helper.data["tests_importing_files"]
    assert lookup(tmp_path, "pkg.worker.helper").ok


def test_file_query_reports_callers_outside_definition_file(tmp_path: Path) -> None:
    (tmp_path / "library.py").write_text("def transform(): pass\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text("from library import transform\ntransform()\n", encoding="utf-8")
    result = asyncio.run(RepoIndexTool(tmp_path).execute({"path": "library.py", "symbol": "transform"}))
    assert result.ok
    assert result.data["definitions"] == [{"name": "transform", "path": "library.py", "line": 1}]
    assert {"name": "transform", "path": "consumer.py", "line": 2} in result.data["references"]


def test_javascript_test_import_is_linked_to_source_file(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "view.js").write_text("export function renderView() {}\n", encoding="utf-8")
    (tmp_path / "tests" / "view.test.mjs").write_text('import { renderView } from "../src/view";\n', encoding="utf-8")
    result = asyncio.run(RepoIndexTool(tmp_path).execute({"path": "src/view.js"}))
    assert result.ok
    assert "tests/view.test.mjs" in result.data["tests_importing_files"]


def test_root_level_javascript_test_import_is_linked(tmp_path: Path) -> None:
    (tmp_path / "view.js").write_text("export function renderView() {}\n", encoding="utf-8")
    (tmp_path / "view.test.js").write_text('import { renderView } from "./view.js";\n', encoding="utf-8")
    result = asyncio.run(RepoIndexTool(tmp_path).execute({"path": "view.js"}))
    assert result.ok
    assert result.data["tests_importing_files"] == ["view.test.js"]


def test_definitions_are_not_duplicated_by_repeated_bindings(tmp_path: Path) -> None:
    (tmp_path / "entry.js").write_text("const value = 1; let value = 2;\n", encoding="utf-8")
    result = lookup(tmp_path, "value")
    assert result.data["definitions"] == [{"name": "value", "path": "entry.js", "line": 1}]


def test_nested_javascript_test_directory_links_to_source(tmp_path: Path) -> None:
    package = tmp_path / "package"
    (package / "src").mkdir(parents=True)
    (package / "test").mkdir()
    (package / "src" / "voice.js").write_text("export function speak() {}\n", encoding="utf-8")
    (package / "test" / "voice.test.js").write_text('import {\n  speak,\n} from "../src/voice.js";\n', encoding="utf-8")
    result = asyncio.run(RepoIndexTool(tmp_path).execute({"path": "package/src/voice.js"}))
    assert result.ok
    assert result.data["tests_importing_files"] == ["package/test/voice.test.js"]


def test_javascript_definition_and_reference(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("function loadView() {}\nloadView();\n", encoding="utf-8")
    result = lookup(tmp_path, "loadView")
    assert result.data["definitions"][0]["line"] == 1
    assert any(ref["path"] == "app.js" and ref["line"] == 2 for ref in result.data["references"])
