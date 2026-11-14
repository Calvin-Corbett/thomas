"""The sandbox slot's ladder is the shell's ladder: four outcomes, the same one for the same inputs.

``thomas/tools/shell.py`` decides how a command is run in ``ShellTool.execute``. The four outcomes, named from that code:

1. disabled: ``allowed`` is false -> "Shell execution is disabled ...", nothing runs.
2. caged: posture is not "off" and the runner answers -> ``run_caged``.
3. refused: posture is "required" and the runner is silent -> "The caged shell is required ...", nothing runs.
4. local: posture "off", or "auto" with a silent runner -> ``run_spooled_command`` as this process.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from thomas.core.kernel import SANDBOX, Kernel
from thomas.tools import sandbox_slot as slot
from thomas.tools import shell as shell_mod
from thomas.tools.cage_shell import CagedResult
from thomas.tools.shell_spool import SpoolResult

# (allowed, posture, runner alive) -> the outcome, for every input the shell reads.
CASES = [
    (False, "off", False, slot.DISABLED),
    (False, "auto", True, slot.DISABLED),
    (False, "required", False, slot.DISABLED),
    (True, "auto", True, slot.CAGED),
    (True, "required", True, slot.CAGED),
    (True, "required", False, slot.REFUSED),
    (True, "auto", False, slot.LOCAL),
    (True, "off", False, slot.LOCAL),
    (True, "off", True, slot.LOCAL),
]


def test_there_are_four_outcomes() -> None:
    assert set(slot.RUNGS) == {"disabled", "caged", "refused", "local"}
    assert len(slot.RUNGS) == 4


def test_the_shell_source_still_has_those_four_branches() -> None:
    source = Path(shell_mod.__file__).read_text(encoding="utf-8")
    for marker in ("is disabled in configuration", "run_caged", "is required and its runner", "run_spooled_command"):
        assert marker in source


def _run_shell(monkeypatch, tmp_path, allowed: bool, posture: str, alive: bool) -> str:
    calls: list[str] = []

    def fake_caged(command, **kwargs):
        calls.append("caged")
        return CagedResult("ok", 0, "out")

    def fake_spooled(command, **kwargs):
        calls.append("local")
        return SpoolResult(
            outcome="ok",
            exit_code=0,
            stdout="out",
            stderr="",
            spool_path=str(tmp_path / "spool.txt"),
            hang_events=[],
            attempts=1,
        )

    monkeypatch.setattr(shell_mod, "cage_posture", lambda *a, **k: posture)
    monkeypatch.setattr(shell_mod, "cage_runner_alive", lambda *a, **k: alive)
    monkeypatch.setattr(shell_mod, "run_caged", fake_caged)
    monkeypatch.setattr(shell_mod, "run_spooled_command", fake_spooled)
    result = asyncio.run(shell_mod.ShellTool(tmp_path, allowed=allowed).execute({"command": "echo hi"}))
    if calls:
        assert calls == [calls[0]] and result.ok
        return calls[0]
    assert not result.ok
    return slot.DISABLED if "disabled" in (result.error or "") else slot.REFUSED


@pytest.mark.parametrize(("allowed", "posture", "alive", "expected"), CASES)
def test_the_slot_and_the_shell_agree(monkeypatch, tmp_path, allowed, posture, alive, expected) -> None:
    box = slot.Sandbox(posture=lambda: posture, runner_alive=lambda: alive)
    assert box.rung(allowed=allowed) == expected
    assert box.rung(allowed=allowed) == expected  # the same inputs, the same outcome
    assert _run_shell(monkeypatch, tmp_path, allowed, posture, alive) == expected


def test_the_default_slot_reads_the_cage_the_shell_reads(monkeypatch) -> None:
    from thomas.tools import cage_shell

    monkeypatch.setattr(cage_shell, "posture", lambda *a, **k: "required")
    monkeypatch.setattr(cage_shell, "runner_alive", lambda *a, **k: False)
    assert slot.sandbox().rung() == slot.REFUSED
    monkeypatch.setattr(cage_shell, "runner_alive", lambda *a, **k: True)
    assert slot.sandbox().rung() == slot.CAGED


def test_a_missing_provider_refuses_and_never_runs_locally() -> None:
    kernel = Kernel()
    with pytest.raises(slot.SandboxMissing, match="refused"):
        slot.rung_for(kernel.root)
    with pytest.raises(slot.SandboxMissing):
        slot.rung_for(kernel.root, allowed=False)


def test_a_provider_that_fails_or_answers_oddly_refuses() -> None:
    class Broken:
        def rung(self, *, allowed: bool = True) -> str:
            raise OSError("heartbeat unreadable")

    class Odd:
        def rung(self, *, allowed: bool = True) -> str:
            return "sandboxed"

    for provider in (Broken(), Odd()):
        kernel = Kernel()
        kernel.root.set(SANDBOX, provider)
        with pytest.raises(slot.SandboxMissing):
            slot.rung_for(kernel.root)


def test_a_provider_of_the_wrong_shape_is_rejected() -> None:
    from thomas.core.kernel import SeamViolation

    kernel = Kernel()
    kernel.root.set(SANDBOX, object())
    with pytest.raises(SeamViolation):
        slot.rung_for(kernel.root)


def test_the_refusing_provider_never_answers_local() -> None:
    kernel = Kernel()
    kernel.root.set(SANDBOX, slot.RefusingSandbox())
    assert slot.rung_for(kernel.root) == slot.REFUSED
    assert slot.rung_for(kernel.root, allowed=False) == slot.DISABLED
