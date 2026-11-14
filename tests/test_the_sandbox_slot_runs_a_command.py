"""The sandbox slot runs a command by its ladder, and only fakes are used: nothing here reaches the real cage."""

from __future__ import annotations

from thomas.core.kernel import SANDBOX, Kernel
from thomas.tools import sandbox_slot as slot
from thomas.tools.cage_shell import CagedResult


class _Calls:
    def __init__(self, cage=None, local=None, cage_error=None) -> None:
        self.cage_calls: list[tuple] = []
        self.local_calls: list[tuple] = []
        self._cage = cage or CagedResult("ok", 0, "caged out", "thomas-agent")
        self._local = local or (0, "local out", "")
        self._cage_error = cage_error

    def cage(self, command, *, cwd, timeout_s):
        self.cage_calls.append((command, cwd, timeout_s))
        if self._cage_error:
            raise self._cage_error
        return self._cage

    def local(self, command, *, cwd, timeout):
        self.local_calls.append((command, cwd, timeout))
        return self._local


def _sandbox(posture: str, alive: bool, calls: _Calls) -> slot.Sandbox:
    return slot.Sandbox(
        posture=lambda: posture,
        runner_alive=lambda: alive,
        cage_run=calls.cage,
        local_run=calls.local,
    )


def test_caged_runs_the_cage_and_not_the_local_run() -> None:
    calls = _Calls()
    result = _sandbox("auto", True, calls).run("echo hi", cwd="w", timeout_s=5, allowed=True)
    assert result == slot.SandboxResult("ok", 0, "caged out", "thomas-agent")
    assert calls.cage_calls == [("echo hi", "w", 5)]
    assert calls.local_calls == []


def test_local_runs_the_local_run_and_merges_stdout_then_stderr() -> None:
    calls = _Calls(local=(3, "out|", "err"))
    result = _sandbox("off", False, calls).run("x", cwd="w", timeout_s=7, allowed=True)
    assert result == slot.SandboxResult("ok", 3, "out|err", "")
    assert calls.local_calls == [("x", "w", 7)]
    assert calls.cage_calls == []


def test_required_with_no_runner_refuses_and_runs_nothing() -> None:
    calls = _Calls()
    result = _sandbox("required", False, calls).run("x", cwd="w", timeout_s=1, allowed=True)
    assert result.outcome == "refused"
    assert result.returncode is None
    assert "nothing ran" in result.output
    assert calls.cage_calls == [] and calls.local_calls == []


def test_auto_with_no_runner_runs_local() -> None:
    calls = _Calls()
    result = _sandbox("auto", False, calls).run("x", cwd="w", timeout_s=1, allowed=True)
    assert result.outcome == "ok"
    assert calls.local_calls and not calls.cage_calls


def test_a_cage_exception_is_an_error_and_runs_nothing_locally() -> None:
    calls = _Calls(cage_error=RuntimeError("boom"))
    result = _sandbox("auto", True, calls).run("x", cwd="w", timeout_s=1, allowed=True)
    assert result.outcome == "error"
    assert result.returncode is None
    assert calls.local_calls == []


def test_a_timeout_maps_to_timeout_on_both_rungs() -> None:
    caged = _Calls(cage=CagedResult("timeout", -1, "slow"))
    assert _sandbox("required", True, caged).run("x", cwd="w", timeout_s=1, allowed=True).outcome == "timeout"
    local = _Calls(local=(None, "partial", ""))
    result = _sandbox("off", False, local).run("x", cwd="w", timeout_s=1, allowed=True)
    assert (result.outcome, result.returncode, result.output) == ("timeout", None, "partial")


def test_a_cage_with_no_runner_reply_is_refused_not_run_locally() -> None:
    calls = _Calls(cage=CagedResult("no_runner", -1, "channel not writable"))
    result = _sandbox("auto", True, calls).run("x", cwd="w", timeout_s=1, allowed=True)
    assert result.outcome == "refused"
    assert calls.local_calls == []


def test_a_local_start_failure_is_an_error() -> None:
    def broken(command, *, cwd, timeout):
        raise OSError("no such dir")

    box = slot.Sandbox(posture=lambda: "off", local_run=broken)
    assert box.run("x", cwd="nope", timeout_s=1, allowed=True).outcome == "error"


def test_disabled_rung_refuses() -> None:
    class Closed(slot.Sandbox):
        def rung(self, *, allowed: bool = True) -> str:
            return slot.DISABLED

    assert Closed().run("x", cwd="w", timeout_s=1, allowed=True).outcome == "refused"


def test_the_helper_uses_the_context_provider() -> None:
    calls = _Calls()
    kernel = Kernel()
    kernel.root.set(SANDBOX, _sandbox("auto", True, calls))
    assert slot.run(kernel.root, "x", cwd="w", timeout_s=2, allowed=True).outcome == "ok"
    assert calls.cage_calls == [("x", "w", 2)]


def test_the_helper_refuses_when_no_sandbox_is_provided() -> None:
    result = slot.run(Kernel().root, "x", cwd="w", timeout_s=1, allowed=True)
    assert result.outcome == "refused"


def test_the_helper_refuses_with_the_refusing_provider() -> None:
    kernel = Kernel()
    kernel.root.set(SANDBOX, slot.RefusingSandbox())
    assert slot.run(kernel.root, "x", cwd="w", timeout_s=1, allowed=True).outcome == "refused"


def test_the_helper_turns_a_provider_exception_into_an_error() -> None:
    class Bad:
        def rung(self, *, allowed: bool = True) -> str:
            return slot.LOCAL

        def run(self, command, *, cwd, timeout_s, allowed):
            raise RuntimeError("x")

    kernel = Kernel()
    kernel.root.set(SANDBOX, Bad())
    assert slot.run(kernel.root, "x", cwd="w", timeout_s=1, allowed=True).outcome == "error"


def test_a_provider_without_run_is_refused() -> None:
    class RungOnly:
        def rung(self, *, allowed: bool = True) -> str:
            return slot.LOCAL

    kernel = Kernel()
    kernel.root.set(SANDBOX, RungOnly())
    assert slot.run(kernel.root, "x", cwd="w", timeout_s=1, allowed=True).outcome == "refused"


def test_strict_lets_a_cage_error_through() -> None:
    import pytest

    calls = _Calls(cage_error=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        _sandbox("auto", True, calls).run("x", cwd="w", timeout_s=1, allowed=True, strict=True)
    assert calls.local_calls == []


def test_allowed_is_required_so_forgetting_it_is_a_type_error() -> None:
    import pytest

    box = _sandbox("off", False, _Calls())
    with pytest.raises(TypeError):
        box.run("x", cwd="w", timeout_s=1)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        slot.RefusingSandbox().run("x", cwd="w", timeout_s=1)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        slot.run(None, "x", cwd="w", timeout_s=1)  # type: ignore[call-arg]


def test_not_allowed_runs_nothing_on_any_posture() -> None:
    for posture, alive in (("off", False), ("auto", True), ("auto", False), ("required", True)):
        calls = _Calls()
        result = _sandbox(posture, alive, calls).run("x", cwd="w", timeout_s=1, allowed=False)
        assert result.outcome == "refused" and result.returncode is None
        assert "switched off" in result.output and "nothing ran" in result.output
        assert calls.cage_calls == [] and calls.local_calls == []


def test_not_allowed_wins_over_a_rung_that_was_already_decided() -> None:
    calls = _Calls()
    result = _sandbox("off", False, calls).run("x", cwd="w", timeout_s=1, allowed=False, rung=slot.LOCAL)
    assert result.outcome == "refused"
    assert calls.cage_calls == [] and calls.local_calls == []


def test_the_helper_does_not_even_ask_the_provider_when_not_allowed() -> None:
    asked: list[str] = []

    class Spy:
        def rung(self, *, allowed: bool = True) -> str:
            return slot.LOCAL

        def run(self, command, *, cwd, timeout_s, allowed):
            asked.append(command)
            return slot.SandboxResult("ok", 0, "")

    kernel = Kernel()
    kernel.root.set(SANDBOX, Spy())
    result = slot.run(kernel.root, "x", cwd="w", timeout_s=1, allowed=False)
    assert result.outcome == "refused" and asked == []
    assert slot.run(None, "x", cwd="w", timeout_s=1, allowed=False).outcome == "refused"


def test_the_helper_passes_allowed_through_to_the_provider() -> None:
    seen: list[bool] = []

    class Spy:
        def rung(self, *, allowed: bool = True) -> str:
            return slot.LOCAL

        def run(self, command, *, cwd, timeout_s, allowed):
            seen.append(allowed)
            return slot.SandboxResult("ok", 0, "")

    kernel = Kernel()
    kernel.root.set(SANDBOX, Spy())
    slot.run(kernel.root, "x", cwd="w", timeout_s=1, allowed=True)
    assert seen == [True]


def test_a_rung_that_was_decided_is_used_without_reading_the_ladder_again() -> None:
    reads: list[int] = []
    calls = _Calls()

    def posture() -> str:
        reads.append(1)
        return "required"

    box = slot.Sandbox(posture=posture, runner_alive=lambda: False, cage_run=calls.cage, local_run=calls.local)
    assert box.run("x", cwd="w", timeout_s=1, allowed=True, rung=slot.LOCAL).outcome == "ok"
    assert reads == [] and calls.local_calls and not calls.cage_calls
    assert box.run("x", cwd="w", timeout_s=1, allowed=True, rung=slot.REFUSED).outcome == "refused"


def test_a_rung_that_is_not_one_of_the_four_runs_nothing() -> None:
    import pytest

    calls = _Calls()
    result = _sandbox("off", False, calls).run("x", cwd="w", timeout_s=1, allowed=True, rung="bogus")
    assert result.outcome == "error" and "nothing ran" in result.output
    assert calls.cage_calls == [] and calls.local_calls == []
    with pytest.raises(slot.SandboxMissing):
        _sandbox("off", False, calls).run("x", cwd="w", timeout_s=1, allowed=True, rung="bogus", strict=True)
