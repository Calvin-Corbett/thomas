"""The caged server writes its console to a log, including how it ended.

On 2026-09-25 and 26 the keepalive found the caged server gone six times; its task each time ended with result 0. The
server is started by a scheduled task that keeps no console, and ``thomas serve`` logs only to the console, so there
was no record of why: not the warnings, not a traceback, not the supervisor's own "[thomas] Stopped by user.". Every
Build run it was hosting was cut off each time. ``scripts/cage/caged_server.py`` now appends its console to
``<memory root>/logs/thomas.log.console`` and writes a line for how the server ended, and the log export serves it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from scripts.cage import caged_server

from thomas.server.routes.logs_export_routes import _log_files


@pytest.fixture
def console(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """``record_console`` for the test to call in its own body: pytest puts its capture back on
    ``sys.stdout`` between a fixture's setup and the test, which would undo the redirect."""
    monkeypatch.setattr(sys, "stdout", sys.stdout)  # restored after the test, whatever the code sets
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    return lambda: caged_server.record_console(tmp_path)


def _text(path: Path) -> str:
    sys.stdout.flush()
    return path.read_text(encoding="utf-8")


def test_the_console_goes_to_a_log_the_export_serves(console, tmp_path: Path) -> None:
    console = console()
    print("[thomas] Stopped by user.")
    print("a warning line", file=sys.stderr)
    assert console == tmp_path / "logs" / "thomas.log.console"
    text = _text(console)
    assert "[thomas] Stopped by user." in text and "a warning line" in text
    assert console in _log_files(tmp_path / "logs")  # GET /api/logs/export includes it


@pytest.mark.parametrize(
    ("raised", "said"),
    [
        (KeyboardInterrupt(), "stopped by a console Ctrl+C (KeyboardInterrupt)"),
        (SystemExit(0), "exited (SystemExit 0)"),
        (RuntimeError("boom"), "crashed: RuntimeError: boom"),
    ],
)
def test_how_the_server_ended_is_written_down(console, raised: BaseException, said: str) -> None:
    console = console()

    def serve() -> None:
        raise raised

    with pytest.raises(type(raised)):
        caged_server.run_recorded(serve)
    lines = [line for line in _text(console).splitlines() if line.startswith("[caged]")]
    assert lines[0].endswith("starting") and lines[-1].endswith(said)


def test_a_clean_return_is_written_down_too(console) -> None:
    console = console()
    caged_server.run_recorded(lambda: None)
    assert _text(console).splitlines()[-1].endswith("returned")


def test_main_puts_the_log_in_the_folder_the_export_reads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The first cut wrote under THOMAS_MEMORY_ROOT (``<data dir>/runtime/logs``); the export reads the folder of
    the THOMAS_LOG_FILE that ``thomas serve`` sets (``<data dir>/logs``), so the file was never served."""
    import os

    from scripts.cage import egress_proxy, search_broker

    import thomas.cli.main as cli_main
    from thomas.cli._commands_base import _prepare_runtime_data_environment

    monkeypatch.setattr(os, "environ", os.environ.copy())  # everything main and the CLI set is thrown away after
    for name in ("THOMAS_MEMORY_ROOT", "THOMAS_LOG_FILE", "THOMAS_PROFILE"):
        os.environ.pop(name, None)
    os.environ["THOMAS_DATA_DIR"] = str(tmp_path / "data")
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(sys, "argv", list(sys.argv))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(egress_proxy, "egress_env", lambda: {})
    monkeypatch.setattr(search_broker, "broker_env", lambda: {})
    monkeypatch.setattr(caged_server, "claude_env", lambda: {})
    # The real call would turn Ctrl+C off for this pytest process; its own test runs it in a separate console.
    ignored: list[bool] = []
    monkeypatch.setattr(caged_server, "ignore_console_ctrl_c", lambda: ignored.append(True) or True)
    served: list[Path] = []

    def serve() -> None:  # the server itself, stood in for: the CLI's own step that sets THOMAS_LOG_FILE
        _prepare_runtime_data_environment(data_dir_override=None, data_profile=None, reset_profile=False)
        served.append(Path(os.environ["THOMAS_LOG_FILE"]).parent)
        print("[thomas] serving")

    monkeypatch.setattr(cli_main, "main", serve)
    assert caged_server.main([]) == 0
    logs = served[0]
    text = _text(logs / "thomas.log.console")
    assert "[thomas] serving" in text and text.splitlines()[-1].endswith("returned")
    assert logs / "thomas.log.console" in _log_files(logs)
    assert ignored == [True] and "[caged] a console Ctrl+C is ignored: True" in text


def test_a_second_start_appends_and_a_large_file_is_kept_as_dot_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    first = caged_server.record_console(tmp_path)
    print("first run")
    sys.stdout.close()
    caged_server.record_console(tmp_path)
    print("second run")
    assert _text(first).splitlines()[-2:] == ["first run", "second run"]
    sys.stdout.close()

    monkeypatch.setattr(caged_server, "CONSOLE_LOG_MAX_BYTES", 5)
    caged_server.record_console(tmp_path)
    print("third run")
    assert (tmp_path / "logs" / "thomas.log.console.1").read_text(encoding="utf-8").startswith("first run")
    assert _text(first) == "third run\n"
    sys.stdout.close()
