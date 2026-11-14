"""A filesystem search must distinguish searched text from an unsearched path."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.tools import filesystem
from thomas.tools.filesystem import SearchFilesTool


@pytest.mark.asyncio
async def test_search_single_file_reports_matching_line(tmp_path: Path):
    target = tmp_path / "tests" / "test_completed_proof_shards_survive_retries.py"
    target.parent.mkdir()
    target.write_text("before\ncompleted proof survives\nafter\n", encoding="utf-8")

    result = await SearchFilesTool(tmp_path).execute(
        {"pattern": "completed proof", "path": target.relative_to(tmp_path).as_posix()}
    )

    assert result.ok
    assert "Found 1 matches (searched 1 files)" in result.data
    assert f"{target.relative_to(tmp_path)}:2: completed proof survives" in result.data


@pytest.mark.asyncio
@pytest.mark.parametrize("rel", ["thomas", "tests/test_completed_proof_shards_survive_retries.py"])
async def test_search_missing_path_is_an_error(tmp_path: Path, rel: str):
    result = await SearchFilesTool(tmp_path).execute({"pattern": "proof", "path": rel})

    assert not result.ok
    assert result.error == f"Path not found: {rel}"
    assert "No matches found" not in (result.data or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("as_file", [False, True])
async def test_search_glob_excluding_every_file_reports_path_and_glob(tmp_path: Path, as_file: bool):
    target = tmp_path / "proof.py"
    target.write_text("completed proof", encoding="utf-8")
    rel = target.name if as_file else "."

    result = await SearchFilesTool(tmp_path).execute({"pattern": "proof", "path": rel, "glob": "*.js"})

    assert result.ok
    assert "No files searched" in result.data
    assert repr(rel) in result.data
    assert repr("*.js") in result.data
    assert "No matches found" not in result.data


@pytest.mark.asyncio
async def test_search_empty_directory_is_not_a_negative_text_search(tmp_path: Path):
    result = await SearchFilesTool(tmp_path).execute({"pattern": "proof", "path": ".", "glob": "*.py"})

    assert result.ok
    assert "No files searched" in result.data
    assert repr(".") in result.data
    assert repr("*.py") in result.data
    assert "No matches found" not in result.data


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["unrelated text\n", ""])
async def test_search_single_file_without_matching_text_is_a_real_negative(tmp_path: Path, text: str):
    target = tmp_path / "proof.py"
    target.write_text(text, encoding="utf-8")

    result = await SearchFilesTool(tmp_path).execute(
        {"pattern": "completed proof", "path": target.name, "glob": "*.py"}
    )

    assert result.ok
    assert result.data == "No matches found (searched 1 files)"


@pytest.mark.asyncio
async def test_search_single_file_respects_max_results(tmp_path: Path):
    target = tmp_path / "proof.py"
    target.write_text("proof\nproof\nproof\n", encoding="utf-8")

    result = await SearchFilesTool(tmp_path).execute({"pattern": "proof", "path": target.name, "max_results": 1})

    assert result.ok
    assert "Found 1 matches (searched 1 files)" in result.data
    assert f"{target.name}:1: proof" in result.data
    assert f"{target.name}:2:" not in result.data


@pytest.mark.asyncio
async def test_search_read_protected_single_file_is_not_opened(tmp_path: Path, monkeypatch):
    target = tmp_path / "proof.py"
    target.write_text("must not be exposed", encoding="utf-8")
    monkeypatch.setattr(filesystem, "_is_read_protected_path", lambda root, path: path == target)

    def forbidden_read(*args):
        pytest.fail("read-protected file was opened")

    monkeypatch.setattr(filesystem, "_file_line_batches", forbidden_read)
    result = await SearchFilesTool(tmp_path).execute({"pattern": ".", "path": target.name})

    assert result.ok
    assert "No files searched" in result.data
    assert repr(target.name) in result.data
    assert "must not be exposed" not in result.data


@pytest.mark.asyncio
@pytest.mark.parametrize("as_file", [False, True])
async def test_search_unreadable_file_is_not_counted_as_searched(tmp_path: Path, monkeypatch, as_file: bool):
    target = tmp_path / "proof.py"
    target.write_text("proof", encoding="utf-8")

    def unreadable(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(filesystem, "_file_line_batches", unreadable)
    rel = target.name if as_file else "."
    result = await SearchFilesTool(tmp_path).execute({"pattern": "proof", "path": rel, "glob": "*.py"})

    assert result.ok
    assert "No files searched" in result.data
    assert repr(rel) in result.data
    assert repr("*.py") in result.data
    assert "No matches found" not in result.data


@pytest.mark.asyncio
async def test_search_exhausted_budget_keeps_partial_notice_without_claiming_no_matches(tmp_path: Path):
    (tmp_path / "first.txt").write_text("proof", encoding="utf-8")
    (tmp_path / "second.txt").write_text("proof", encoding="utf-8")

    result = await SearchFilesTool(tmp_path, max_files=1).execute({"pattern": "proof", "path": ".", "glob": "*.py"})

    assert result.ok
    assert "No files searched" in result.data
    assert "These results are partial" in result.data
    assert "no matching files read" in result.data
    assert "matched no searchable files" not in result.data
    assert "No matches found" not in result.data


@pytest.mark.asyncio
async def test_search_expired_budget_does_not_open_single_file(tmp_path: Path, monkeypatch):
    target = tmp_path / "proof.py"
    target.write_text("proof", encoding="utf-8")

    def forbidden_read(*args):
        pytest.fail("file was opened after search budget expired")

    monkeypatch.setattr(filesystem, "_file_line_batches", forbidden_read)
    monkeypatch.setattr(filesystem, "time", SimpleNamespace(monotonic=lambda: 1.0))
    result = await SearchFilesTool(tmp_path, max_seconds=0).execute(
        {"pattern": "proof", "path": target.name, "glob": "*.py"}
    )

    assert result.ok
    assert "No files searched" in result.data
    assert repr(target.name) in result.data
    assert repr("*.py") in result.data
    assert "These results are partial" in result.data
    assert "No matches found" not in result.data


def test_search_path_schema_advertises_files_and_directories():
    description = SearchFilesTool.parameters["properties"]["path"]["description"]
    assert "File or directory" in description
