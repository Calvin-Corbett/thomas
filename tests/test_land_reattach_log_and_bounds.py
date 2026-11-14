"""Follow-ups 3, 4 and 6: run it again after a dead worker, a worker log and a git that does not answer, the two
mutants the verifier saw survive (the 8-lease wall bound), and pruning of the new per-ticket files."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from scripts.crew.brief import land, land_git, land_worker, landing_proc
from scripts.crew.brief.landing_liveness import Clocks, judge
from scripts.crew.brief.landing_queue import Config

from tests._landing_fakes import World

ARGS = SimpleNamespace(
    message="feat b",
    include=["b.txt"],
    no_detach=False,
    agent="",
    allow_scope_fallback=False,
    fallback_reason="",
    max_hold=900.0,
    wait_timeout=2700.0,
    no_precheck=False,
)


def submitted_behind_a_holder(tmp_path):  # noqa: ANN001, ANN201
    """b submitted T2 behind holder T1; its worker (pid 201) adopted it; the submitting land.py has returned."""
    w = World(tmp_path)
    h = w.lane("h", 100)
    h.wait_turn(h.enqueue("kh", "s"))
    n2 = w.lane("b", 101).enqueue("kb", "feat b", mode="detached")
    w.lane("b", 201).adopt(n2)
    w.alive.discard(101)
    return w, n2


# ---- 3. run it again
def test_run_it_again_after_the_worker_died_queues_a_new_ticket_with_a_worker_and_says_why(tmp_path, capsys):
    w, n2 = submitted_behind_a_holder(tmp_path)
    w.alive.discard(201)  # the worker died; nobody has polled since
    again = w.lane("b", 102)
    num, code, text, _ = land.start_ticket(ARGS, again, "kb")
    assert (code, text) == (0, "queued") and num == n2 + 1  # was: "attached", so no worker for the new ticket
    assert again.states()[n2]["state"] == "abandoned"
    told = capsys.readouterr().err
    assert (
        f"your earlier ticket T{n2:06d} for this change was taken back (waiter_dead); queued again as T{num:06d}"
        in told
    )


def test_run_it_again_while_the_worker_lives_still_attaches(tmp_path, capsys):
    w, n2 = submitted_behind_a_holder(tmp_path)
    num, code, text, _ = land.start_ticket(ARGS, w.lane("b", 102), "kb")
    assert (num, code, text) == (n2, 0, "attached") and capsys.readouterr().err == ""


def test_a_worker_that_dies_between_the_attach_check_and_the_ticket_still_gets_a_new_worker(tmp_path):
    w, n2 = submitted_behind_a_holder(tmp_path)
    again = w.lane("b", 102)
    real = again.find_open

    def look_then_die(key: str) -> int | None:
        found = real(key)
        w.alive.discard(201)  # the worker dies right after this look
        return found

    again.find_open = look_then_die
    num, _code, text, _ = land.start_ticket(ARGS, again, "kb")
    assert num == n2 + 1 and text == "queued"  # was: "attached" to the old number, and nobody waited for the new one


# ---- 4. a worker log, and a git that does not answer
def test_a_git_that_does_not_answer_is_no_answer_and_never_a_crash(tmp_path, monkeypatch, capsys):
    def slow(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise subprocess.TimeoutExpired(cmd="git log", timeout=60)

    monkeypatch.setattr(landing_proc, "run", slow)
    assert land_git.git(tmp_path, "log") is None  # no answer, never the same as empty output
    assert land_git.find_landed(tmp_path, "lq-anything") is None  # not landed: the safe direction
    assert "did not answer in 60 s" in capsys.readouterr().err


def test_the_worker_writes_its_output_and_any_crash_to_its_own_log(tmp_path):
    script = tmp_path / "worker_stub.py"
    script.write_text("print('adopted', flush=True)\nraise RuntimeError('boom in the worker')\n")
    log = land_worker.worker_log(tmp_path / "queue", 7)
    proc = land_worker.spawn_worker(7, script, log)
    assert proc is not None and proc.wait(timeout=30) != 0
    text = log.read_text(encoding="utf-8")
    assert "adopted" in text and "RuntimeError: boom in the worker" in text  # was: DEVNULL, a death nobody could read


def test_a_ticket_taken_back_names_its_worker_log(tmp_path):
    w, n2 = submitted_behind_a_holder(tmp_path)
    log = land_worker.worker_log(w.store.root, n2)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("Traceback (most recent call last): ...\n")
    w.alive.discard(201)
    w.lane("x", 300).reap()
    code, status, text, extra = land_worker.report(w.lane("b", 102), n2)
    assert code == 4 and extra["worker_log"] == str(log) and str(log) in text


# ---- 6. the wall bound of eight leases on a holder's own run-time count (verifier mutant RANBOUND)
LEASE = 10.0


def judged(granted_ago: float, ran: float) -> tuple[bool, str]:
    now = 1_000_000.0
    s = {
        "ticket": {"num": 1, "created": now - granted_ago - 5, "pid": 1},
        "ledgered": True,
        "state": "holding",
        "granted_at": now - granted_ago,
        "max_hold": LEASE,
        "owner_pid": 1,
    }
    clocks = Clocks(lambda: now, lambda: 5000.0, 30.0)
    return judge(s, {"t": now, "ran": ran, "child": 0}, None, now, Config(), lambda pid, start: True, clocks)


def test_a_holder_whose_run_count_never_moves_still_loses_its_lease_after_eight_leases():
    assert judged(8 * LEASE - 1, ran=0.0) == (True, "")  # it may honestly have been asleep that long
    assert judged(8 * LEASE + 1, ran=0.0) == (False, "lease_expired")  # the wall bound catches a holder that lies
    assert judged(LEASE + 1, ran=LEASE + 1)[0] is False  # its own count passing the lease ends it at once


def test_the_reaper_takes_the_slot_back_from_a_holder_that_never_counts_its_run_time(tmp_path):
    w = World(tmp_path, Config(poll=2.0, say_every=1e9, max_hold=LEASE))
    h = w.lane("h", 100)
    n = h.enqueue("kh", "s")
    h.wait_turn(n)
    observer, _ = w.bystander()
    w.life(70, observer, (h, n, "holding", {"ran": 0.0}))
    assert h.states()[n]["state"] == "holding"  # seven leases of wall time and a run count of 0: not yet
    w.life(16, observer, (h, n, "holding", {"ran": 0.0}))
    s = h.states()[n]
    assert s["state"] == "skipped" and s["reason"].startswith("lease_expired")


# ---- pruning takes a ticket's refusal output and worker log with it
def test_a_pruned_ticket_takes_its_refusal_output_and_worker_log_with_it(tmp_path):
    w = World(tmp_path, Config(poll=2.0, say_every=1e9, keep_closed=2))
    a = w.lane("a", 100)
    nums = [a.enqueue(f"k{i}", "s") for i in range(14)]
    for n in nums[:-1]:
        a.withdraw(n)
    root = w.store.root
    files = {
        n: (root / "output" / f"T{n:06d}-refused.txt", root / "logs" / f"T{n:06d}.log") for n in (nums[0], nums[-1])
    }
    for paths in files.values():
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x")
    assert a.maybe_prune() > 0
    assert not any(p.exists() for p in files[nums[0]])  # pruned with its ticket
    assert all(p.exists() for p in files[nums[-1]])  # the open ticket keeps its files
