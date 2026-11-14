"""Crash and posting faults leave a durable, blocking after-check for every landing."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.cage import checker_jobs as cj
from scripts.cage import window_loop as wl
from scripts.cage.window_record import Record


class Link:
    def __init__(self) -> None:
        self.jobs: list[cj.Job] = []
        self.fail = False
        self.verdict = None

    def answering(self):
        return ""

    def post(self, kind, **fields):
        if self.fail:
            raise OSError("posting stopped")
        job = cj.Job(
            f"{len(self.jobs):024x}",
            kind,
            fields["base"],
            fields["commit"],
            fields["tree"],
            tuple(fields["changed"]),
            posted_at=10.0,
        )
        self.jobs.append(job)
        return job

    def result(self, job):
        if self.verdict:
            return cj.Result(job.id, job.kind, job.base, job.commit, job.tree, self.verdict, seen=1, ran=1)

    def forget(self, job):
        pass


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scripts.cage import self_change_checks, window_record

    monkeypatch.setattr(self_change_checks, "run_git", lambda *a, **k: SimpleNamespace(stdout="a" * 40, returncode=0))
    monkeypatch.setattr(window_record, "landed_on", lambda *a: True)
    monkeypatch.setattr(window_record, "window_summary", lambda *a: [{"sid": "self-a", "commit": "2" * 40}])
    # Existing loop imports these names directly; the extracted recovery module may use window_record itself.
    monkeypatch.setattr(wl, "landed_on", lambda *a: True, raising=False)
    monkeypatch.setattr(wl, "window_summary", lambda *a: [{"sid": "self-a", "commit": "2" * 40}])
    (tmp_path / "record").mkdir()
    record, link = Record(tmp_path / "record"), Link()
    closed = []
    window = SimpleNamespace(
        opened=SimpleNamespace(window_id="w"),
        why_not=lambda: "",
        off_marker=lambda: "",
        close=closed.append,
        take_ended=lambda: [],
        status=lambda: {},
    )
    lane = SimpleNamespace(
        last_landed=None, owned=lambda: frozenset({"self-a"}), take=lambda *a, **k: None, close=lambda: None
    )
    card = SimpleNamespace(
        repo=tmp_path, branch="dev", busy=frozenset(), skip=lambda: frozenset({"self-a"}), taking=threading.Lock()
    )
    undo = SimpleNamespace(start=lambda *a, **k: "", step=lambda: "", current=None)

    def build():
        return wl.WindowLoop(
            card=card,
            lane=lane,
            undoer=undo,
            window=window,
            link=link,
            record=record,
            home=tmp_path / "home",
            clock=lambda: 20.0,
        )

    return SimpleNamespace(loop=build(), build=build, record=record, link=link, lane=lane, closed=closed, card=card)


def landed(rig, sid="self-a", commit="2" * 40, files=("thomas/a.py",)):
    rig.record.event("landing_intent", window_id="w", sid=sid, commit=commit, parent="1" * 40, tree="a" * 40)
    rig.record.event("landed", window_id="w", sid=sid, commit=commit, parent="1" * 40, files=list(files))
    rig.lane.last_landed = (sid, commit, "1" * 40, list(files))


def test_a_failed_post_keeps_the_landing_blocked_and_retries_without_losing_it(rig):
    landed(rig)
    rig.link.fail = True
    with pytest.raises(OSError):
        rig.loop._landed()
    assert rig.loop.after is not None and rig.lane.last_landed is not None
    rig.link.fail = False
    rig.loop._after_check()
    assert len(rig.link.jobs) == 1 and rig.lane.last_landed is None
    posted = rig.record.events()[-1]
    assert posted["name"] == "after_posted" and cj.Job.parse(posted["job"]) == rig.link.jobs[0]


def test_restart_restores_the_posted_job_before_landings_can_resume(rig):
    landed(rig)
    rig.loop._landed()
    job = rig.link.jobs[0]
    restarted = rig.build()
    restarted.recover()
    assert restarted.after is not None and restarted.after.job == job
    assert restarted.after.posted == job.posted_at, "a restart never extends an unanswered job's deadline"
    assert len(rig.link.jobs) == 1
    rig.link.verdict = cj.PASSED
    restarted._after_check()
    assert restarted.after is None


def test_restart_posts_every_unchecked_landing_in_order_with_its_windows_union(rig):
    landed(rig)
    landed(rig, "self-b", "3" * 40, ("thomas/b.py",))
    restarted = rig.build()
    restarted.recover()
    assert restarted.after is not None
    rig.link.verdict = cj.PASSED
    restarted._after_check()
    restarted._after_check()
    assert [job.commit for job in rig.link.jobs] == ["2" * 40, "3" * 40]
    assert rig.link.jobs[-1].changed == ("thomas/a.py", "thomas/b.py")
    assert restarted.after is None


def test_recovered_intent_on_dev_gets_an_after_check_and_killed_window_gets_closed(rig):
    rig.record.event("window_opened", window_id="w")
    rig.record.event(
        "landing_intent",
        window_id="w",
        sid="self-a",
        commit="2" * 40,
        parent="1" * 40,
        tree="a" * 40,
        files=["thomas/a.py"],
    )
    rig.loop.recover()
    assert rig.loop.after is not None
    closed = [event for event in rig.record.events() if event["name"] == "window_closed"]
    assert len(closed) == 1 and closed[0]["landed"]
    rig.loop.recover()
    assert len([event for event in rig.record.events() if event["name"] == "window_closed"]) == 1


def test_an_after_check_record_failure_never_releases_the_block(rig, monkeypatch):
    landed(rig)
    rig.loop._landed()
    rig.link.verdict = cj.PASSED
    original = rig.record.event

    def event(name, **fields):
        if name == "after_check":
            raise OSError("record unavailable")
        return original(name, **fields)

    monkeypatch.setattr(rig.record, "event", event)
    with pytest.raises(OSError):
        rig.loop._after_check()
    assert rig.loop.after is not None


def test_a_dead_loop_returns_its_changes_to_cards_even_on_unexpected_failure(rig):
    stop = threading.Event()
    rig.loop.undoer.invalidate = lambda: None
    rig.loop.undoer.close = lambda: None

    def fail():
        stop.set()
        raise ImportError("lazy module failed")

    rig.loop.tick = fail
    rig.loop.run(stop, interval_s=0)
    assert rig.card.skip() == frozenset() and rig.closed


def test_an_after_post_record_error_reuses_the_job_but_keeps_the_block(rig, monkeypatch):
    landed(rig)
    original = rig.record.event

    def fail(name, **fields):
        if name == "after_posted":
            raise OSError("record unavailable")
        return original(name, **fields)

    monkeypatch.setattr(rig.record, "event", fail)
    with pytest.raises(OSError):
        rig.loop._landed()
    assert rig.loop.after is not None and rig.lane.last_landed is not None
    monkeypatch.setattr(rig.record, "event", original)
    rig.loop._after_check()
    assert len(rig.link.jobs) == 1 and rig.lane.last_landed is None


@pytest.mark.parametrize("result", [None, cj.PASSED])
def test_recovery_reposts_a_missing_job_unless_its_completed_answer_is_available(rig, result):
    landed(rig)
    rig.loop._landed()
    rig.link.root = rig.card.repo / "empty-checker"
    rig.link.verdict = result
    restarted = rig.build()
    restarted.recover()
    restarted._after_check()
    assert len(rig.link.jobs) == (2 if result is None else 1)


@pytest.mark.parametrize("trouble", ["off", "checker", "record"])
def test_window_trouble_immediately_returns_waiting_changes_to_cards(rig, monkeypatch, trouble):
    assert rig.loop.card_skip() == frozenset({"self-a"})
    if trouble == "off":
        rig.loop.window.off_marker = lambda: "off"
    elif trouble == "checker":
        rig.link.answering = lambda: "not answering"
    else:
        monkeypatch.setattr(rig.record, "usable", lambda: "not writable")
    assert rig.loop.card_skip() == frozenset()


def test_recovery_reads_a_real_landed_intent_from_dev_and_closes_its_window(tmp_path):
    from tests.green_support import git, make_blue

    repo = make_blue(tmp_path)
    git(repo, "checkout", "-qb", "dev")
    parent = git(repo, "rev-parse", "HEAD")
    (repo / "thomas/fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(
        repo,
        "commit",
        "-qam",
        "landed (window w, ABC)\n\nThomas-Submission-Id: self-a\nThomas-Committed-By: self-change-promoter",
    )
    commit = git(repo, "rev-parse", "HEAD")
    (tmp_path / "record").mkdir()
    record = Record(tmp_path / "record")
    record.event("window_opened", window_id="w")
    record.event("landing_intent", window_id="w", sid="self-a", commit=commit)
    link = Link()
    loop = wl.WindowLoop(
        card=SimpleNamespace(repo=repo, branch="dev"),
        lane=SimpleNamespace(last_landed=None),
        undoer=object(),
        window=object(),
        link=link,
        record=record,
        home=tmp_path / "home",
    )
    loop.recover()
    assert loop.after is not None and loop.after.parent == parent
    assert loop.after.files == ("thomas/fix_me.py",)
    loop._after_check()
    assert link.jobs[0].tree == git(repo, "rev-parse", "HEAD^{tree}")
    closed = [row for row in record.events() if row["name"] == "window_closed"]
    assert closed[0]["landed"][0]["commit"] == commit


def test_a_finalization_error_after_land_never_strands_its_last_landed_marker(rig):
    calls = []

    def step(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            landed(rig)
            raise OSError("outbox write failed after landing")

    rig.lane.step = step
    rig.loop._write_status = lambda: None
    with pytest.raises(OSError):
        rig.loop.tick()
    rig.loop.tick()
    assert len(rig.link.jobs) == 1 and rig.loop.after is not None


def test_recovered_intents_keep_original_order_and_prior_after_checks(rig):
    rig.record.event(
        "landing_intent", window_id="w", sid="self-a", commit="2" * 40, parent="1" * 40, files=["thomas/a.py"]
    )
    rig.record.event("after_check", sid="self-a", commit="2" * 40, verdict=cj.PASSED)
    landed(rig, "self-b", "3" * 40, ("thomas/b.py",))
    rig.loop.recover()
    assert rig.loop.after.commit == "3" * 40
    rig.loop._after_check()
    assert rig.link.jobs[0].changed == ("thomas/a.py", "thomas/b.py")
