"""Private Build files are verified in their own workspace before integration."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_build_agent_team import OfflineClient, runtime  # noqa: F401
from thomas.agent import acceptance_runtime, loop_completion
from thomas.core.llm_shared import StreamEvent
from thomas.forge.anvil import build_agent_team as team
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_child", [False, True])
async def test_concurrent_builders_verify_private_outputs_with_contract_enabled(
    monkeypatch, runtime, tmp_path, wrong_child
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "1")
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "1")
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "0")
    monkeypatch.setattr(acceptance_runtime, "load_learned", lambda *_: [])
    monkeypatch.setattr(acceptance_runtime, "record_misses", lambda *_: None)
    runtime.models["selected"].context_window = 65536
    runtime.models["selected"].max_tokens = 1024
    runtime.max_agent_iterations = 4
    started, release = set(), asyncio.Event()
    observed = []
    rules = []
    real_rules = loop_completion.evaluate_rules

    def observe_rules(**kwargs):
        result = real_rules(**kwargs)
        rules.append((str(kwargs["repo_root"]), result))
        return result

    monkeypatch.setattr(loop_completion, "evaluate_rules", observe_rules)
    real_begin = acceptance_runtime.begin_contract

    def observe_begin(loop, **kwargs):
        text = real_begin(loop, **kwargs)
        if not kwargs.get("attempt"):
            observed.append((loop, getattr(loop, "_acceptance_state", None)))
        return text

    monkeypatch.setattr("thomas.agent.loop_turn_context.begin_contract", observe_begin)

    class Model(OfflineClient):
        async def stream_chat(self, messages, tools):
            assert self.config.model == "gpt-5.6-luna"
            prompt = "\n".join(str(message.get("content", "")) for message in messages)
            name = "alpha.txt" if "OWNED=alpha.txt" in prompt else "beta.txt"
            if not getattr(self, "wrote", False):
                self.wrote = True
                started.add(name)
                if len(started) == 2:
                    release.set()
                await release.wait()
                # Both loops share process cwd; neither has integrated its result.
                assert Path.cwd() == tmp_path
                assert not (tmp_path / "alpha.txt").exists()
                assert not (tmp_path / "beta.txt").exists()
                assert {"remember", "task.spawn", "task.team", "shell.exec"}.isdisjoint(
                    spec["function"]["name"] for spec in tools
                )
                yield StreamEvent(type="tool_call_start", data={"id": name, "name": "fs.write_file"})
                yield StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": name,
                        "name": "fs.write_file",
                        "arguments": json.dumps(
                            {
                                "path": name,
                                "content": "wrong" if wrong_child and name == "beta.txt" else name,
                            }
                        ),
                    },
                )
            elif not getattr(self, "read_back", False):
                self.read_back = True
                yield StreamEvent(
                    type="tool_call_start",
                    data={"id": name + "-read", "name": "fs.read_file"},
                )
                yield StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": name + "-read",
                        "name": "fs.read_file",
                        "arguments": json.dumps({"path": name}),
                    },
                )
            else:
                yield StreamEvent(
                    type="token",
                    data={
                        "text": (
                            f"Created {name}.\nEVIDENCE: fs.write_file succeeded.\n"
                            f"VERIFY: python -c \"from pathlib import Path; assert Path('{name}').read_text() == '{name}'\""
                        )
                    },
                )
            yield StreamEvent(type="done", data={})

    monkeypatch.setattr(team, "LLMClient", Model)
    registry = ToolRegistry()
    register_filesystem_tools(registry, tmp_path)
    events = []
    team.register_build_team(
        registry,
        config=runtime,
        model_config=runtime.models["selected"],
        emit=events.append,
        timeout=30,
        autonomy_level=3,
        tools_policy="auto",
        token_economy="cheap",
        protected_paths=[],
        can_write=True,
    )
    results = await asyncio.wait_for(
        asyncio.gather(
            *[
                registry.execute(
                    "task.spawn",
                    {
                        "title": name,
                        "path": name,
                        "instructions": f"Create `{name}` with the text {name}. OWNED={name}",
                    },
                )
                for name in ("alpha.txt", "beta.txt")
            ]
        ),
        timeout=30,
    )
    assert results[0].ok, results[0].error
    assert results[1].ok is (not wrong_child), results[1].error
    assert len(observed) == 2
    roots = {Path(state["workspace"]) for _, state in observed}
    assert len(roots) == 2 and tmp_path not in roots
    for loop, state in observed:
        assert Path(state["workspace"]) == loop.config.tools.sandbox_path
        paths = [Path(item.target) for item in state["items"] if item.kind == "output_path"]
        assert paths and all(path.parent == loop.config.tools.sandbox_path for path in paths)
    assert (tmp_path / "alpha.txt").read_text() == "alpha.txt"
    if wrong_child:
        assert not (tmp_path / "beta.txt").exists()
        assert "blocked" in results[1].error.lower() or "unmet" in results[1].error.lower()
        assert not any(event.get("fc") == "final" for event in events)
    else:
        assert (tmp_path / "beta.txt").read_text() == "beta.txt"
    assert rules and all(Path(root) in roots for root, _report in rules)
    assert all(report["passed"] for _root, report in rules)
    assert all(client.closed for client in OfflineClient.instances)
    assert Path.cwd() == tmp_path


def test_ordinary_loop_retains_cwd_and_private_loop_uses_the_existing_tool_root(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    private = tmp_path / "private"
    parent.mkdir()
    private.mkdir()
    monkeypatch.chdir(parent)
    loop = SimpleNamespace(config=SimpleNamespace(tools=SimpleNamespace(sandbox_path=private)))
    assert acceptance_runtime.verification_workspace(loop) == parent
    loop.verify_in_tool_workspace = True
    assert acceptance_runtime.verification_workspace(loop) == private
    assert Path.cwd() == parent


def test_ordinary_loop_ignores_an_owned_output_hint_without_private_workspace_opt_in(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "1")
    monkeypatch.setattr(acceptance_runtime, "load_learned", lambda *_: [])
    loop = SimpleNamespace(
        config=SimpleNamespace(tools=SimpleNamespace(sandbox_path=tmp_path)),
        llm=SimpleNamespace(config=SimpleNamespace(reasoning_effort="medium")),
        acceptance_owned_output="index.html",
    )
    acceptance_runtime.begin_contract(loop, prompt_text="Create js/game.js.", route_path="coding")
    outputs = [item for item in loop._acceptance_state["items"] if item.kind == "output_path"]
    assert [item.target for item in outputs] == [str(tmp_path / "js/game.js")]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["complete", "missing", "empty", "missing_verify", "failed_verify"])
async def test_html_builder_acceptance_respects_its_assignment(monkeypatch, runtime, tmp_path, case):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "1")
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "1")
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "0")
    monkeypatch.setattr(acceptance_runtime, "load_learned", lambda *_: [])
    monkeypatch.setattr(acceptance_runtime, "record_misses", lambda *_: None)
    runtime.models["selected"].reasoning_effort = "medium"
    runtime.models["selected"].context_window = 65536
    runtime.models["selected"].max_tokens = 1024
    runtime.max_agent_iterations = 4
    states = []
    real_begin = acceptance_runtime.begin_contract

    def observe_begin(loop, **kwargs):
        block = real_begin(loop, **kwargs)
        if not kwargs.get("attempt"):
            states.append(loop._acceptance_state)
        return block

    monkeypatch.setattr("thomas.agent.loop_turn_context.begin_contract", observe_begin)
    html = (
        '<!doctype html><html><link rel="stylesheet" href="styles.css"><script src="js/game.js" defer></script></html>'
    )

    class Model(OfflineClient):
        calls = 0

        async def stream_chat(self, messages, tools):
            self.calls += 1
            assert self.config.model == "gpt-5.6-luna"
            if self.calls <= 2:
                name = "fs.write_file" if self.calls == 1 and case != "missing" else "fs.read_file"
                args = {"path": "index.html"}
                if name == "fs.write_file":
                    args["content"] = "" if case == "empty" else html
                yield StreamEvent(type="tool_call_start", data={"id": str(self.calls), "name": name})
                yield StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": str(self.calls),
                        "name": name,
                        "arguments": json.dumps(args),
                    },
                )
            else:
                reply = "Created the assigned page.\nEVIDENCE: read back index.html."
                if case == "failed_verify":
                    reply += '\nVERIFY: python -c "raise SystemExit(7)"'
                elif case != "missing_verify":
                    reply += (
                        '\nVERIFY: python -c "from pathlib import Path; '
                        "s=Path('index.html').read_text(); assert 'styles.css' in s and 'js/game.js' in s and 'defer' in s\""
                    )
                yield StreamEvent(type="token", data={"text": reply})
            yield StreamEvent(type="done", data={})

    monkeypatch.setattr(team, "LLMClient", Model)
    registry = ToolRegistry()
    register_filesystem_tools(registry, tmp_path)
    events = []
    team.register_build_team(
        registry,
        config=runtime,
        model_config=runtime.models["selected"],
        emit=events.append,
        timeout=20,
        autonomy_level=3,
        tools_policy="auto",
        token_economy="cheap",
        protected_paths=[],
        can_write=True,
    )
    result = await asyncio.wait_for(
        registry.execute(
            "task.spawn",
            {
                "title": "HTML page",
                "path": "index.html",
                "context_files": [],
                "instructions": "Create index.html. It must load styles.css and js/game.js with defer.",
            },
        ),
        timeout=25,
    )
    assert result.ok is (case == "complete"), result.error
    assert states
    state = states[0]
    owned = [item for item in state["items"] if item.kind == "output_path"]
    assert [item.target for item in owned] == [str(Path(state["workspace"]) / "index.html")]
    assert not (Path(state["workspace"]) / "js/game.js").exists()
    assert not (tmp_path / "js/game.js").exists()
    failures = {item.item_id for item in state["items"] if item.checked and not item.satisfied}
    if case == "complete":
        assert (tmp_path / "index.html").read_text(encoding="utf-8") == html
        assert not failures and state["rounds"] == 0
    else:
        assert not (tmp_path / "index.html").exists()
        assert state["rounds"] == 1
        assert "output:js/game.js" not in failures
        assert ("output:index.html" in failures) is (case in {"missing", "empty"})
        assert "finish:verify" in failures
        assert not any(event.get("fc") == "final" for event in events)
    assert all(client.closed for client in OfflineClient.instances)
    assert Path.cwd() == tmp_path
