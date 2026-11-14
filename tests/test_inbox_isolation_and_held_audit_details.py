"""Inbox checks use scratch code, and inconclusive holds retain audit details."""

from pathlib import Path

from scripts.cage import shell_runner

from tests import hand_in_hold_support as support
from tests import test_the_repo_ritual_works_inside_green as ritual
from thomas.server import autopilot_hold_tick, autopilot_restart, capacity_ledger, hand_in_hold
from thomas.server.proof import runner


def test_inbox_does_not_launch_the_real_checkout(tmp_path: Path, monkeypatch) -> None:
    def capture(request):
        script = tmp_path / "green" / "work" / "exec-ritual" / "scripts" / "crew" / "workboard" / "message.py"
        assert f'"{script}"' in request["command"]
        assert str(ritual.REPO / "scripts" / "crew" / "workboard" / "message.py") not in request["command"]
        assert script.is_file()
        return {"returncode": 0, "output": "Workboard message tool: PASS"}

    monkeypatch.setattr(shell_runner, "run_command", capture)
    ritual.test_the_mandated_inbox_check_passes_in_green(tmp_path, monkeypatch)


def test_the_held_message_keeps_the_audit_test_and_long_path(tmp_path: Path, monkeypatch) -> None:
    project = support.make_project(tmp_path, monkeypatch)
    work, catalog, cid = project
    support.book(project)
    node = "tests/test_the_repo_ritual_works_inside_green.py::test_the_mandated_inbox_check_passes_in_green"
    path = "C:/" + "long-folder/" * 35 + "Thomas"
    finding = f"{path} [test {node}] was opened from scripts/cage/shell_runner.py:423 run_command (a child command)"
    detail = runner._unexplained("REAL THOMAS DATA ACCESS (1 path):\n  " + finding)
    assert path in detail and node in detail
    why = "Not checked before this card: the same tests did not run to the end: " + detail
    held = hand_in_hold.hold(work, catalog, cid, "check", why, costly=False, no_answer=True)
    assert held["why"] == why
    words = hand_in_hold.phase(work, catalog, cid)[1]
    assert node in words and path in words


def test_a_transient_failure_does_not_end_unlimited_inconclusive_retries(tmp_path: Path, monkeypatch) -> None:
    project = support.make_project(tmp_path, monkeypatch)
    work, catalog, cid = project
    monkeypatch.setattr(hand_in_hold, "clock", lambda: 100.0)
    booked = support.book(project)
    held = hand_in_hold.hold(work, catalog, cid, "check", "dev audit failed", costly=False, no_answer=True)
    assert hand_in_hold.change(catalog, cid, booked["gen"], {**held, "tries": 1100, "state": "checking"}, expected=held)
    after = hand_in_hold.hold(work, catalog, cid, "check", "the hand-in attempt did not complete", costly=False)
    assert after["state"] == "held"
    assert after["no_answers"] == 1
    assert after["next_at"] == 100.0 + hand_in_hold.RETRY_MAX_S


def test_unlimited_retry_backoff_does_not_overflow() -> None:
    assert hand_in_hold.retry_after(100_000) == hand_in_hold.RETRY_MAX_S


def test_the_tick_retries_an_inconclusive_check_beyond_the_old_limits(tmp_path: Path, monkeypatch) -> None:
    project = support.make_project(tmp_path, monkeypatch)
    work, catalog, cid = project
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))
    monkeypatch.setattr(autopilot_hold_tick, "_previous_listener_gone", lambda _port: False)
    booked = support.book(project)
    assert hand_in_hold.change(catalog, cid, booked["gen"], {**booked, "tries": 100_000}, expected=booked)
    held = hand_in_hold.hold(work, catalog, cid, "check", "dev audit failed", costly=False, no_answer=True)
    assert held is not None and held["state"] == "held"
    scheduled = []
    monkeypatch.setattr(autopilot_hold_tick, "_schedule", lambda _app, row, _catalog: scheduled.append(row) or True)
    support.due(project)
    assert support.tick(project) == [cid]
    assert scheduled[0]["tries"] == 100_001
    assert support.row(project)["state"] == "checking"
