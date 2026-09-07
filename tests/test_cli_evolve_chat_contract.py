from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

import thomas.cli._commands_base as commands_base
from thomas.cli._commands_base import chat
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.forge.anvil.evolve_runtime_exec import _build_green_chat_command


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
    )


def test_generated_evolve_command_reaches_chat_runtime(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_chat(
        _config,
        prompt,
        model_name,
        *,
        autonomy_level,
        max_iterations,
        job_type,
    ):
        captured.update(
            prompt=prompt,
            model_name=model_name,
            autonomy_level=autonomy_level,
            max_iterations=max_iterations,
            job_type=job_type,
        )
        return {
            "outcome": "success",
            "model_profile": model_name,
            "model_id": "dummy",
            "artifacts": [],
        }

    monkeypatch.delenv("THOMAS_DEFAULT_MODEL", raising=False)
    monkeypatch.setattr(commands_base, "_run_chat", fake_run_chat)
    command = _build_green_chat_command(
        "python",
        "local",
        "Improve one eligible goal",
        max_iterations="4",
    )

    result = CliRunner().invoke(
        chat,
        command[4:],
        obj={"config": _config(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "prompt": "Improve one eligible goal",
        "model_name": "local",
        "autonomy_level": 4,
        "max_iterations": 4,
        "job_type": "self_development",
    }


def test_chat_rejects_nonpositive_internal_iteration_limit(tmp_path) -> None:
    result = CliRunner().invoke(
        chat,
        ["--max-iterations", "0", "Do not run"],
        obj={"config": _config(tmp_path)},
    )

    assert result.exit_code == 2
    assert "0 is not in the range x>=1" in result.output
