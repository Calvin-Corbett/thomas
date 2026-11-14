"""Build's Python definition lookup reuses a current, bounded source index."""

import asyncio
from pathlib import Path
from unittest.mock import patch

from thomas.tools.code_search import FindDefinitionTool


def test_python_definition_lookup_refreshes_changed_and_removed_files(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    other = tmp_path / "other.py"
    source.write_text("def target():\n    return 1\n", encoding="utf-8")
    other.write_text("def unrelated():\n    pass\n", encoding="utf-8")
    tool = FindDefinitionTool(tmp_path)

    original_read = Path.read_text
    reads: list[Path] = []

    def count_reads(path: Path, *args: object, **kwargs: object) -> str:
        reads.append(path)
        return original_read(path, *args, **kwargs)

    def lookup(symbol: str) -> str:
        result = asyncio.run(tool.execute({"symbol": symbol, "language": "python"}))
        assert result.ok
        return str(result.data)

    with patch.object(Path, "read_text", count_reads):
        assert "module.py:1" in lookup("target")
        assert set(reads) == {source, other}
        reads.clear()
        assert "module.py:1" in lookup("target")
        assert reads == [source]  # Only the matching file supplies context.
        reads.clear()
        source.write_text("def replacement():\n    return 2\n", encoding="utf-8")
        assert "No definition found" in lookup("target")
        assert reads == [source]
        reads.clear()
        assert "module.py:1" in lookup("replacement")
        assert reads == [source]
        source.unlink()
        assert "No definition found" in lookup("replacement")
        reads.clear()
        added = tmp_path / "added.py"
        added.write_text("def newcomer():\n    return 3\n", encoding="utf-8")
        assert "added.py:1" in lookup("newcomer")
        assert reads == [added, added]  # Index the new file, then read its context.


def test_python_index_finds_unicode_definition_names(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("def élève():\n    return 1\n", encoding="utf-8")
    result = asyncio.run(FindDefinitionTool(tmp_path).execute({"symbol": "élève", "language": "python"}))
    assert result.ok
    assert "module.py:1" in str(result.data)


def test_python_index_keeps_legacy_combining_mark_identifier_lookup(tmp_path: Path) -> None:
    symbol = "e\u0301leve"
    assert symbol.isidentifier()
    (tmp_path / "module.py").write_text(f"def {symbol}():\n    return 1\n", encoding="utf-8")
    result = asyncio.run(FindDefinitionTool(tmp_path).execute({"symbol": symbol, "language": "python"}))
    assert result.ok
    assert "module.py:1" in str(result.data)


def test_python_index_keeps_legacy_non_identifier_lookup(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("config.key = 1\n", encoding="utf-8")
    result = asyncio.run(FindDefinitionTool(tmp_path).execute({"symbol": "config.key", "language": "python"}))
    assert result.ok
    assert "module.py:1" in str(result.data)


def test_python_index_does_not_change_other_language_lookup(tmp_path: Path) -> None:
    (tmp_path / "module.js").write_text("function target() {}\n", encoding="utf-8")
    result = asyncio.run(FindDefinitionTool(tmp_path).execute({"symbol": "target", "language": "javascript"}))
    assert result.ok
    assert "module.js:1" in str(result.data)
