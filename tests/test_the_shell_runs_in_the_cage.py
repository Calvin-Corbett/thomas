"""A shell command runs as the caged account, or it does not run at all.

Owner direction, 2026-09-22: "The thing that stops Thomas from breaking his
rules is not words. It's hard gates that have passwords." Protected files had
the card and the PIN; ``shell.exec`` had nothing. Observed the same day: a run
put a protected file back with a shell command, around the card entirely.

The fix is the cage, an OS privilege boundary. The server hands the command to
a runner started as ``thomas-agent``, which can read and execute the repo and
cannot write Thomas's own code. These tests pin the channel and, above all,
that failing to reach the cage never quietly falls back to running the command
with the owner's own account.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "cage"))

import shell_runner  # noqa: E402

from thomas.tools import cage_shell  # noqa: E402
from thomas.tools.shell import ShellTool  # noqa: E402

# Read before any fixture patches it: the real value the server will use.
_REAL_PIN_ROOT = cage_shell.DEFAULT_PIN_ROOT
_REAL_CAGE_ROOT = cage_shell.DEFAULT_CAGE_ROOT


@pytest.fixture(autouse=True)
def _no_env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.delenv(cage_shell.POSTURE_ENV, raising=False)
    monkeypatch.delenv(cage_shell.CAGE_ROOT_ENV, raising=False)
    # A pin is honoured from the default root as well as the effective one, so
    # once this machine has a real one every test below would otherwise read
    # the posture off the live cage instead of its own fixture.
    monkeypatch.setattr(cage_shell, "DEFAULT_CAGE_ROOT", tmp_path_factory.mktemp("no-default-cage"))
    monkeypatch.setattr(cage_shell, "DEFAULT_PIN_ROOT", tmp_path_factory.mktemp("no-default-pins"))
    # A test may replace the cached reader; clear only when it is still cached.
    getattr(cage_shell._configured_posture, "cache_clear", lambda: None)()
    yield
    getattr(cage_shell._configured_posture, "cache_clear", lambda: None)()


def _beat(cage: Path, *, seconds_ago: float = 0.0) -> None:
    beat = cage / "shell" / shell_runner.HEARTBEAT_NAME
    beat.parent.mkdir(parents=True, exist_ok=True)
    beat.write_text("{}", encoding="utf-8")
    if seconds_ago:
        stamp = time.time() - seconds_ago
        os.utime(beat, (stamp, stamp))


def test_the_command_runs_and_comes_back(tmp_path: Path) -> None:
    cage = tmp_path / "cage"
    inbox, outbox = shell_runner.channel_dirs(cage)
    inbox.mkdir(parents=True)
    outbox.mkdir(parents=True)

    def serve_soon() -> None:
        for _ in range(200):
            if shell_runner.serve_once(inbox, outbox):
                return
            time.sleep(0.01)

    server = threading.Thread(target=serve_soon)
    server.start()
    result = cage_shell.run_caged("echo caged-hello", cwd=str(tmp_path), timeout_s=30, root=cage)
    server.join(10)

    assert result.outcome == "ok" and result.returncode == 0
    assert "caged-hello" in result.output


def test_a_command_that_never_gets_an_answer_is_a_timeout_not_a_local_run(tmp_path: Path) -> None:
    """Nobody is serving. The command must not be run here instead."""
    marker = tmp_path / "escaped.txt"
    command = f"echo escaped > {marker}"
    result = cage_shell.run_caged(command, cwd=str(tmp_path), timeout_s=1, root=tmp_path / "cage")
    assert result.outcome == "timeout"
    assert not marker.exists(), "the client ran the command locally; the cage is not a wall"


def test_the_runner_says_who_it_ran_as(tmp_path: Path) -> None:
    reply = shell_runner.run_command({"id": "x", "command": "echo hi", "cwd": str(tmp_path), "timeout_s": 30})
    assert reply["outcome"] == "ok"
    assert "ran_as" in reply, "the answer names the account, so a caged run is checkable"


def test_a_missing_directory_is_refused_not_run(tmp_path: Path) -> None:
    reply = shell_runner.run_command({"id": "x", "command": "echo hi", "cwd": str(tmp_path / "nope"), "timeout_s": 5})
    assert reply["outcome"] == "invalid"


def test_a_half_written_request_never_stalls_the_runner(tmp_path: Path) -> None:
    inbox, outbox = shell_runner.channel_dirs(tmp_path)
    inbox.mkdir(parents=True)
    outbox.mkdir(parents=True)
    (inbox / "broken.json").write_text("{not json", encoding="utf-8")
    (inbox / "good.json").write_text(
        json.dumps({"id": "good", "command": "echo fine", "cwd": str(tmp_path), "timeout_s": 10}), encoding="utf-8"
    )
    shell_runner.serve_once(inbox, outbox)
    assert not (inbox / "broken.json").exists()
    assert json.loads((outbox / "good.json").read_text(encoding="utf-8"))["outcome"] == "ok"


def test_a_stale_heartbeat_means_no_runner(tmp_path: Path) -> None:
    _beat(tmp_path, seconds_ago=cage_shell.HEARTBEAT_STALE_S + 5)
    assert cage_shell.runner_alive(tmp_path) is False
    _beat(tmp_path)
    assert cage_shell.runner_alive(tmp_path) is True


def test_required_refuses_when_the_cage_is_not_there(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The wall: no runner, no shell -- never the owner's own account instead."""
    monkeypatch.setenv(cage_shell.POSTURE_ENV, "required")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(tmp_path / "cage"))
    marker = tmp_path / "ran-locally.txt"
    tool = ShellTool(tmp_path)

    result = asyncio.run(tool.execute({"command": f"echo escaped > {marker}"}))

    assert not result.ok
    assert "did not run" in str(result.error)
    assert not marker.exists(), "required posture ran the command locally"


def test_off_runs_locally_as_before(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cage_shell.POSTURE_ENV, "off")
    result = asyncio.run(ShellTool(tmp_path).execute({"command": "echo local-ok"}))
    assert result.ok and "local-ok" in str(result.data)


def test_auto_falls_back_and_says_nothing_clever_about_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """auto is honest: with no runner it runs locally, which is why required exists."""
    monkeypatch.setenv(cage_shell.POSTURE_ENV, "auto")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(tmp_path / "cage"))
    result = asyncio.run(ShellTool(tmp_path).execute({"command": "echo fallback"}))
    assert result.ok and "fallback" in str(result.data)


def test_the_posture_comes_from_config_when_the_environment_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cage_shell, "_configured_posture", lambda: "required")
    assert cage_shell.posture() == "required"
    monkeypatch.setenv(cage_shell.POSTURE_ENV, "off")
    assert cage_shell.posture() == "off", "the environment overrides the config"


def test_nothing_in_the_client_executes_a_command() -> None:
    """The client may only hand the command over. If it could run one, a
    failure to reach the cage could silently become an uncaged run."""
    import inspect

    src = inspect.getsource(cage_shell)
    for forbidden in ("subprocess", "os.system", "popen", "create_subprocess"):
        assert forbidden not in src.lower(), f"cage_shell reaches for {forbidden}"


def _pin(root: Path, value: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / cage_shell.POSTURE_NAME).write_text(value, encoding="utf-8")
    return root


def test_a_pinned_posture_is_not_loosened_by_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The point of the pin. thomas.toml is a repo file the server's own
    account can rewrite; the pin lives where only an administrator can."""
    cage = _pin(tmp_path / "cage", "required")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(cage))
    monkeypatch.setenv(cage_shell.POSTURE_ENV, "off")
    assert cage_shell.posture() == "required"


def test_a_pinned_posture_is_not_loosened_by_the_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cage = _pin(tmp_path / "cage", "required")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(cage))
    monkeypatch.setattr(cage_shell, "_configured_posture", lambda: "off")
    assert cage_shell.posture() == "required"


def test_the_environment_may_still_tighten_a_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A floor, not a fixed value: asking for more cage than was pinned is fine."""
    cage = _pin(tmp_path / "cage", "auto")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(cage))
    monkeypatch.setenv(cage_shell.POSTURE_ENV, "required")
    assert cage_shell.posture() == "required"


def test_pointing_the_cage_root_elsewhere_does_not_escape_the_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THOMAS_CAGE_ROOT is an environment variable, so a pin that only counted
    at the root it names could be retired by looking somewhere empty."""
    monkeypatch.setattr(cage_shell, "DEFAULT_CAGE_ROOT", _pin(tmp_path / "real", "required"))
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(tmp_path / "decoy"))
    monkeypatch.setenv(cage_shell.POSTURE_ENV, "off")
    assert cage_shell.posture() == "required"


def test_a_pin_nobody_can_read_is_the_strictest_posture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only an administrator can put that file there, so its presence is the
    decision. A typo or a truncated write must not be the difference between a
    wall and nothing -- loud and wrong beats quietly absent."""
    cage = _pin(tmp_path / "cage", "fortress-mode-9000")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(cage))
    monkeypatch.setenv(cage_shell.POSTURE_ENV, "off")
    assert cage_shell.pinned_posture() == "required"
    assert cage_shell.posture() == "required"


def test_undecodable_bytes_are_a_pin_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """read_text raises UnicodeDecodeError, not OSError. Caught, it is still a
    pin; uncaught, it would crash every shell call in the process."""
    cage = tmp_path / "cage"
    cage.mkdir(parents=True)
    (cage / cage_shell.POSTURE_NAME).write_bytes(bytes([0xFF, 0xFE, 0x00]) + b"rubbish")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(cage))
    assert cage_shell.pinned_posture() == "required"


def test_no_pin_at_all_leaves_the_posture_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The absence of the file is the absence of a pin -- the strict reading
    applies to a pin that exists and cannot be understood, not to no pin."""
    cage = _pin(tmp_path / "cage", "auto")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(cage))
    (cage / cage_shell.POSTURE_NAME).unlink()
    assert cage_shell.pinned_posture() == ""
    monkeypatch.setenv(cage_shell.POSTURE_ENV, "off")
    assert cage_shell.posture() == "off"


def test_the_pin_is_read_fresh_every_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An administrator changes this under a running server; a cached answer
    would be a posture nobody chose, in the other direction."""
    cage = _pin(tmp_path / "cage", "auto")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(cage))
    assert cage_shell.posture() == "auto"
    _pin(cage, "required")
    assert cage_shell.posture() == "required"


def test_a_byte_order_mark_does_not_retire_the_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A BOM is not whitespace. Read as plain utf-8 it survives strip(), the
    value stops matching, and the wall quietly becomes a suggestion."""
    cage = tmp_path / "cage"
    cage.mkdir(parents=True)
    (cage / cage_shell.POSTURE_NAME).write_text("required", encoding="utf-8-sig")
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(cage))
    monkeypatch.setenv(cage_shell.POSTURE_ENV, "off")
    assert cage_shell.posture() == "required"


def test_a_caged_command_can_find_python() -> None:
    """The agent account has no Python on its PATH. The first real caged
    command answered "'python' is not recognized", which would make the cage a
    place no work can be done in -- and a cage like that gets switched off."""
    env = shell_runner.child_env()
    first = env["PATH"].split(os.pathsep)[0]
    assert Path(first) == Path(sys.executable).resolve().parent
    assert env["PYTHONDONTWRITEBYTECODE"] == "1", "most of the repo is read-only to this account"


def test_the_interpreter_comes_from_this_process_not_a_setting() -> None:
    """The runner is started with the venv's pythonw, so its own executable is
    the right answer by construction. A configured path could drift from the
    interpreter Thomas actually uses; this cannot."""
    import inspect

    src = inspect.getsource(shell_runner.child_env)
    assert "sys.executable" in src
    for guess in (".venv", "Python312", "PYTHONHOME"):
        assert guess not in src, f"child_env hard-codes {guess} instead of asking the process"


def test_only_one_runner_can_hold_the_channel(tmp_path: Path) -> None:
    """Three runners were found sharing one channel after repeated restarts.
    Two of them can read the same request before either deletes it, and the
    command runs twice -- for anything that changes state, that is a bug."""
    cage = tmp_path / "cage"
    first = shell_runner.take_single_instance_lock(cage)
    assert first is not None, "the first runner must get the channel"
    try:
        assert shell_runner.take_single_instance_lock(cage) is None, "a second runner took the same channel"
    finally:
        first.close()
    second = shell_runner.take_single_instance_lock(cage)
    assert second is not None, "the lock did not release when the holder let go"
    second.close()


def test_a_second_runner_exits_quietly_rather_than_failing(tmp_path: Path) -> None:
    """Exit 0: the scheduled task restarts a FAILED run, so a loser that
    reported failure would restart-loop against the runner doing the work."""
    cage = tmp_path / "cage"
    held = shell_runner.take_single_instance_lock(cage)
    assert held is not None
    try:
        assert shell_runner.serve(cage, once=True) == 0
    finally:
        held.close()


def test_the_lock_dies_with_the_process_not_as_a_stale_file(tmp_path: Path) -> None:
    """A pid file outlives a kill -9 and has to be second-guessed; a byte-range
    lock is released by the OS, so there is nothing stale to misread."""
    import inspect

    src = inspect.getsource(shell_runner.take_single_instance_lock)
    assert "msvcrt" in src or "fcntl" in src
    assert "pid" not in src.split('"""')[2].lower() or "os.getpid" in src


def test_tools_that_cache_into_the_repo_get_somewhere_to_write() -> None:
    """ruff died in the live cage with "Failed to create temporary file ...
    .ruff_cache ... Access is denied" while pytest passed, because pytest
    degrades when its cache is unwritable and ruff does not. The repo root is
    read-only by design, so the caches move rather than the boundary."""
    env = shell_runner.child_env()
    for name in ("RUFF_CACHE_DIR", "MYPY_CACHE_DIR"):
        target = Path(env[name])
        assert target.is_dir(), f"{name} points at {target}, which does not exist"
        probe = target / "writable.probe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        assert Path(r"C:\Users\corbe\Thomas") not in target.parents, f"{name} still writes into the repo"


@pytest.mark.skipif(os.name != "nt", reason="the quoting bug is list2cmdline's, and only on Windows")
def test_a_command_with_quotes_survives_the_runner(tmp_path: Path) -> None:
    """An argv list is joined by subprocess.list2cmdline, which escapes inner
    quotes as backslash-quote -- an escape cmd.exe does not understand. Before
    this, `python -c "print(7*6)"` answered "is not recognized" instead of 42,
    so anything with a quoted argument was silently broken."""
    reply = shell_runner.run_command(
        {"id": "q", "command": 'python -c "print(7*6)"', "cwd": str(tmp_path), "timeout_s": 60}
    )
    assert reply["outcome"] == "ok", reply
    assert reply["returncode"] == 0, reply["output"]
    assert "42" in reply["output"], reply["output"]


@pytest.mark.skipif(os.name != "nt", reason="the quoting bug is list2cmdline's, and only on Windows")
def test_quotes_are_consumed_by_the_shell_not_passed_through(tmp_path: Path) -> None:
    """The quotes must be eaten by the shell, as they are when typed. The list
    form left them in the output, so `--format="%s"` printed its own quotes."""
    reply = shell_runner.run_command(
        {"id": "q2", "command": "python -c \"print('plain')\"", "cwd": str(tmp_path), "timeout_s": 60}
    )
    assert reply["outcome"] == "ok"
    assert reply["output"].strip() == "plain", reply["output"]


def test_the_caged_and_uncaged_shells_parse_a_command_the_same_way() -> None:
    """If the cage changed what a command means, every command would need
    testing twice. Both paths hand Windows the whole line and POSIX an argv."""
    import inspect

    from thomas.tools import shell as shell_tool

    def code_only(src: str) -> str:
        # Comments explain the old form, so they would fail a search for it.
        kept = [ln for ln in src.splitlines() if not ln.strip().startswith(chr(35))]
        return chr(10).join(kept)

    caged = code_only(inspect.getsource(shell_runner.run_command))
    uncaged = code_only(inspect.getsource(shell_tool.ShellTool.execute))
    for src, name in ((caged, "the runner"), (uncaged, "the shell tool")):
        assert '"/c"' not in src and "'/c'" not in src, f"{name} still builds an argv list for cmd"
        assert '["bash", "-c", command]' in src, f"{name} changed how POSIX is invoked"


def test_the_heartbeat_keeps_beating_while_a_command_runs(tmp_path: Path) -> None:
    """The beat used to share the serve loop, so it paused for as long as a
    command took. The stale window is 20s: one 61-second test run made a
    healthy runner read as gone, and with the posture pinned that turns every
    other shell call into a refusal."""
    beat = tmp_path / "shell" / shell_runner.HEARTBEAT_NAME
    beat.parent.mkdir(parents=True)
    stop = threading.Event()
    worker = threading.Thread(target=shell_runner._beat_until, args=(beat, stop), daemon=True)
    worker.start()
    try:
        # Stand in for a long command: the loop this runs on is not the beat's.
        time.sleep(shell_runner.HEARTBEAT_EVERY_S * 1.5)
        assert beat.exists(), "no beat while something else was busy"
        first = beat.stat().st_mtime
        time.sleep(shell_runner.HEARTBEAT_EVERY_S * 1.2)
        assert beat.stat().st_mtime > first, "the beat stalled"
    finally:
        stop.set()
        worker.join(timeout=5)


def test_a_failing_request_does_not_take_the_runner_down(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Anything raising out of serve_once used to end the process. The task
    does not restart a clean exit, so the only symptom was a shell refusing
    everything with nothing anywhere saying why."""
    calls = {"n": 0}

    def explode(_inbox: Path, _outbox: Path) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("the inbox blinked")
        raise KeyboardInterrupt  # end the loop so the test finishes

    monkeypatch.setattr(shell_runner, "serve_once", explode)
    monkeypatch.setattr(shell_runner, "POLL_EVERY_S", 0.01)
    with pytest.raises(KeyboardInterrupt):
        shell_runner.serve(tmp_path)
    assert calls["n"] == 2, "the runner stopped serving after one failed request"
    logged = (tmp_path / "shell" / shell_runner.LOG_NAME).read_text(encoding="utf-8")
    assert "the inbox blinked" in logged, "the failure was swallowed with no trace"
    assert "runner stopped" in logged, "the runner did not record its own exit"


def test_the_runner_records_that_it_started(tmp_path: Path) -> None:
    """A service that vanishes without a word is the worst thing to debug, and
    this one did exactly that three times before it kept a log."""
    shell_runner.log(tmp_path, "hello from the cage")
    logged = (tmp_path / "shell" / shell_runner.LOG_NAME).read_text(encoding="utf-8")
    assert "hello from the cage" in logged
    assert f"pid={os.getpid()}" in logged, "a log line that does not say who wrote it cannot be correlated"


def test_the_pin_root_is_honoured_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins live where an unelevated process cannot remove them. A pin there
    holds even when the cage root, which the owner's account can empty, has
    nothing in it at all."""
    monkeypatch.setattr(cage_shell, "DEFAULT_PIN_ROOT", _pin(tmp_path / "pins", "required"))
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(tmp_path / "empty-cage"))
    monkeypatch.setenv(cage_shell.POSTURE_ENV, "off")
    assert cage_shell.posture() == "required"


def test_an_old_pin_can_only_tighten_the_pin_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The legacy location stays readable during the move, and strictest wins,
    so whatever is left there can never loosen what the pin root says."""
    monkeypatch.setattr(cage_shell, "DEFAULT_PIN_ROOT", _pin(tmp_path / "pins", "required"))
    monkeypatch.setattr(cage_shell, "DEFAULT_CAGE_ROOT", _pin(tmp_path / "legacy", "off"))
    assert cage_shell.pinned_posture() == "required"


def test_pins_do_not_live_where_the_owner_can_empty_them() -> None:
    """Measured 2026-09-22: an unelevated process deleted an Administrators-only
    file in ThomasCage, because the owner holds delete-child on that folder. The
    real pin root must be a different folder, directly under ProgramData."""
    from pathlib import PureWindowsPath

    pin_root = PureWindowsPath(str(_REAL_PIN_ROOT))
    assert pin_root != PureWindowsPath(str(_REAL_CAGE_ROOT)), "pins share the folder the owner can empty"
    assert pin_root.parent == PureWindowsPath(r"C:\ProgramData"), pin_root
