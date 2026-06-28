import asyncio

import thomas.tools.code_search as code_search
import thomas.tools.search_code as rag_search
from thomas.tools.code_search import CodeSearchTool


def test_code_search_and_rag_search_modules_have_distinct_contracts() -> None:
    assert CodeSearchTool.name == "code.search"
    assert code_search.FindDefinitionTool.name == "code.find_definition"

    assert rag_search.TOOL.name == "rag.search"
    assert rag_search.TOOL.category == "search"

    assert "Registers the ``code.*`` tools" in code_search.__doc__
    assert "RAG index-backed repository search adapter" in rag_search.__doc__


class _FakeProc:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr


def test_code_search_rg_error_with_stdout_returns_success(tmp_path, monkeypatch):
    async def _run() -> None:
        file_path = tmp_path / "sample.txt"
        file_path.write_text("swarm mode works", encoding="utf-8")

        async def _fake_exec(*_args, **_kwargs):
            return _FakeProc(
                2,
                b"sample.txt:1:swarm mode works\n",
                b"rg: .\\nul: Incorrect function. (os error 1)\n",
            )

        monkeypatch.setattr(code_search.asyncio, "create_subprocess_exec", _fake_exec)

        tool = CodeSearchTool(tmp_path)
        tool._has_rg = True
        result = await tool.execute({"pattern": "swarm", "path": ".", "max_results": 10})

        assert result.ok is True
        assert "sample.txt:1:swarm mode works" in str(result.data)
        assert "[rg warning]" in str(result.data)

    asyncio.run(_run())


def test_code_search_rg_error_falls_back_to_python(tmp_path, monkeypatch):
    async def _run() -> None:
        file_path = tmp_path / "sample.txt"
        file_path.write_text("swarm mode works", encoding="utf-8")

        async def _fake_exec(*_args, **_kwargs):
            return _FakeProc(2, b"", b"rg: .\\nul: Incorrect function. (os error 1)\n")

        monkeypatch.setattr(code_search.asyncio, "create_subprocess_exec", _fake_exec)

        tool = CodeSearchTool(tmp_path)
        tool._has_rg = True
        result = await tool.execute({"pattern": "swarm", "path": ".", "max_results": 10})

        assert result.ok is True
        assert "sample.txt:1:" in str(result.data)
        assert "[rg warning]" in str(result.data)

    asyncio.run(_run())
