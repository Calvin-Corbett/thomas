"""An optional scope at each place a root first becomes known.

None keeps today's root; a scope replaces it, and the tools built there read and write under the scope's root.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.test_build_agent_team import OfflineClient, runtime  # noqa: F401 - shared offline fixture
from thomas.core.config import AppConfig
from thomas.tools.fs_scope import scopes


def _run(coro):
    return asyncio.run(coro)


def _config(root: Path) -> AppConfig:
    cfg = AppConfig()
    cfg.tools.sandbox_root = str(root)
    cfg.tools.allow_shell = False
    return cfg


def _worlds(tmp_path: Path) -> tuple[Path, Path]:
    configured, scoped = tmp_path / "configured", tmp_path / "scoped"
    for folder, text in ((configured, "from-config"), (scoped, "from-scope")):
        folder.mkdir()
        (folder / "f.txt").write_text(text, encoding="utf-8")
    return configured, scoped


def _read(registry, name: str = "fs.read_file") -> str:
    result = _run(registry.get(name).execute({"path": "f.txt"}))
    return result.to_content()


def test_the_cli_tools_follow_the_scope_and_default_to_the_config(tmp_path) -> None:
    from thomas.cli._commands_base import _build_tools

    configured, scoped = _worlds(tmp_path)
    cfg = _config(configured)
    assert "from-config" in _read(_build_tools(cfg))
    assert "from-config" in _read(_build_tools(cfg, None))
    assert "from-scope" in _read(_build_tools(cfg, scopes().scope(scoped)))


def test_the_benchmark_tools_follow_the_scope_and_default_to_the_config(tmp_path) -> None:
    from thomas.demo.agentic_benchmark_runners import _build_tools

    configured, scoped = _worlds(tmp_path)
    cfg = _config(configured)
    assert "from-config" in _read(_build_tools(cfg))
    assert "from-config" in _read(_build_tools(cfg, None))
    assert "from-scope" in _read(_build_tools(cfg, scopes().scope(scoped)))


class _Stop(Exception):
    pass


def _dispatched_tools(monkeypatch, cwd: Path, **kwargs):
    """Run the dispatch pass up to the moment it builds its loop; return the tools and the loop's scope."""
    import thomas.agent.kernel_wiring as wiring
    from thomas.forge.anvil.dispatch_agent_loop import _agent_loop_pass_async

    seen: dict = {}

    def fake_build(config, llm, tools, **_kw):
        seen["tools"] = tools
        seen["root"] = config.tools.sandbox_path
        raise _Stop

    monkeypatch.setattr(wiring, "build_agent_loop", fake_build)
    try:
        _run(_agent_loop_pass_async("p", str(cwd), 5, lambda _e: None, **kwargs))
    except _Stop:
        pass
    return seen


def test_the_dispatch_pass_roots_its_tools_at_cwd_without_a_scope_and_at_the_scope_with_one(
    tmp_path, monkeypatch
) -> None:
    configured, scoped = _worlds(tmp_path)
    plain = _dispatched_tools(monkeypatch, configured)
    assert plain["root"] == configured.resolve()
    assert "from-config" in _read(plain["tools"])
    none = _dispatched_tools(monkeypatch, configured, scope=None)
    assert none["root"] == configured.resolve()
    with_scope = _dispatched_tools(monkeypatch, configured, scope=scopes().scope(scoped))
    assert with_scope["root"] == scoped.resolve()
    assert "from-scope" in _read(with_scope["tools"])


async def _what_a_builder_sees(runtime, parent_root: Path, **kwargs) -> list[str]:
    from thomas.forge.anvil import build_agent_team as team
    from thomas.forge.anvil.build_agent_writer import BuildTeamTool
    from thomas.tools.filesystem import register_filesystem_tools
    from thomas.tools.registry import ToolRegistry
    from thomas.tools.task_spawn import SpawnAgentTool

    seen: list[str] = []

    async def run(_id, _title, _brief, *, workspace, toolset):
        seen.append((workspace.root / "f.txt").read_text(encoding="utf-8"))
        yield {"type": "text", "text": "ok"}

    registry = ToolRegistry()
    register_filesystem_tools(registry, parent_root)
    tool = BuildTeamTool(
        review_tool=SpawnAgentTool(run_child=run, record_event=lambda *_: None),
        run_child=run,
        record_event=lambda *_: None,
        parent=registry,
        config=runtime,
        deadline=asyncio.get_running_loop().time() + 10,
        can_write=True,
        protected_paths=[],
        read_subset=team.review_tools,
        **kwargs,
    )
    await tool.execute({"title": "T", "instructions": "do", "path": "out.txt"})
    return seen


@pytest.mark.asyncio
async def test_the_build_writer_copies_the_configured_project_without_a_scope_and_the_scope_with_one(
    runtime, tmp_path
) -> None:
    configured, scoped = _worlds(tmp_path)
    runtime.tools.sandbox_root = str(configured)
    assert await _what_a_builder_sees(runtime, configured) == ["from-config"]
    assert await _what_a_builder_sees(runtime, configured, scope=None) == ["from-config"]
    assert await _what_a_builder_sees(runtime, configured, scope=scopes().scope(scoped)) == ["from-scope"]


def test_the_boot_doctor_tools_follow_the_scope_and_default_to_the_root(tmp_path) -> None:
    from thomas.bootdoctor.runtime_helpers import build_restricted_tools

    configured, scoped = tmp_path / "root", tmp_path / "other"
    for folder, text in ((configured, "from-root"), (scoped, "from-scope")):
        (folder / "scripts").mkdir(parents=True)
        (folder / "scripts" / "f.txt").write_text(text, encoding="utf-8")

    def read(registry) -> str:
        return _run(registry.get("fs.read_file").execute({"path": "scripts/f.txt"})).to_content()

    plain, plain_policy = build_restricted_tools(configured)
    assert "from-root" in read(plain)
    none, _ = build_restricted_tools(configured, None)
    assert "from-root" in read(none)
    scoped_tools, scoped_policy = build_restricted_tools(configured, scopes().scope(scoped))
    assert "from-scope" in read(scoped_tools)
    assert scoped_policy.root == scoped.resolve() and plain_policy.root == configured.resolve()
    # The refusal wording is the same with and without a scope.
    refused = _run(plain.get("fs.read_file").execute({"path": "elsewhere/x.txt"})).error
    refused_scoped = _run(scoped_tools.get("fs.read_file").execute({"path": "elsewhere/x.txt"})).error
    assert refused and refused == refused_scoped


def test_the_loop_judges_paths_against_its_scope_when_it_carries_one(tmp_path) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from thomas.agent.loop_tool_paths import loop_sandbox_root

    configured, scoped = _worlds(tmp_path)
    config = SimpleNamespace(tools=SimpleNamespace(sandbox_path=configured))
    assert loop_sandbox_root(SimpleNamespace(config=config)) == configured.resolve()
    assert loop_sandbox_root(SimpleNamespace(config=config, scope=None)) == configured.resolve()
    assert loop_sandbox_root(SimpleNamespace(config=config, scope=scopes().scope(scoped))) == scoped.resolve()
    # Something that is not a Scope (an auto-made mock attribute, say) is not one.
    assert loop_sandbox_root(MagicMock(config=config)) == configured.resolve()


def test_the_path_checks_take_the_scope_as_the_root_and_word_every_refusal_the_same(tmp_path) -> None:
    from thomas.agent.loop_tool_paths import _sanitize_write_tool_path, _validate_filesystem_path

    configured, scoped = _worlds(tmp_path)
    outside = str(tmp_path / "elsewhere" / "x.txt")
    cases = [
        {"path": "f.txt"},
        {"path": "../x.txt"},
        {"path": outside},
        {"path": str(scoped / "f.txt")},
        {"path": "a\x00b"},
        {"path": "C:/x"},
        {"path": "https://x"},
        {"file": "docs/a.md", "path": "secret/b.md"},
    ]
    for protected in (None, ["secret"]):
        for args in cases:
            by_root = _sanitize_write_tool_path(dict(args), sandbox_root=scoped, protected_paths=protected)
            by_scope = _sanitize_write_tool_path(dict(args), scope=scopes().scope(scoped), protected_paths=protected)
            assert by_scope == by_root, args
            assert _sanitize_write_tool_path(dict(args), protected_paths=protected) == _sanitize_write_tool_path(
                dict(args), scope=None, protected_paths=protected
            )
    for value in ("f.txt", outside, "../x", str(scoped / "f.txt")):
        assert _validate_filesystem_path(value, scope=scopes().scope(scoped)) == _validate_filesystem_path(
            value, sandbox_root=scoped
        )
    # A scope's root is what an absolute path is judged against, and the refusal names it as before.
    _, error = _validate_filesystem_path(outside, scope=scopes().scope(scoped))
    assert error == (
        f"absolute paths are not allowed outside the sandbox root {scoped.resolve()}; this path resolves outside it"
    )
    assert _validate_filesystem_path(outside) == (None, "absolute paths are not allowed")
    assert _validate_filesystem_path(str(scoped / "f.txt"), scope=scopes().scope(scoped))[1] is None
