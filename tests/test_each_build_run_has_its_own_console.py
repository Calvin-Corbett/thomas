"""Each Build run, and each test run of the check before your card, gets its own hidden console.

On 2026-09-26 the caged server and every process it started shared one console, and a console Ctrl+C from
anything in that tree reached all of them: the server's log read "[thomas] Stopped by user." with nobody at it, and
from 00:42 to 01:09 every Build run it hosted was stopped with KeyboardInterrupt, all at once, every few minutes.
The server now ignores a stray Ctrl+C; these keep each run on a console of its own, so a Ctrl+C sent inside one run
reaches that run and nothing else.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.test_code_never_runs_in_thomas_own_source import _drive, _init_repo
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server.proof import environment
from thomas.server.routes import evolve_agent_http_support

pytestmark = pytest.mark.skipif(os.name != "nt", reason="consoles are a Windows matter")


def test_a_build_run_is_started_on_its_own_hidden_console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = tmp_path / "thomas-source"
    project = tmp_path / "a-real-project"
    for root in (catalog, project):
        root.mkdir()
        _init_repo(root)
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: catalog.resolve())
    launches: list[dict[str, Any]] = []

    async def _spawn(_executable: str, *_args: str, **kwargs: Any) -> Any:
        launches.append(kwargs)
        raise RuntimeError("stop here: the launch itself is the proof")

    async def _access_token(_profile: str, *, secret_store: object) -> str:
        return "live-oauth-token"

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
    monkeypatch.setattr(evolve_agent_http_support, "ensure_openai_codex_access_token", _access_token)
    cid = forge_code_store.new_conversation(project, title="a real task")["id"]
    forge_code_projects.bind_conversation(catalog, cid, project)

    async def _body(client) -> None:
        await client.post(
            "/api/evolve/agent/send",
            json={"conversation_id": cid, "message": "go", "model": "codex:gpt", "model_id": "gpt-5.6-codex"},
        )

    _drive(catalog, _body)
    assert launches, "the Build runner was never launched"
    assert launches[0].get("creationflags") == subprocess.CREATE_NO_WINDOW


def test_a_check_test_run_is_started_on_its_own_hidden_console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def _run(command, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return subprocess.CompletedProcess(command, 0, "1 passed", "")

    monkeypatch.setattr(environment.subprocess, "run", _run)
    code, out = environment.run_quietly(["python", "-m", "pytest"], cwd=tmp_path, env={}, timeout_s=5)

    assert (code, out) == (0, "1 passed")
    assert calls[0].get("creationflags") == subprocess.CREATE_NO_WINDOW
