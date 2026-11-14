"""`bootdoctor rescue` ends with its report when something that is not Thomas holds the port.

A model repair pass edits files, which cannot free a port another program holds, and the launcher starts a rescue
with no window: the interactive prompt that follows the passes would be left waiting for typing nobody can see.
Before this, a listener that was not Thomas was reported as "Thomas is healthy again"; the report now names it, and the
rescue stops there. With the port free, the rescue still goes on to its repair pass.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import thomas.bootdoctor.__main__ as bd_main
import thomas.core.boot_doctor as boot_doctor
from tests._bootdoctor_fakes import (
    ForeignServer,
    fake_owners,
    free_port,
    isolate_offline_checks,
    listener,
    raw_listener,
)
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    fake_owners(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(boot_doctor, "_run_cmd", lambda *args, **kwargs: (True, "exit=0"))
    monkeypatch.setattr("builtins.input", lambda *args: pytest.fail("the rescue waited for typed input"))


def _rescue(tmp_path: Path, port: int, *extra: str) -> int:
    models = {"m": ModelConfig(name="m", provider="openai_compat", model="gpt-5")}
    config = AppConfig(memory=MemoryConfig(root=str(tmp_path / "mem")), models=models, default_model="m")
    argv = ["rescue", "--root", str(tmp_path), "--port", str(port), "--no-ai", "--no-auto-repair", *extra]
    return asyncio.run(bd_main._run_rescue(bd_main._build_parser().parse_args(argv), config=config, root=tmp_path))


def _another_program(kind: str):
    return listener(ForeignServer) if kind == "web server" else raw_listener()


def _status(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "runtime" / "boot_doctor" / "rescue_status.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("kind", ["web server", "not a web server"])
def test_a_rescue_ends_at_a_port_another_program_holds_and_asks_no_model(
    tmp_path: Path, monkeypatch, capsys, kind: str
) -> None:
    monkeypatch.setattr(bd_main, "_build_bootdoctor_agent", lambda *a, **k: pytest.fail("a model pass was started"))

    with _another_program(kind) as port:
        exit_code = _rescue(tmp_path, port)  # not --no-interactive: it must not wait at a prompt either

    status = _status(tmp_path)
    assert exit_code == 1
    assert (status["status"], status["phase"]) == ("failed", "awaiting_user")
    assert f"port {port}" in status["message"]
    assert "healthy again" not in capsys.readouterr().out
    assert f"[fail] port_probe: Port {port} " in Path(status["report_path"]).read_text(encoding="utf-8")


def test_a_rescue_with_a_free_port_still_goes_on_to_its_repair_pass(tmp_path: Path, monkeypatch) -> None:
    built: list[bool] = []
    monkeypatch.setattr(bd_main, "_build_bootdoctor_agent", lambda *a, **k: built.append(True) or (None, None, None))

    exit_code = _rescue(tmp_path, free_port(), "--no-interactive")

    assert built == [True]
    assert exit_code == 1  # no rescue model to run, so it ends there, as before
    assert "no rescue model" in _status(tmp_path)["message"]
