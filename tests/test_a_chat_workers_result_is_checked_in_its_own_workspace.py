"""A chat worker's result is checked in the worker's own workspace, not the server's working folder.

A chat background worker's file tools write in its workspace (its tool sandbox), but its acceptance
contract was built and checked in the process working directory. A ``result.txt`` the worker wrote
read as missing, its ``VERIFY:`` command could not find it, and finished work was blocked; a file
that happened to sit in the server's folder could pass for work the worker never did.

These run the real worker runtime, the real AgentLoop and the real acceptance contract. Only the
model is scripted. The contract's build and evaluation calls are observed as they happen
(call-through), so the tests see the directory the real contract used. The working directory is
never changed by the fix: workers run concurrently in threads of one process.

Adapted from the workspace cases of tests/test_a_worker_contract_checks_its_own_task_and_workspace.py
(praxis-native wt-native-trial, 2026-09-19).
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from thomas.agent import acceptance_runtime
from thomas.core import acceptance_contract
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ToolsConfig
from thomas.core.llm_shared import StreamEvent, TokenUsage
from thomas.server import app_helpers, worker_runtime  # noqa: F401 -- app_helpers provides seams.TOOL_SET

TOKEN_RE = re.compile(r"TOKEN=(\w+)")


def _verify(token: str) -> str:
    check = f"import pathlib,sys; sys.exit(0 if pathlib.Path('result.txt').read_text().strip() == '{token}' else 1)"
    return f'VERIFY: "{sys.executable}" -c "{check}"'


class _ScriptedModel:
    """Writes `result.txt` with the task's token, then finishes with a VERIFY command."""

    writes = True

    def __init__(self, config: Any, **_kwargs: Any) -> None:
        self.config = config
        self.session_usage = TokenUsage()

    async def stream_chat(self, messages: list[dict[str, Any]], tools: Any = None, **_kwargs: Any):  # noqa: ANN201
        text = "\n".join(str(m.get("content") or "") for m in messages if isinstance(m, dict))
        match = TOKEN_RE.search(text)
        token = match.group(1) if match else "missing"
        if self.writes and not any(isinstance(m, dict) and m.get("role") == "tool" for m in messages):
            args = json.dumps({"path": "result.txt", "content": token})
            yield StreamEvent("tool_call_start", {"id": "call-1", "name": "fs.write_file", "index": 0})
            yield StreamEvent("tool_call_delta", {"id": "call-1", "delta": args})
            yield StreamEvent("tool_call_end", {"id": "call-1", "name": "fs.write_file", "arguments": args})
        else:
            yield StreamEvent("token", {"text": f"Wrote result.txt.\n{_verify(token)}"})
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        self.session_usage.add(usage)
        yield StreamEvent("usage", {"usage": usage})
        yield StreamEvent("done", {})

    def reset_runtime_trace(self) -> None:
        return None

    def runtime_trace(self) -> dict[str, Any]:
        active = {"profile": self.config.name, "provider": self.config.provider, "model": self.config.model}
        return {
            "requested": dict(active),
            "active": dict(active),
            "failover_used": False,
            "attempts": [{**active, "status": "success"}],
        }

    async def close(self) -> None:
        return None


class _ModelThatWritesNothing(_ScriptedModel):
    """Claims the file and names a VERIFY command, but never calls a tool."""

    writes = False


class _ContractObserver:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.builds: list[dict[str, Any]] = []
        self.evaluations: list[dict[str, Any]] = []
        self.cwds: set[str] = set()

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_build = acceptance_contract.build_contract
        real_evaluate = acceptance_contract.evaluate_contract
        observer = self

        def build(prompt_text: str, workspace: Any, **kwargs: Any) -> Any:
            items = real_build(prompt_text, workspace, **kwargs)
            with observer.lock:
                observer.cwds.add(str(Path.cwd().resolve()))
                observer.builds.append(
                    {"workspace": str(Path(workspace).resolve()), "items": [i.item_id for i in items]}
                )
            return items

        def evaluate(items: Any, **kwargs: Any) -> Any:
            evaluated = real_evaluate(items, **kwargs)
            with observer.lock:
                observer.cwds.add(str(Path.cwd().resolve()))
                observer.evaluations.append(
                    {
                        "workspace": str(Path(kwargs["workspace"]).resolve()),
                        "results": {it.item_id: (it.satisfied, it.detail) for it in evaluated if it.checked},
                    }
                )
            return evaluated

        monkeypatch.setattr(acceptance_contract, "build_contract", build)
        monkeypatch.setattr(acceptance_contract, "evaluate_contract", evaluate)


def _run_worker(root: Path, workspace: Path, task: str) -> list[dict[str, Any]]:
    cfg = AppConfig(
        models={
            "scripted": ModelConfig(
                name="scripted",
                provider="openai_compat",
                model="scripted-model",
                max_tokens=2048,
                context_window=128000,
            )
        },
        default_model="scripted",
        memory=MemoryConfig(root=str(root / "memory")),
        tools=ToolsConfig(allow_shell=False),
    )
    app = {worker_runtime.APP_CONFIG: cfg, worker_runtime.APP_SECRETS: None, worker_runtime.APP_MEMORY: None}

    async def go() -> list[dict[str, Any]]:
        stream = worker_runtime.run_agent_worker_events(
            app,
            prompt=task,
            instructions="You are a background worker.",
            work_dir=workspace,
            profile="scripted",
            reasoning_effort="medium",
            autonomy_level=3,
            memory_enabled=False,
        )
        return [event async for event in stream]

    return asyncio.run(asyncio.wait_for(go(), timeout=240))


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, _ContractObserver]:
    """The server's working folder is its own empty folder, apart from every worker workspace."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "data" / "prefs.sqlite"))
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "1")
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "0")
    monkeypatch.delenv("THOMAS_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("THOMAS_PROFILE", raising=False)
    monkeypatch.setattr(acceptance_runtime, "load_learned", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(acceptance_runtime, "record_misses", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker_runtime, "LLMClient", _ScriptedModel)
    server = tmp_path / "server"
    server.mkdir()
    monkeypatch.chdir(server)
    observer = _ContractObserver()
    observer.install(monkeypatch)
    return tmp_path, server, observer


def _errors(events: list[dict[str, Any]]) -> list[str]:
    return [str(event.get("error") or "") for event in events if event.get("type") == "error"]


def assert_verify_ran_and_passed(evaluations: list[dict[str, Any]]) -> None:
    """Every contract evaluation must contain the reply's VERIFY check, and it must have passed.
    A missing entry means verification never ran, which is not a pass."""
    assert evaluations, "the contract was never evaluated"
    for entry in evaluations:
        assert "finish:verify" in entry["results"], f"VERIFY never ran in {entry['workspace']}: {entry['results']}"
        assert entry["results"]["finish:verify"][0], f"VERIFY failed in {entry['workspace']}: {entry['results']}"


def test_a_result_the_worker_wrote_in_its_workspace_is_found_there(isolated) -> None:
    root, server, observer = isolated
    workspace = root / "worker-a"
    workspace.mkdir()
    events = _run_worker(root, workspace, "TOKEN=alpha1 Create `result.txt` in your workspace containing the token.")

    assert (workspace / "result.txt").read_text(encoding="utf-8").strip() == "alpha1"
    assert observer.builds, "the real contract was never built"
    assert "output:result.txt" in observer.builds[0]["items"], observer.builds[0]["items"]
    assert observer.builds[0]["workspace"] == str(workspace.resolve()), "the contract was built somewhere else"
    assert {entry["workspace"] for entry in observer.evaluations} == {str(workspace.resolve())}
    assert_verify_ran_and_passed(observer.evaluations)
    assert _errors(events) == []
    assert [event["type"] for event in events if event["type"] in {"done", "error"}] == ["done"]
    assert not (server / "result.txt").exists()


def test_a_file_in_the_servers_folder_does_not_count_for_the_worker(isolated, monkeypatch) -> None:
    root, server, observer = isolated
    monkeypatch.setattr(worker_runtime, "LLMClient", _ModelThatWritesNothing)
    (server / "result.txt").write_text("beta2", encoding="utf-8")
    workspace = root / "worker-b"
    workspace.mkdir()
    events = _run_worker(root, workspace, "TOKEN=beta2 Create `result.txt` in your workspace containing the token.")

    assert not (workspace / "result.txt").exists()
    assert str(server.resolve()) not in {entry["workspace"] for entry in observer.evaluations}
    errors = _errors(events)
    assert errors and "result.txt" in errors[-1], f"work the worker never did was accepted: {events}"
    assert "done" not in [event["type"] for event in events]


def test_two_workers_each_check_their_own_workspace_at_the_same_time(isolated) -> None:
    root, _server, observer = isolated
    runs = {"gamma3": root / "worker-c", "delta4": root / "worker-d"}
    results: dict[str, list[dict[str, Any]]] = {}
    start = threading.Barrier(len(runs))

    def work(token: str, workspace: Path) -> None:
        workspace.mkdir()
        start.wait(timeout=30)
        results[token] = _run_worker(root, workspace, f"TOKEN={token} Create `result.txt` in your workspace.")

    threads = [threading.Thread(target=work, args=(token, ws)) for token, ws in runs.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=240)

    for token, workspace in runs.items():
        assert token in results, f"{token}: the worker never finished"
        assert (workspace / "result.txt").read_text(encoding="utf-8").strip() == token
        assert _errors(results[token]) == [], f"{token}: {_errors(results[token])}"
    checked = {entry["workspace"] for entry in observer.evaluations}
    assert checked == {str(ws.resolve()) for ws in runs.values()}, f"a contract was checked somewhere else: {checked}"
    assert_verify_ran_and_passed(observer.evaluations)


def test_the_process_working_folder_never_moves(isolated) -> None:
    root, server, observer = isolated
    workspace = root / "worker-e"
    workspace.mkdir()
    _run_worker(root, workspace, "TOKEN=epsilon5 Create `result.txt` in your workspace containing the token.")

    assert observer.cwds == {str(server.resolve())}, f"the working folder moved while the contract ran: {observer.cwds}"
    assert Path.cwd().resolve() == server.resolve()


def test_evidence_without_a_verify_result_is_not_a_pass() -> None:
    """Synthetic red for the check above: the same evidence with the VERIFY entry removed must fail it."""
    real_shape = [{"workspace": "w", "results": {"output:result.txt": (True, "present"), "finish:verify": (True, "")}}]
    assert_verify_ran_and_passed(real_shape)
    without_verify = [{"workspace": "w", "results": {"output:result.txt": (True, "present")}}]
    with pytest.raises(AssertionError, match="VERIFY never ran"):
        assert_verify_ran_and_passed(without_verify)
