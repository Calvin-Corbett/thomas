"""Headless Thomas has the same sign-in the server has.

2026-09-05: a scheduled task fired on time, spawned ``python -m thomas chat``
and died with "ChatGPT OAuth is not connected", because the only place that
registers the ChatGPT token resolver is a server module the CLI never
imports. ``thomas.cli.headless_run`` imports it first, then runs chat.
"""

from __future__ import annotations

import importlib
import sys


def test_importing_the_runner_registers_the_chatgpt_token_resolver(monkeypatch) -> None:
    from thomas.core import codex_auth

    monkeypatch.setattr(codex_auth, "_access_token_resolver", None)
    sys.modules.pop("thomas.cli.headless_run", None)

    module = importlib.import_module("thomas.cli.headless_run")

    assert codex_auth._access_token_resolver is not None
    assert callable(module.main)


def test_the_scheduler_executor_spawns_the_runner(tmp_path, monkeypatch) -> None:
    from thomas.core.schedule_executor import make_subprocess_executor

    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        seen.append(list(cmd))

        class _Done:
            returncode = 0
            stdout = "pong"
            stderr = ""

        return _Done()

    monkeypatch.setattr("thomas.core.schedule_executor.subprocess.run", fake_run)
    make_subprocess_executor(log_dir=tmp_path, timeout_s=10)("Reply with pong", "default")

    assert seen[0][:3] == [sys.executable, "-m", "thomas.cli.headless_run"]
    assert seen[0][-1] == "Reply with pong"
