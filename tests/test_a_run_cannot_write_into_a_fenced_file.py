"""A run's file fence is enforced by the write tools, not stated in the brief (2026-09-06).

A Build run on Thomas's own checkout was told, in its brief, not to edit six
files another agent held. It edited two of them anyway, collided with that
agent's repair, and was stopped. A fence that lives only in prose is advice to
the model; the tools it writes with enforce nothing.

The loop now carries ``protected_paths``: paths, relative to the sandbox root,
that no write tool may touch for this run. A write into one comes back as a
refused tool result that names the fence, the file is untouched, and writes
elsewhere proceed as before. The engine that starts a run sets the list from
whatever fenced the run (a brief's boundary, another agent's claim).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _WriteTool(Tool):
    """A write tool that really writes, so an untouched file proves the refusal."""

    name = "fs.write_file"
    category = "test"
    description = "write a file"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}

    def __init__(self, root: Path) -> None:
        self.root = root

    async def execute(self, args):  # noqa: ANN001
        target = Path(args["path"])
        if not target.is_absolute():
            target = self.root / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(args.get("content", "")), encoding="utf-8")
        return ToolResult(ok=True, data={"path": str(target)})


class _WritesTwoFilesLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self._calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        self._calls += 1
        plan = {
            1: ("t1", '{"path":"thomas/forge/anvil/held.py","content":"# overwritten by the run"}'),
            2: ("t2", '{"path":"thomas/server/web/js/free.js","content":"// written by the run"}'),
        }
        if self._calls in plan:
            tool_id, arguments = plan[self._calls]
            yield StreamEvent(type="tool_call_start", data={"id": tool_id, "name": "fs.write_file"})
            yield StreamEvent(
                type="tool_call_end", data={"id": tool_id, "name": "fs.write_file", "arguments": arguments}
            )
            yield StreamEvent(type="done", data={})
            return
        yield StreamEvent(type="token", data={"text": "Done."})
        yield StreamEvent(type="done", data={})


def test_a_write_into_a_fenced_path_is_refused_and_the_file_untouched(tmp_path: Path) -> None:
    held = tmp_path / "thomas" / "forge" / "anvil" / "held.py"
    held.parent.mkdir(parents=True)
    held.write_text("# another agent's repair\n", encoding="utf-8")

    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    cfg.tools.sandbox_root = str(tmp_path)
    tools = ToolRegistry()
    tools.register(_WriteTool(tmp_path))
    agent = AgentLoop(cfg, _WritesTwoFilesLLM(), tools, conversation=[])
    agent.protected_paths = ["thomas/forge/anvil/held.py"]

    async def _collect():
        return [ev async for ev in agent.run("edit both files", tools_policy="always")]

    events = asyncio.run(_collect())
    results = [ev for ev in events if ev.type == EventType.TOOL_RESULT]
    assert len(results) == 2, [ev.type for ev in events]
    refused, allowed = results[0].data, results[1].data
    assert refused["ok"] is False
    assert "held.py" in str(refused["result_text"]) and "fence" in str(refused["result_text"]).lower()
    assert held.read_text(encoding="utf-8") == "# another agent's repair\n"
    assert allowed["ok"] is True
    assert (tmp_path / "thomas" / "server" / "web" / "js" / "free.js").read_text(
        encoding="utf-8"
    ) == "// written by the run"


# ---------------------------------------------------------------------------
# A patch names its targets inside the patch text, not in a path argument. An
# audit (codex-image-takeover, 2026-09-07) drove the real diff.apply_patch with
# a unified diff against a fenced file and it went through: the sanitizer never
# saw a path. The fence must read the patch's own headers, both formats.
# ---------------------------------------------------------------------------

UNIFIED = "--- a/held.txt\n+++ b/held.txt\n@@ -1 +1 @@\n-original\n+overwritten\n"
CODEX = "*** Begin Patch\n*** Update File: held.txt\n@@\n-original\n+overwritten\n*** End Patch\n"


class _PatchOnceLLM:
    def __init__(self, patch: str) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self._patch = patch
        self._calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        self._calls += 1
        if self._calls == 1:
            import json

            args = json.dumps({"patch": self._patch})
            yield StreamEvent(type="tool_call_start", data={"id": "p1", "name": "diff.apply_patch"})
            yield StreamEvent(type="tool_call_end", data={"id": "p1", "name": "diff.apply_patch", "arguments": args})
            yield StreamEvent(type="done", data={})
            return
        yield StreamEvent(type="token", data={"text": "Done."})
        yield StreamEvent(type="done", data={})


def _patch_run(tmp_path: Path, patch: str) -> tuple[Path, list]:
    from thomas.tools.diff import ApplyPatchTool

    held = tmp_path / "held.txt"
    held.write_text("original\n", encoding="utf-8")
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    cfg.tools.sandbox_root = str(tmp_path)
    cfg.memory.root = str(tmp_path / "private-runtime")
    tools = ToolRegistry()
    tools.register(ApplyPatchTool(tmp_path))
    agent = AgentLoop(cfg, _PatchOnceLLM(patch), tools, conversation=[])
    agent.protected_paths = ["held.txt"]

    async def _collect():
        return [ev async for ev in agent.run("Edit this file", tools_policy="always")]

    events = asyncio.run(_collect())
    return held, [ev.data for ev in events if ev.type == EventType.TOOL_RESULT]


def test_a_unified_diff_against_a_fenced_file_is_refused(tmp_path: Path) -> None:
    held, results = _patch_run(tmp_path, UNIFIED)
    assert results and results[0]["ok"] is False, results
    assert "held.txt" in str(results[0]["result_text"]) and "fence" in str(results[0]["result_text"]).lower()
    assert held.read_text(encoding="utf-8") == "original\n"


def test_a_codex_patch_against_a_fenced_file_is_refused(tmp_path: Path) -> None:
    held, results = _patch_run(tmp_path, CODEX)
    assert results and results[0]["ok"] is False, results
    assert held.read_text(encoding="utf-8") == "original\n"
