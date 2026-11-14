"""Productive helpers use private files and only integrate completed current candidates."""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from tests.test_build_agent_team import OfflineClient, runtime  # noqa: F401 - shared offline fixture
from thomas.core import llm_client
from thomas.core.llm import StreamEvent
from thomas.forge.anvil import build_agent_team as team
from thomas.forge.anvil import dispatch_agent_loop as dispatch
from thomas.forge.anvil.build_agent_writer import BuildTeamTool
from thomas.tools.base import ToolResult
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.task_spawn import SpawnAgentTool


def writer(runtime, tmp_path, runner, *, can_write=True, protected=()):
    registry = ToolRegistry()
    register_filesystem_tools(registry, tmp_path)
    review = SpawnAgentTool(run_child=runner, record_event=lambda *_: None)
    return BuildTeamTool(
        review_tool=review,
        run_child=runner,
        record_event=lambda *_: None,
        parent=registry,
        config=runtime,
        deadline=asyncio.get_running_loop().time() + 10,
        can_write=can_write,
        protected_paths=list(protected),
        read_subset=team.review_tools,
    )


@pytest.mark.asyncio
async def test_builder_writes_private_file_and_integrates_through_parent(runtime, tmp_path):
    (tmp_path / "ui.html").write_bytes(b"unmerged UI\r\n")
    roots = []

    async def run(_id, _title, _brief, *, workspace, toolset):
        roots.append(workspace.root)
        assert (workspace.root / "ui.html").read_bytes() == b"unmerged UI\r\n"
        assert toolset.get("task.spawn") is None and toolset.get("shell.exec") is None
        assert toolset.get("check.run") is None
        assert not (await toolset.execute("fs_write_file", {"path": "ui.html", "content": "bad"})).ok
        assert (await toolset.execute("fs.write_file", {"path": "styles.css", "content": "body{color:orange}"})).ok
        assert not (tmp_path / "styles.css").exists()
        yield {"type": "text", "text": "Created the stylesheet"}

    tool = writer(runtime, tmp_path, run)
    writes = []
    execute = tool._parent.execute

    async def observed(name, args):
        writes.append((name, args))
        return await execute(name, args)

    tool._parent.execute = observed
    result = await tool.execute({"title": "Styles", "instructions": "Create styles", "path": "styles.css"})
    assert result.ok and "Integrated styles.css" in result.data
    assert (tmp_path / "styles.css").read_text(encoding="utf-8") == "body{color:orange}"
    assert (tmp_path / "ui.html").read_bytes() == b"unmerged UI\r\n"
    assert writes == [("fs.write_file", {"path": "styles.css", "content": "body{color:orange}"})]
    receipt = json.loads((roots[0].parent / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["state"] == "integrated" and receipt["integrated_file"]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["error", "cancel", "stale", "empty"])
async def test_failed_cancelled_or_stale_child_never_applies(runtime, tmp_path, outcome):
    (tmp_path / "a.txt").write_text("original", encoding="utf-8")
    started = asyncio.Event()
    roots = []

    async def run(_id, _title, _brief, *, workspace, toolset):
        roots.append(workspace.root)
        assert (await toolset.execute("fs.write_file", {"path": "a.txt", "content": "candidate"})).ok
        started.set()
        if outcome == "cancel":
            await asyncio.Event().wait()
        if outcome == "stale":
            (tmp_path / "a.txt").write_text("new user edit", encoding="utf-8")
        if outcome != "empty":
            yield (
                {"type": "error", "error": "provider failed"}
                if outcome == "error"
                else {"type": "text", "text": "done"}
            )

    pending = asyncio.create_task(
        writer(runtime, tmp_path, run).execute({"title": "A", "instructions": "Write", "path": "a.txt"})
    )
    await started.wait()
    if outcome == "cancel":
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    else:
        assert not (await pending).ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == ("new user edit" if outcome == "stale" else "original")
    receipt = json.loads((roots[0].parent / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["state"] == ("cancelled" if outcome == "cancel" else "failed")


@pytest.mark.asyncio
async def test_inflight_assignment_overlap_is_refused(runtime, tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    async def run(_id, _title, _brief, *, workspace, toolset):
        entered.set()
        await release.wait()
        await toolset.execute("fs.write_file", {"path": workspace.path, "content": "built"})
        yield {"type": "text", "text": "done"}

    tool = writer(runtime, tmp_path, run)
    brief = {"title": "A", "instructions": "Write A", "path": "a.txt"}
    first = asyncio.create_task(tool.execute(brief))
    await entered.wait()
    second = await tool.execute(brief)
    assert not second.ok and "already owns" in second.error
    release.set()
    assert (await first).ok
    assert not tool._active_paths


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["readonly", "protected", "binary", "large", "extra_policy"])
async def test_authority_and_text_bounds_refuse_before_model(runtime, tmp_path, condition):
    called = []

    async def run(*_args, **_kwargs):
        called.append(True)
        yield {"type": "text", "text": "unexpected"}

    tool = writer(
        runtime,
        tmp_path,
        run,
        can_write=condition != "readonly",
        protected=["a.txt"] if condition == "protected" else [],
    )
    if condition == "binary":
        (tmp_path / "a.txt").write_bytes(b"\xff\0")
    if condition == "large":
        runtime.tools.max_file_size = 2
        (tmp_path / "a.txt").write_text("large", encoding="utf-8")
    if condition == "extra_policy":
        tool._parent.policy = object()
    result = await tool.execute({"title": "A", "instructions": "Write", "path": "a.txt"})
    assert not result.ok and not called
    assert not (tmp_path / ".thomas").exists()


@pytest.mark.asyncio
async def test_real_build_loops_form_two_files_on_selected_luna(monkeypatch, runtime, tmp_path):
    from thomas.agent import acceptance_runtime, loop_completion

    (tmp_path / "index.html").write_text(
        "<link rel=stylesheet href=styles.css><script src=app.js></script>", encoding="utf-8"
    )
    before = (tmp_path / "index.html").read_bytes()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "0")
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "1")
    monkeypatch.setattr(acceptance_runtime, "load_learned", lambda *_: [])
    monkeypatch.setattr(acceptance_runtime, "record_misses", lambda *_: None)
    monkeypatch.setattr(loop_completion, "evaluate_rules", lambda **_: {"passed": True, "checks": []})
    runtime.models["selected"].context_window = 65536
    runtime.models["selected"].max_tokens = 512
    contents = {"styles.css": "body{color:orange}", "app.js": "window.ready=true;"}

    class Model(OfflineClient):
        def __init__(self, *args, **kwargs):
            self.child = bool(self.instances)
            self.calls = 0
            self.receipts = []
            super().__init__(*args, **kwargs)

        async def stream_chat(self, messages, tools):
            self.calls += 1
            self.receipts.extend(message for message in messages if message.get("role") == "tool")
            if self.calls == 1:
                if self.child:
                    prompt = "\n".join(
                        str(message.get("content")) for message in messages if message.get("role") == "user"
                    )
                    path = next(path for path in contents if f"OWNED={path}" in prompt)
                    self.path = path
                    calls = [("fs.write_file", {"path": path, "content": contents[path]})]
                else:
                    calls = [
                        ("task.spawn", {"title": path, "instructions": f"Create {path}. OWNED={path}", "path": path})
                        for path in contents
                    ]
                for index, (name, args) in enumerate(calls):
                    yield StreamEvent(type="tool_call_start", data={"id": f"c{index}", "name": name})
                    yield StreamEvent(
                        type="tool_call_end", data={"id": f"c{index}", "name": name, "arguments": json.dumps(args)}
                    )
            else:
                reply = "Created the assigned files."
                if self.child:
                    reply += (
                        f"\nEVIDENCE: {self.receipts[-1]['content']}\n"
                        f'VERIFY: python -c "from pathlib import Path; '
                        f'assert Path({self.path!r}).read_text() == {contents[self.path]!r}"'
                    )
                yield StreamEvent(type="token", data={"text": reply})
            yield StreamEvent(type="done", data={})

    monkeypatch.setattr(llm_client, "LLMClient", Model)
    monkeypatch.setattr(team, "LLMClient", Model)
    events = []
    rc, _ = await dispatch._agent_loop_pass_async(
        "Create styles.css and app.js with helpers.",
        str(tmp_path),
        15,
        events.append,
        intent_text="Create styles.css and app.js with helpers.",
        profile="selected",
        allow_shell=False,
    )
    assert rc == 0 and len(OfflineClient.instances) == 3
    assert all(client.config.model == "gpt-5.6-luna" and client.closed for client in OfflineClient.instances)
    assert (tmp_path / "index.html").read_bytes() == before
    assert all((tmp_path / path).read_text(encoding="utf-8") == content for path, content in contents.items())
    assert any("Integrated styles.css" in str(receipt) for receipt in OfflineClient.instances[0].receipts)
    assert any(
        event.get("agent_mode") == "builder" and "Integrated app.js" in event.get("text", "") for event in events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["deadline", "parent_denial", "oversize", "binary"])
async def test_integration_refusal_keeps_original_file(runtime, tmp_path, reason):
    (tmp_path / "a.txt").write_text("original", encoding="utf-8")
    if reason == "oversize":
        runtime.tools.max_file_size = 10

    async def run(_id, _title, _brief, *, workspace, toolset):
        if reason in {"oversize", "binary"}:
            # Test candidate validation independently of the model tool fence.
            (workspace.root / workspace.path).write_bytes(b"a" * 11 if reason == "oversize" else b"bad\0file")
        else:
            await toolset.execute("fs.write_file", {"path": "a.txt", "content": "candidate"})
        if reason == "deadline":
            await asyncio.sleep(0.03)
        yield {"type": "text", "text": "done"}

    tool = writer(runtime, tmp_path, run)
    if reason == "deadline":
        tool._deadline = asyncio.get_running_loop().time() + 0.02
    if reason == "parent_denial":

        async def denied(*_args):
            return ToolResult(ok=False, error="parent policy refused")

        tool._parent.execute = denied
    result = await tool.execute({"title": "A", "instructions": "Write", "path": "a.txt"})
    assert not result.ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "original"


@pytest.mark.asyncio
async def test_private_write_rejects_hardlink_swap(runtime, tmp_path):
    outside = tmp_path / "keep.txt"
    outside.write_text("keep unchanged", encoding="utf-8")

    async def run(_id, _title, _brief, *, workspace, toolset):
        os.link(outside, workspace.root / workspace.path)
        result = await toolset.execute("fs.write_file", {"path": "a.txt", "content": "bad"})
        assert not result.ok and "hard-linked" in result.error
        yield {"type": "error", "error": result.error}

    result = await writer(runtime, tmp_path, run).execute({"title": "A", "instructions": "Write", "path": "a.txt"})
    assert not result.ok and not (tmp_path / "a.txt").exists()
    assert outside.read_text(encoding="utf-8") == "keep unchanged"
