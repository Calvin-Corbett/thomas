"""Follow-ups end to end with REAL processes: --submit does not wait for a slow dry run, a dry run never delays the turn,
run it again after the worker died, and the worker's log."""

from __future__ import annotations

import json
import time

import psutil
from scripts.crew.brief.landing_store import FileTicketStore

from tests.test_land_e2e import FAKE_COMMIT, run, start, world, write  # noqa: F401 - world is a fixture


def test_submit_returns_once_the_ticket_exists_and_a_slow_dry_run_never_delays_the_turn(world):
    slow_dry = FAKE_COMMIT.replace("if dry:\n", "if dry:\n    time.sleep(40)\n", 1)
    assert "time.sleep(40)" in slow_dry
    (world.tmp / "tool" / "fake_commit.py").write_text(slow_dry)
    write(world, "a.txt", "a\n")
    write(world, "b.txt", "b\n")
    t0 = time.monotonic()
    holder = start(world, "agent-a", "--message", "feat: a", "--include", "a.txt", seconds="8")
    time.sleep(2.0)
    t1 = time.monotonic()
    code, out = run(world, "agent-b", "--submit", "--message", "feat: b", "--include", "b.txt", timeout=90)
    assert code == 0 and out["status"] == "submitted" and time.monotonic() - t1 < 15  # was: the 40 s dry run first
    ticket = out["ticket"]
    code, out = run(world, "agent-b", "--wait", str(ticket), "--wait-seconds", "100", timeout=130)
    assert code == 0 and out["status"] == "landed", out
    assert time.monotonic() - t0 < 34  # the dry run was stopped when b's turn came, not waited for (40 s)
    assert holder.wait(timeout=60) == 0
    log = (world.queue / "logs" / f"T{ticket:06d}.log").read_text()
    assert "adopted by worker pid" in log and "granted" in log and "landed" in log


def test_run_it_again_after_the_worker_died_lands_and_says_the_old_ticket_was_taken_back(world):
    write(world, "a.txt", "a\n")
    write(world, "b.txt", "b\n")
    assert run(world, "agent-a", "--submit", "--message", "feat: a", "--include", "a.txt", seconds="10")[0] == 0
    time.sleep(1.0)
    code, out = run(world, "agent-b", "--submit", "--message", "feat: b", "--include", "b.txt", timeout=60)
    first = out["ticket"]
    worker = FileTicketStore(world.queue).events()
    pid = next(e["owner_pid"] for e in reversed(worker) if e["kind"] == "adopted" and e["ticket"] == first)
    psutil.Process(pid).kill()  # the worker dies; with the holder submitted too, nobody polls in between
    time.sleep(1.0)
    proc = start(world, "agent-b", "--message", "feat: b", "--include", "b.txt", "--wait-seconds", "120")
    stdout, stderr = proc.communicate(timeout=160)
    out = json.loads([ln for ln in stdout.splitlines() if ln.startswith("{")][-1])
    assert proc.returncode == 0 and out["status"] == "landed" and out["ticket"] == first + 1, stdout + stderr
    assert f"your earlier ticket T{first:06d} for this change was taken back" in stderr  # was: exit 4 after 90 s
    assert run(world, "agent-a", "--wait", "1", "--wait-seconds", "60", timeout=90)[0] == 0
