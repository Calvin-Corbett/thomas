"""The cage's one way out stays up, and the promoter says why it stopped.

From 2026-09-23 21:51 to 2026-09-24 11:10 the promoter service -- and the egress
proxy inside it, the caged Thomas's only route to its models -- was gone, with no
line in its log. scripts/cage/cage_keepalive.py, run every 15 minutes by its own
ThomasCageKeepalive task, starts what is down and checks that it came up; the
promoter writes a line when it exits, logs the error that stopped it, and keeps
its search broker on a thread of its own, started again whenever it stops. Task
Scheduler and the ports are stubbed here; git is real, in a throwaway repository.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import scripts.cage
from scripts.cage import cage_keepalive as keepalive
from scripts.cage import promoter_service

REPO = Path(__file__).resolve().parents[1]
PORT_OF = {"ThomasSelfChangePromoter": 8897, "ThomasCagedServer": 8898}


class Machine:
    """Task Scheduler and the two ports: a task that is run brings its port up, unless told otherwise."""

    def __init__(self, up: set[int] = frozenset(), *, code: int = 0, states: dict | None = None, starts: bool = True):
        self.up, self.code, self.states, self.starts = set(up), code, dict(states or {}), starts
        self.ran: list[str] = []
        self.ended: list[str] = []
        self.last_run = "10/28/2026 1:00:00 PM"
        self.now = 0.0

    def probe(self, port: int) -> bool:
        return port in self.up

    def details(self, name: str) -> keepalive.TaskReport:
        return keepalive.TaskReport(self.state(name) or "Unknown", self.last_run, "0")

    def end(self, name: str) -> tuple[int, str]:
        self.ended.append(name)
        return 0, "SUCCESS: ended"

    def run(self, name: str) -> tuple[int, str]:
        self.ran.append(name)
        if self.code == 0 and self.starts:
            self.up.add(PORT_OF[name])
        return self.code, "SUCCESS: Attempted to run the scheduled task."

    def state(self, name: str) -> str | None:
        return self.states.get(name, "Ready")

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _pass(machine: Machine, repo: Path, memory: Path | None = None) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = keepalive.keep_alive(
        repo=repo,
        probe=machine.probe,
        run=machine.run,
        state=machine.state,
        details=machine.details,
        end=machine.end,
        say=lines.append,
        sleep=machine.sleep,
        clock=lambda: machine.now,
        off_switch=repo / "caged_server.off",
        memory=memory,
    )
    return code, lines


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A committed tree shaped like this one: server code, the cage's scripts, and a forge script."""
    for rel in (
        "thomas/core/config.py",
        "scripts/cage/caged_server.py",
        "scripts/breakglass_auth.py",
        "scripts/forge/gates/gate.py",
        "thomas/a.js",
    ):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "config", "commit.gpgsign", "false")  # your global git config signs commits
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


def test_a_dead_proxy_port_starts_the_promoter_and_sees_it_listen(checkout: Path) -> None:
    machine = Machine({8898})

    assert _pass(machine, checkout) == (
        0,
        ["proxy: nothing listens on 127.0.0.1:8897; started ThomasSelfChangePromoter (port now listening)"],
    )
    assert machine.ran == ["ThomasSelfChangePromoter"]


def test_a_dead_server_port_starts_the_server_when_the_tree_is_clean(checkout: Path) -> None:
    machine = Machine({8897})

    code, lines = _pass(machine, checkout)
    assert code == 0 and len(lines) == 1
    assert lines[0].startswith(
        "server: nothing listens on 127.0.0.1:8898; started ThomasCagedServer (port now listening)"
    )
    assert "Task Scheduler:" in lines[0]


def test_a_start_that_never_listens_is_not_called_a_start(checkout: Path) -> None:
    machine = Machine({8897}, starts=False)

    code, lines = _pass(machine, checkout)

    assert code == 1 and machine.ran == ["ThomasCagedServer"] and machine.now >= 30
    assert len(lines) == 1
    assert lines[0].startswith(
        "server: nothing listens on 127.0.0.1:8898; asked Task Scheduler to run ThomasCagedServer;"
        " nothing listens on 8898 after 30 s"
    )
    assert "status='Ready'" in lines[0]
    assert "last run time='10/28/2026 1:00:00 PM'" in lines[0]
    assert "last result='0'" in lines[0]


@pytest.mark.parametrize("next_status", ["Ready", "Running"])
def test_a_noop_run_is_ended_then_run_on_the_next_pass(checkout: Path, next_status: str) -> None:
    machine = Machine({8897}, starts=False)
    memory = checkout / "keepalive.state.json"
    events = []
    original_run, original_end = machine.run, machine.end

    def run(name):
        events.append("run")
        return original_run(name)

    def end(name):
        events.append("end")
        return original_end(name)

    machine.run, machine.end = run, end
    assert _pass(machine, checkout, memory)[0] == 1
    assert events == ["run"]
    machine.states["ThomasCagedServer"] = next_status
    machine.starts = True

    code, lines = _pass(machine, checkout, memory)

    assert code == 0
    assert events == ["run", "end", "run"]
    assert machine.ended == ["ThomasCagedServer"]
    assert "Last Run Time unchanged" in lines[0]
    assert f"status='{next_status}'" in lines[0]
    assert "last run time='10/28/2026 1:00:00 PM'" in lines[0]
    assert "last result='0'" in lines[0]
    assert _pass(machine, checkout, memory) == (0, [])
    assert events == ["run", "end", "run"]


def test_verbose_scheduler_report_preserves_csv_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def schtasks(*args):
        calls.append(args)
        return 0, '"HOST","ThomasCagedServer","N/A","Running","Interactive only","October 29, 2026 00:07:00","267009"'

    monkeypatch.setattr(keepalive, "_schtasks", schtasks)
    report = keepalive.task_report("ThomasCagedServer")
    assert report == keepalive.TaskReport("Running", "October 29, 2026 00:07:00", "267009")
    assert calls == [("/Query", "/TN", "ThomasCagedServer", "/V", "/FO", "CSV", "/NH")]
    monkeypatch.setattr(keepalive, "_schtasks", lambda *args: (1, "ERROR"))
    assert keepalive.task_report("ThomasCagedServer") is None


def test_an_end_failure_does_not_issue_another_run(checkout: Path) -> None:
    machine = Machine({8897}, starts=False)
    memory = checkout / "keepalive.state.json"
    assert _pass(machine, checkout, memory)[0] == 1
    machine.end = lambda name: (1, "Access denied")
    code, lines = _pass(machine, checkout, memory)
    assert code == 1 and machine.ran == ["ThomasCagedServer"]
    assert "/End exit 1: Access denied" in lines[0]


def test_a_server_that_started_but_is_slow_to_listen_is_never_ended(checkout: Path) -> None:
    machine = Machine({8897}, starts=False)
    memory = checkout / "keepalive.state.json"
    assert _pass(machine, checkout, memory)[0] == 1
    machine.states["ThomasCagedServer"] = "Running"
    machine.last_run = "10/29/2026 12:07:00 AM"

    code, lines = _pass(machine, checkout, memory)

    assert code == 1 and "Last Run Time advanced" in lines[0]
    assert _pass(machine, checkout, memory)[0] == 1
    assert machine.ended == []
    assert machine.ran == ["ThomasCagedServer"]
    machine.up.add(8898)
    assert _pass(machine, checkout, memory) == (0, [])
    assert machine.ended == []


@pytest.mark.parametrize(("task", "up"), [("ThomasSelfChangePromoter", {8898}), ("ThomasCagedServer", {8897})])
def test_a_task_still_running_with_a_dead_port_is_reported_not_ended(checkout: Path, task: str, up: set[int]) -> None:
    machine = Machine(up, states={task: "Running"})

    code, lines = _pass(machine, checkout)

    assert (code, machine.ran) == (1, [])
    assert len(lines) == 1 and f"still shows {task} running" in lines[0] and "nothing was ended" in lines[0]


@pytest.mark.parametrize("rel", ["thomas/core/config.py", "scripts/cage/caged_server.py", "scripts/breakglass_auth.py"])
@pytest.mark.parametrize("staged", [False, True])
def test_a_server_file_that_cannot_load_keeps_the_server_down(checkout: Path, rel: str, staged: bool) -> None:
    (checkout / rel).write_text("def half_edited(:\n", encoding="utf-8")
    if staged:
        _git(checkout, "add", rel)
    machine = Machine({8897})

    code, lines = _pass(machine, checkout)

    assert (code, machine.ran) == (1, [])
    assert len(lines) == 1 and "not started" in lines[0] and rel in lines[0] and "cannot be loaded" in lines[0]


@pytest.mark.parametrize("rel", ["thomas/core/config.py", "scripts/cage/caged_server.py", "scripts/breakglass_auth.py"])
@pytest.mark.parametrize("staged", [False, True])
def test_an_uncommitted_server_file_that_loads_does_not_keep_the_server_down(
    checkout: Path, rel: str, staged: bool
) -> None:
    """On 2026-11-09 from 07:04 to 08:02 this refused the server every two minutes for 38 files that all loaded.

    The server that had just stopped was running those same files, and every start loads whatever is in the checkout.
    Since the restart watcher stopped waiting for such files, refusing here would leave the server down after a restart.
    """
    (checkout / rel).write_text("x = 2  # somebody's unfinished work that loads\n", encoding="utf-8")
    (checkout / "thomas/core/new_and_staged.py").write_text("y = 1\n", encoding="utf-8")
    _git(checkout, "add", "thomas/core/new_and_staged.py")
    if staged:
        _git(checkout, "add", rel)
    machine = Machine({8897})

    assert _pass(machine, checkout)[0] == 0
    assert machine.ran == ["ThomasCagedServer"]


def test_a_deleted_server_file_is_not_one_that_cannot_load(checkout: Path) -> None:
    (checkout / "thomas/core/config.py").unlink()
    machine = Machine({8897})

    assert _pass(machine, checkout)[0] == 0
    assert machine.ran == ["ThomasCagedServer"]


@pytest.mark.parametrize("rel", ["scripts/forge/gates/gate.py", "thomas/a.js", "scripts/crew/new_tool.py"])
def test_work_elsewhere_does_not_keep_the_server_down(checkout: Path, rel: str) -> None:
    (checkout / rel).parent.mkdir(parents=True, exist_ok=True)
    (checkout / rel).write_text("y = 3\n", encoding="utf-8")
    machine = Machine({8897})

    assert _pass(machine, checkout)[0] == 0
    assert machine.ran == ["ThomasCagedServer"]


@pytest.mark.parametrize(
    ("states", "off", "why"),
    [
        ({"ThomasCagedServer": "Disabled"}, False, "ThomasCagedServer is disabled"),
        ({"ThomasCagedServer": None}, False, "ThomasCagedServer is not registered"),
        ({}, True, "caged_server.off is there"),
    ],
)
def test_a_server_stopped_on_purpose_stays_stopped_and_is_said_once(
    checkout: Path, tmp_path_factory: pytest.TempPathFactory, states: dict, off: bool, why: str
) -> None:
    if off:
        (checkout / "caged_server.off").write_text("", encoding="utf-8")
    memory = tmp_path_factory.mktemp("state") / "keepalive.state.json"
    machine = Machine({8897}, states=states)

    first, second = _pass(machine, checkout, memory), _pass(machine, checkout, memory)

    assert first[0] == 0 and len(first[1]) == 1 and why in first[1][0] and "left stopped" in first[1][0]
    assert second == (0, [])
    assert machine.ran == []


def test_both_up_means_nothing_to_do(checkout: Path) -> None:
    (checkout / "thomas/core/config.py").write_text("x = 2\n", encoding="utf-8")
    machine = Machine({8897, 8898})

    assert _pass(machine, checkout) == (0, [])
    assert machine.ran == []


def test_a_failed_start_is_said_and_exits_1(checkout: Path) -> None:
    machine = Machine(code=1)

    code, lines = _pass(machine, checkout)

    assert code == 1 and machine.ran == ["ThomasSelfChangePromoter", "ThomasCagedServer"]
    assert all("could not start" in line for line in lines) and len(lines) == 2


def test_the_real_probe_tells_a_listener_from_a_closed_port() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert keepalive.listening(port) is True
    assert keepalive.listening(port) is False


def test_git_and_schtasks_open_no_window_and_a_task_state_is_read(checkout: Path, monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    real = subprocess.run

    def run(args: list[str], *rest: Any, **kwargs: Any) -> Any:
        calls.append((args[0], int(kwargs.get("creationflags", 0))))
        if args[0] == "schtasks":
            return subprocess.CompletedProcess(args, 0, '"\\ThomasCagedServer","N/A","Running"\r\n', "")
        return real(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)

    assert keepalive.modified_server_code(checkout) == []
    assert keepalive.task_state("ThomasCagedServer") == "Running"
    assert calls and all(flags & keepalive.NO_WINDOW == keepalive.NO_WINDOW for _program, flags in calls), calls


def test_each_line_goes_to_the_log_with_its_time(tmp_path: Path) -> None:
    log = tmp_path / "keepalive.log"
    say = keepalive._writer(log)

    say("proxy: nothing listens on 127.0.0.1:8897; started ThomasSelfChangePromoter (port now listening)")
    say("second")

    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and lines[0].endswith("(port now listening)") and lines[0][:4].isdigit()


# --- The promoter keeps its proxy, and its broker heals ---------------------------


def _main_until(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException, *, in_init: bool = False):
    started: list[str] = []
    at_exit: list[Any] = []

    class Promoter:
        def __init__(self, **_kwargs: object) -> None:
            if in_init:
                raise error

        def run_once(self) -> None:
            raise error

    monkeypatch.setattr(promoter_service, "Promoter", Promoter)
    monkeypatch.setattr(promoter_service, "_wait_for_lock", lambda *_a, **_k: object())
    monkeypatch.setattr(promoter_service.egress_proxy, "start_in_thread", lambda **_k: started.append("proxy"))
    monkeypatch.setattr(promoter_service.atexit, "register", at_exit.append)
    with pytest.raises(type(error)):
        promoter_service.main(["--cage-root", str(tmp_path)])
    for thread in threading.enumerate():
        if thread.name.startswith("search-broker"):
            thread.join(10)
    for handler in at_exit:
        handler()
    return started


def test_a_broker_that_cannot_load_costs_the_cage_nothing(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setitem(sys.modules, "scripts.cage.search_broker", None)  # its import now raises ImportError
    monkeypatch.delattr(scripts.cage, "search_broker", raising=False)

    with caplog.at_level(logging.INFO, logger=promoter_service.log.name):
        started = _main_until(tmp_path, monkeypatch, LookupError("a bug nothing caught"))

    assert started == ["proxy"]
    assert "search broker not started: ModuleNotFoundError" in caplog.text
    assert "promoter stopped by an error it did not catch" in caplog.text and "a bug nothing caught" in caplog.text
    assert "promoter process exiting" in caplog.text


def test_an_error_while_the_promoter_starts_is_written_down(tmp_path: Path, monkeypatch, caplog) -> None:
    with caplog.at_level(logging.INFO, logger=promoter_service.log.name):
        started = _main_until(tmp_path, monkeypatch, LookupError("no promoter today"), in_init=True)

    assert started == []
    assert "promoter stopped by an error it did not catch" in caplog.text and "no promoter today" in caplog.text


def test_a_stopped_broker_is_started_again_at_most_once_a_minute() -> None:
    now = [0.0]
    keeper = promoter_service._BrokerKeeper(threading.Event(), target=lambda: None, clock=lambda: now[0])

    starts = []
    for when in (0.0, 10.0, 59.0, 61.0, 90.0, 122.0):
        now[0] = when
        if keeper.thread is not None:
            keeper.thread.join(5)
        starts.append(keeper.tick())

    assert starts == [True, False, False, True, False, True]


def test_the_broker_heals_once_its_port_is_free(caplog: pytest.LogCaptureFixture) -> None:
    stop = threading.Event()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    port = blocker.getsockname()[1]
    keeper = promoter_service._BrokerKeeper(
        stop, target=lambda: promoter_service._run_search_broker(stop, port=port), every_s=0.2
    )
    with caplog.at_level(logging.INFO):
        try:
            assert keeper.tick()
            keeper.thread.join(20)
            assert "search broker stopped: OSError" in caplog.text
            blocker.close()
            time.sleep(0.3)
            assert keeper.tick()
            deadline = time.monotonic() + 20
            while not keepalive.listening(port) and time.monotonic() < deadline:
                time.sleep(0.2)
            assert keepalive.listening(port)
        finally:
            blocker.close()
            stop.set()
            if keeper.thread is not None:
                keeper.thread.join(20)

    assert f"search broker listening on 127.0.0.1:{port}" in caplog.text


# --- Thomas says what is true when the proxy is down ------------------------------


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="module")
def dead_proxy() -> tuple[int, list[str]]:
    """A proxy port nothing listens on, and what a model call through it raises, as the chat receives it."""
    import httpx

    port = _closed_port()
    proxy = f"http://127.0.0.1:{port}"

    async def call() -> BaseException:
        with pytest.raises(httpx.ConnectError) as caught:
            async with httpx.AsyncClient(proxy=proxy, timeout=10) as client:
                await client.post("https://model-provider.invalid/v1/responses")
        return caught.value

    async_error = asyncio.run(call())
    with pytest.raises(httpx.ConnectError) as sync_error, httpx.Client(proxy=proxy, timeout=10) as client:
        client.get("https://model-provider.invalid/v1/models")
    return port, [
        f"Reasoning failed: Connection failed after 3 attempts: {async_error}",  # thomas/core/llm_streaming.py
        f"Reasoning failed: {type(async_error).__name__}: {async_error}",
        f"Reasoning failed: {sync_error.value}",
        "Reasoning failed: Token refresh could not reach the OAuth service.",  # openai_codex_oauth.py, same cause
    ]


@pytest.mark.parametrize("autonomy", [2, 5])
def test_the_failure_text_names_the_proxy_when_its_port_refuses(
    dead_proxy: tuple[int, list[str]], monkeypatch: pytest.MonkeyPatch, autonomy: int
) -> None:
    from thomas.marketplace.orchestrator.response_failures import _chat_failure_message

    port, errors = dead_proxy
    monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{port}")

    for error in errors:
        text = _chat_failure_message(error, attempts=2, autonomy_level=autonomy)
        assert "Thomas's network proxy (the promoter service) is not running" in text, (error, text)
        assert "within 15 minutes or at your next sign-in" in text
        assert "selected model" not in text


def test_the_proxy_is_blamed_only_when_it_is_down(
    dead_proxy: tuple[int, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.marketplace.orchestrator.response_failures import _chat_failure_message

    port, errors = dead_proxy
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    assert not any("network proxy" in _chat_failure_message(error) for error in errors)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{listener.getsockname()[1]}")
        assert not any("network proxy" in _chat_failure_message(error) for error in errors)
    monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{port}")
    # A refusal from the provider is the provider's, not the proxy's.
    limited = _chat_failure_message("ChatGPT/Codex HTTP 429 rate limited.")
    assert "short burst limit" in limited and "network proxy" not in limited
    # A sign-in that is missing is a sign-in, not a network, even with the proxy down.
    assert "isn't connected yet" in _chat_failure_message("ChatGPT OAuth is not connected. Sign in first.")
    # A model on this machine never goes through the proxy.
    local = _chat_failure_message(errors[0], target="http://127.0.0.1:11434/v1")
    assert "network proxy" not in local and "couldn't reach" in local


def test_the_chat_turn_asks_the_proxy_off_its_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.marketplace.orchestrator import response_failures

    asked_on: list[threading.Thread] = []

    def refuses(detail: str, target: str) -> bool:
        asked_on.append(threading.current_thread())
        return (detail, target) == ("all connection attempts failed", "https://model.example/v1")

    monkeypatch.setattr(response_failures, "_egress_proxy_refuses", refuses)

    down = asyncio.run(
        response_failures.egress_proxy_down("All connection attempts failed", target="https://model.example/v1")
    )

    assert down is True and asked_on and asked_on[0] is not threading.main_thread()


def test_the_failing_model_is_read_from_the_clients_own_trace() -> None:
    from thomas.marketplace.orchestrator.response_failures import failing_target

    class Model:
        def runtime_trace(self) -> dict[str, Any]:
            attempts = [{"status": "error", "base_url": "http://127.0.0.1:11434/v1"}, {"status": "skipped_cooldown"}]
            return {"requested": {"base_url": "https://chatgpt.com/backend-api/codex"}, "attempts": attempts}

    assert failing_target(Model()) == "http://127.0.0.1:11434/v1"
    assert failing_target(None) == failing_target(object()) == ""


@pytest.mark.parametrize(
    ("target", "names_proxy"), [("https://chatgpt.com/backend-api/codex", True), ("http://127.0.0.1:11434/v1", False)]
)
def test_a_chat_turn_names_the_dead_proxy_and_never_for_a_local_model(
    dead_proxy: tuple[int, list[str]], monkeypatch: pytest.MonkeyPatch, target: str, names_proxy: bool
) -> None:
    from tests.test_a_chat_reply_hands_off_instead_of_timing_out import _Dispatcher, _MemoryCoordinatorStub, _Registry
    from thomas.chat.conversation import ConversationManager
    from thomas.marketplace.orchestrator import response_failures
    from thomas.marketplace.orchestrator.brain import OrchestratorBrain

    port, errors = dead_proxy
    monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{port}")
    monkeypatch.setattr("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _MemoryCoordinatorStub)
    real, asked_on = response_failures._egress_proxy_refuses, []

    def asking(detail: str, target: str = "") -> bool:
        asked_on.append(threading.current_thread())
        return real(detail, target)

    monkeypatch.setattr(response_failures, "_egress_proxy_refuses", asking)

    class Failing:
        capabilities = {"read"}

        async def execute(self, **_kwargs: object):
            yield {"type": "error", "error": errors[0]}

    class Model:
        def runtime_trace(self) -> dict[str, Any]:
            return {"requested": {"base_url": target}, "attempts": [{"status": "error", "base_url": target}]}

    brain = OrchestratorBrain(
        config=None, llm=Model(), memory_engine=None, registry=_Registry({"reasoning": Failing()})
    )
    turn = brain._handle_casual(
        session_id="sess-dead-proxy",
        conversation=ConversationManager(),
        prompt="What changed today?",
        dispatcher=_Dispatcher(),
        mode="auto",
        autonomy_level=3,
        token_economy="optimal",
        turn_start=0.0,
    )
    text = asyncio.run(turn).last_assistant_message()

    assert ("Thomas's network proxy (the promoter service) is not running" in text) is names_proxy, text
    assert ("selected model" in text) is not names_proxy, text
    assert asked_on and threading.main_thread() not in asked_on  # never on the chat's event loop


# --- The keepalive's own task ------------------------------------------------------

PS1 = REPO / "scripts" / "cage" / "enable_cage_keepalive.ps1"


def test_the_keepalive_runs_as_its_own_task_for_you() -> None:
    text = PS1.read_text(encoding="utf-8")

    for needed in (
        '$taskName = "ThomasCageKeepalive"',
        "-LogonType Interactive -RunLevel Limited",
        "-MultipleInstances IgnoreNew",
        "-RepetitionInterval (New-TimeSpan -Minutes 15)",
        '".venv\\Scripts\\pythonw.exe"',
        '"cage_keepalive.py"',
        '--log `"$log`"',
        '"keepalive.log"',
        "Rollback: Unregister-ScheduledTask -TaskName ThomasCageKeepalive -Confirm:$false",
    ):
        assert needed in text, needed
    assert "Highest" not in text and "RunAsAdministrator" not in text


def test_the_keepalive_setup_says_an_empty_log_is_normal() -> None:
    # The keepalive writes a line only when it acts, so with both ports up there is no
    # keepalive.log at all; the setup says so and names where to look instead.
    said = [line for line in PS1.read_text(encoding="utf-8").splitlines() if line.strip().startswith("Say ")]

    assert any("no keepalive.log yet is normal while both ports are up" in line for line in said), said
    assert any("(Get-ScheduledTaskInfo -TaskName $taskName).LastTaskResult is 0" in line for line in said), said


@pytest.mark.skipif(os.name != "nt", reason="PowerShell's own parser")
def test_the_keepalive_script_parses() -> None:
    parse = (
        "$tokens = $null; $errors = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{PS1}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "$errors | ForEach-Object { $_.Message }; 'errors:' + $errors.Count"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", parse],
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=keepalive.NO_WINDOW,
    )

    assert out.stdout.strip().endswith("errors:0"), out.stdout + out.stderr
