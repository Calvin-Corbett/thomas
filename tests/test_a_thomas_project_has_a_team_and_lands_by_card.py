"""A Thomas project gets Build's full team in a private copy, and lands only through your card.

You asked: "so when thomas works on himself make sure their is a task
manegrr just for thomas project like he does with every new build." Before
this, asking Thomas to change himself got one chat worker with no task
manager and no builders or reviewers. `thomas_project.start_thomas_project`
gives it Build's whole team instead: a green copy of Thomas's own source
(never the running checkout), a Build run started in it through the same
guarded start hook Chat uses, and a settle step (`settle_if_finished`) that
only ever hands a FINISHED, checked run to your promoter card -- never a
failed one, and never twice.

Fix round 1 (opus review of 2467fd28, probed with `probe_settle.py` /
`probe_after_settle.py` against a real green): `green_handoff.settle`
deletes the whole green, and the conversation -- every turn, including the
`thomas_project` stamp -- lived only inside it. The settle tests below now
prove the conversation survives that deletion (I1) instead of only checking
the happy path where nothing gets removed underneath it.

Fix round 2 (opus re-review of 212cd52f, an 8-case probe against real
greens): that round's own commit message and changelog wrongly claimed
`start_thomas_project`'s blocking calls already ran through
`asyncio.to_thread` -- they did not; this round makes it true (I2, below,
is the one test here allowed to use a real 1s `time.sleep` in a fake
`create_green`'s own thread, per this round's instructions). Also fixed: a
genuinely failed hand-off no longer forgets the live conversation's
registry row (Case G); a `remove_green` that fails AFTER a real submission
was written is no longer reported as a failed hand-off (Case H); and the
Autopilot `done` settle's summary -- which `self_change_promoter.py` builds
the landed commit's subject from -- now names the actual change instead of
the done check's own "Thomas replied without changing files" reply.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings
from thomas.server import green_checkout, green_handoff, thomas_project
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import evolve_agent_autopilot as ap


@pytest.fixture
def blue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stand in for Thomas's own source checkout -- never a real one in a test.

    Also stands in for `_default_repo_root()`, the catalog `start_thomas_project`
    binds under (fix round 1): both resolve to the same root in production, so
    both are patched to the same fixture here.
    """
    root = tmp_path / "blue"
    root.mkdir()
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: root)
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: root)
    return root


def _stub_create_green(tmp_path: Path, calls: list[tuple[Path, str]]):
    """Stand in for a real `git clone --shared`: makes a plain folder, records the call."""

    def _create(*, blue: Path, execution_id: str) -> green_checkout.Green:
        calls.append((blue, execution_id))
        work = tmp_path / "green-work" / execution_id
        (work / ".git").mkdir(parents=True)
        return green_checkout.Green(execution_id, work, tmp_path / "green-git" / execution_id, "deadbeef", blue)

    return _create


def _fake_start(status: int, payload: dict[str, Any]) -> tuple[Any, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    async def _start(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        calls.append(body)
        return status, payload

    return _start, calls


def _agent_turn(**overrides: Any) -> dict[str, Any]:
    turn = dict(
        model="claude-cli",
        transcript="",
        changed_files=["a.py"],
        returncode=0,
        ok=True,
        noop=False,
        reason="1 file(s) changed",
        outcome="completed",
    )
    turn.update(overrides)
    return turn


# ── start_thomas_project ──


def test_start_makes_a_green_of_the_thomas_source_and_runs_in_its_work_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blue: Path
) -> None:
    green_calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(green_checkout, "create_green", _stub_create_green(tmp_path, green_calls))
    start, start_calls = _fake_start(200, {"ok": True})
    app = {APP_PRAXIS_START_CODE_RUN: start}

    result = asyncio.run(
        thomas_project.start_thomas_project(app, request="fix the thing", settings={"autonomy_level": 5}, port=8898)
    )

    assert green_calls == [(blue, result["execution_id"])]
    assert result["project_root"] != str(blue)
    assert result["project_root"] == str(tmp_path / "green-work" / result["execution_id"])
    assert result["status"] == 200

    assert len(start_calls) == 1
    body = start_calls[0]
    assert (body["project_root"], body["conversation_id"]) == (result["project_root"], result["conversation_id"])
    assert (body["project_choice"], body["autonomy_level"]) == ("picked", 5) and body["message"].startswith(
        "fix the thing"
    )

    conv = forge_code_store.load_conversation(Path(result["project_root"]), result["conversation_id"])
    assert conv is not None
    assert conv["thomas_project"]["execution_id"] == result["execution_id"]
    assert conv["title"] == "fix the thing"  # short enough to need no truncation


def test_title_is_the_first_line_capped_at_80_chars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blue: Path
) -> None:
    monkeypatch.setattr(green_checkout, "create_green", _stub_create_green(tmp_path, []))
    start, _calls = _fake_start(200, {"ok": True})
    app = {APP_PRAXIS_START_CODE_RUN: start}
    long_request = ("x" * 120) + "\nsecond line is never used"

    result = asyncio.run(thomas_project.start_thomas_project(app, request=long_request, settings={}, port=8898))

    conv = forge_code_store.load_conversation(Path(result["project_root"]), result["conversation_id"])
    assert conv is not None
    assert conv["title"] == ("x" * 80) + "…"


def test_a_refused_start_removes_the_green_and_forgets_the_registry_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blue: Path
) -> None:
    green_calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(green_checkout, "create_green", _stub_create_green(tmp_path, green_calls))
    removed: list[str] = []
    monkeypatch.setattr(green_checkout, "remove_green", lambda g: removed.append(g.execution_id))
    start, start_calls = _fake_start(
        409, {"ok": False, "error": "another Code run is still active", "code": "agent_already_running"}
    )
    app = {APP_PRAXIS_START_CODE_RUN: start}

    with pytest.raises(thomas_project.ThomasProjectError):
        asyncio.run(thomas_project.start_thomas_project(app, request="fix", settings={}, port=8898))

    assert len(start_calls) == 1
    assert removed == [green_calls[0][1]]
    cid = start_calls[0]["conversation_id"]
    assert forge_code_projects.conversation_metadata(blue, cid) is None  # I1 minor: no dangling row either


def test_any_exception_after_create_green_still_removes_it_not_only_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blue: Path
) -> None:
    """Minor: wrap everything after `create_green` -- a bug, not just a refused start, cleans up."""
    monkeypatch.setattr(green_checkout, "create_green", _stub_create_green(tmp_path, []))
    removed: list[str] = []
    monkeypatch.setattr(green_checkout, "remove_green", lambda g: removed.append(g.execution_id))

    async def _boom(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        raise RuntimeError("the start hook itself blew up, not a clean refusal")

    app = {APP_PRAXIS_START_CODE_RUN: _boom}

    with pytest.raises(RuntimeError, match="blew up"):
        asyncio.run(thomas_project.start_thomas_project(app, request="fix", settings={}, port=8898))

    assert len(removed) == 1


def test_an_oserror_removing_the_green_does_not_hide_the_original_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blue: Path
) -> None:
    monkeypatch.setattr(green_checkout, "create_green", _stub_create_green(tmp_path, []))
    monkeypatch.setattr(green_checkout, "remove_green", lambda g: (_ for _ in ()).throw(OSError("locked")))
    start, _calls = _fake_start(409, {"ok": False, "error": "busy", "code": "agent_already_running"})
    app = {APP_PRAXIS_START_CODE_RUN: start}

    with pytest.raises(thomas_project.ThomasProjectError, match="Build refused"):
        asyncio.run(thomas_project.start_thomas_project(app, request="fix", settings={}, port=8898))


def test_a_cancelled_start_still_removes_the_green_and_forgets_the_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blue: Path
) -> None:
    """Minor: extend the cleanup to BaseException -- asyncio.CancelledError is not an Exception,
    so the old `except Exception:` let a cancelled start leak both the green and its row."""
    green_calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(green_checkout, "create_green", _stub_create_green(tmp_path, green_calls))
    removed: list[str] = []
    monkeypatch.setattr(green_checkout, "remove_green", lambda g: removed.append(g.execution_id))

    async def _cancelled(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        raise asyncio.CancelledError()

    app = {APP_PRAXIS_START_CODE_RUN: _cancelled}

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(thomas_project.start_thomas_project(app, request="fix", settings={}, port=8898))

    assert len(removed) == 1
    assert removed == [green_calls[0][1]]


# ── Ruling F: an optional caller-owned green, and extra meta fields ──


def test_a_passed_in_green_is_used_and_survives_a_refused_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blue: Path
) -> None:
    green_calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(green_checkout, "create_green", _stub_create_green(tmp_path, green_calls))
    removed: list[str] = []
    monkeypatch.setattr(green_checkout, "remove_green", lambda g: removed.append(g.execution_id))
    start, start_calls = _fake_start(409, {"ok": False, "error": "busy", "code": "agent_already_running"})
    app = {APP_PRAXIS_START_CODE_RUN: start}

    work = tmp_path / "caller-green" / "work"
    (work / ".git").mkdir(parents=True)
    caller_green = green_checkout.Green("thomas-caller-owned", work, tmp_path / "caller-git", "deadbeef", blue)

    with pytest.raises(thomas_project.ThomasProjectError):
        asyncio.run(thomas_project.start_thomas_project(app, request="fix", settings={}, port=8898, green=caller_green))

    assert len(start_calls) == 1
    assert green_calls == []  # a passed-in green is used, never (re-)created
    assert removed == []  # ...and it survives a refused start: the caller owns it
    cid = start_calls[0]["conversation_id"]
    assert forge_code_projects.conversation_metadata(blue, cid) is None  # its registry row is still forgotten


def test_meta_is_merged_but_cannot_replace_execution_id_or_settled_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blue: Path
) -> None:
    monkeypatch.setattr(green_checkout, "create_green", _stub_create_green(tmp_path, []))
    start, _calls = _fake_start(200, {"ok": True})
    app = {APP_PRAXIS_START_CODE_RUN: start}
    meta = {"purpose": "ratchet", "candidate_sha": "abc123", "execution_id": "not-allowed", "settled_at": "not-allowed"}

    result = asyncio.run(
        thomas_project.start_thomas_project(app, request="ratchet candidate", settings={}, port=8898, meta=meta)
    )

    conv = forge_code_store.load_conversation(Path(result["project_root"]), result["conversation_id"])
    assert conv is not None
    record = conv["thomas_project"]
    assert (record["purpose"], record["candidate_sha"]) == ("ratchet", "abc123")
    assert record["execution_id"] == result["execution_id"]  # meta cannot override the real one
    assert "settled_at" not in record  # meta cannot pre-seed it either


# ── Fix round 2, I2: start_thomas_project must not block the event loop ──


def test_a_slow_create_green_does_not_stall_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blue: Path
) -> None:
    """The one sanctioned real `time.sleep`: a fake `create_green` that blocks its OWN thread for
    1s. Before this round, `create_green` ran inline with no await ahead of it, so a ticker task
    merely `ensure_future`'d before the call never got a turn to run AT ALL until the blocking
    call finally returned and the coroutine hit its first real await (the start hook) -- its
    gaps between the ticks it DID record stayed small throughout, hiding the whole stall. What
    actually reveals it is WHEN the ticker's first tick lands relative to a clock started before
    the call: blocked, that is ~1s later; free, it is near-immediate.
    """

    def _slow_create(*, blue: Path, execution_id: str) -> green_checkout.Green:
        time.sleep(1.0)  # real, deliberate -- runs in the thread asyncio.to_thread gives it
        work = tmp_path / "green-work" / execution_id
        (work / ".git").mkdir(parents=True)
        return green_checkout.Green(execution_id, work, tmp_path / "green-git" / execution_id, "deadbeef", blue)

    monkeypatch.setattr(green_checkout, "create_green", _slow_create)
    start, _calls = _fake_start(200, {"ok": True})
    app = {APP_PRAXIS_START_CODE_RUN: start}

    async def _run() -> list[float]:
        tick_times: list[float] = []
        clock_start = time.perf_counter()
        stop = asyncio.Event()

        async def ticker() -> None:
            while not stop.is_set():
                await asyncio.sleep(0.02)
                tick_times.append(time.perf_counter() - clock_start)

        ticker_task = asyncio.ensure_future(ticker())
        await thomas_project.start_thomas_project(app, request="fix", settings={}, port=8898)
        stop.set()
        await ticker_task
        return tick_times

    tick_times = asyncio.run(_run())

    assert tick_times  # the ticker got at least one turn
    assert tick_times[0] < 0.2  # ...promptly, not ~1s late behind a frozen loop


# ── settle_if_finished ──


def test_settle_if_finished_settles_a_completed_run_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settle_calls: list[tuple[Any, ...]] = []

    def _fake_settle(
        execution_id: str, *, promote: bool, summary: str, chat: str, checked: str = "", patch: str | None = None
    ) -> Path:
        settle_calls.append((execution_id, promote, summary, chat))
        return tmp_path / "inbox" / f"self-{execution_id}"

    monkeypatch.setattr(green_handoff, "settle", _fake_settle)

    root, catalog_root = tmp_path / "project", tmp_path / "catalog"
    conv = forge_code_store.new_conversation(root, title="fix thing", thomas_project={"execution_id": "thomas-abc123"})
    cid = conv["id"]
    forge_code_store.append_agent_turn(root, cid, **_agent_turn())

    submission = thomas_project.settle_if_finished(root, catalog_root, cid)

    assert submission == tmp_path / "inbox" / "self-thomas-abc123"
    assert len(settle_calls) == 1
    execution_id, promote, _summary, chat = settle_calls[0]
    assert (execution_id, promote, chat) == ("thomas-abc123", True, cid)

    # I1: the STAMP lands on the surviving (catalog) copy, not the original root.
    stored = forge_code_store.load_conversation(catalog_root, cid)
    assert stored is not None
    assert stored["thomas_project"]["settled_at"]

    # Never settles twice, even if asked again -- reading from wherever it now lives.
    assert thomas_project.settle_if_finished(catalog_root, catalog_root, cid) is None
    assert len(settle_calls) == 1


def test_settle_if_finished_does_nothing_for_a_failed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settle_calls: list[Any] = []
    monkeypatch.setattr(green_handoff, "settle", lambda *a, **k: settle_calls.append((a, k)))

    root, catalog_root = tmp_path / "project", tmp_path / "catalog"
    conv = forge_code_store.new_conversation(root, title="fix thing", thomas_project={"execution_id": "thomas-xyz"})
    cid = conv["id"]
    forge_code_store.append_agent_turn(
        root, cid, **_agent_turn(ok=False, outcome="failed", reason="crashed", changed_files=[])
    )

    assert thomas_project.settle_if_finished(root, catalog_root, cid) is None
    assert settle_calls == []


def test_settle_if_finished_ignores_a_conversation_with_no_thomas_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settle_calls: list[Any] = []
    monkeypatch.setattr(green_handoff, "settle", lambda *a, **k: settle_calls.append((a, k)))

    root, catalog_root = tmp_path / "project", tmp_path / "catalog"
    conv = forge_code_store.new_conversation(root, title="ordinary build")
    cid = conv["id"]
    forge_code_store.append_agent_turn(root, cid, **_agent_turn())

    assert thomas_project.settle_if_finished(root, catalog_root, cid) is None
    assert settle_calls == []


# ── I1: settling must not lose the conversation that lived inside the green ──


def test_settle_if_finished_preserves_the_conversation_when_settle_really_deletes_the_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviewer's finding: green_handoff.settle deletes green.work -- every turn with it.

    A fake settle here does what the real one does: it removes `root` for real
    before returning. `settle_if_finished` must have copied the conversation
    to `catalog_root` BEFORE that call, or there is nothing left to stamp.
    """
    root, catalog_root = tmp_path / "green-work", tmp_path / "catalog"
    conv = forge_code_store.new_conversation(root, title="fix thing", thomas_project={"execution_id": "thomas-real1"})
    cid = conv["id"]
    forge_code_store.append_agent_turn(root, cid, **_agent_turn())

    def _settle_and_really_delete_the_green(
        execution_id: str, *, promote: bool, summary: str, chat: str, checked: str = "", patch: str | None = None
    ) -> Path:
        shutil.rmtree(root)  # what remove_green actually does at the end of a real settle
        return tmp_path / "inbox" / f"self-{execution_id}"

    monkeypatch.setattr(green_handoff, "settle", _settle_and_really_delete_the_green)
    monkeypatch.setattr(green_checkout, "find_green", lambda execution_id: None)  # confirms it is really gone

    submission = thomas_project.settle_if_finished(root, catalog_root, cid)

    assert submission == tmp_path / "inbox" / "self-thomas-real1"
    assert not root.exists()  # the green really is gone
    preserved = forge_code_store.load_conversation(catalog_root, cid)
    assert preserved is not None
    assert preserved["turns"]  # the turns, not just the shell, survived
    assert preserved["thomas_project"]["settled_at"]


def test_settle_if_finished_does_not_stamp_when_the_hand_off_kept_the_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I1: stamp only when the green is actually gone; a kept green is a recorded issue, not a stamp."""
    root, catalog_root = tmp_path / "green-work", tmp_path / "catalog"
    conv = forge_code_store.new_conversation(root, title="fix thing", thomas_project={"execution_id": "thomas-kept"})
    cid = conv["id"]
    forge_code_store.append_agent_turn(root, cid, **_agent_turn())

    monkeypatch.setattr(green_handoff, "settle", lambda *a, **k: None)  # the hand-off failed; green untouched
    monkeypatch.setattr(green_checkout, "find_green", lambda execution_id: object())  # still there
    monkeypatch.setattr(green_checkout, "green_patch", lambda green: "")  # settle freezes the patch first (da23f510)
    issues: list[dict[str, Any]] = []
    monkeypatch.setattr(thomas_project, "record_issue", lambda **kwargs: issues.append(kwargs))

    submission = thomas_project.settle_if_finished(root, catalog_root, cid)

    assert submission is None
    preserved = forge_code_store.load_conversation(catalog_root, cid)
    assert preserved is not None  # still copied out, so a later retry has it
    assert "settled_at" not in preserved["thomas_project"]
    assert len(issues) == 1
    assert issues[0]["kind"] == "settle_kept_green"


# ── Fix round 2, Case G/H: the registry row, and a late remove_green failure ──


def test_settle_if_finished_leaves_the_registry_row_when_the_hand_off_genuinely_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case G: forgetting the row here strands the still-live conversation at `root`, reachable
    only through the row -- and leaves the green to the 24h sweep instead of a retried settle."""
    root, catalog_root = tmp_path / "green-work", tmp_path / "catalog"
    conv = forge_code_store.new_conversation(root, title="fix thing", thomas_project={"execution_id": "thomas-caseg"})
    cid = conv["id"]
    forge_code_store.append_agent_turn(root, cid, **_agent_turn())
    forge_code_projects.bind_conversation(catalog_root, cid, root, settings={}, allow_without_history=True)

    monkeypatch.setattr(green_handoff, "settle", lambda *a, **k: None)  # the hand-off failed
    monkeypatch.setattr(green_checkout, "find_green", lambda execution_id: object())  # green kept
    monkeypatch.setattr(green_checkout, "green_patch", lambda green: "")  # settle freezes the patch first (da23f510)
    monkeypatch.setattr(thomas_project, "record_issue", lambda **kwargs: None)

    submission = thomas_project.settle_if_finished(root, catalog_root, cid)

    assert submission is None
    row = forge_code_projects.conversation_metadata(catalog_root, cid)
    assert row is not None
    assert row["project_root"] == str(root)  # a later read or retry still finds the live conversation


def test_settle_if_finished_stamps_and_notes_a_kept_green_after_a_real_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case H: green_handoff.settle can write a real submission and still fail to remove_green
    afterward (Windows briefly holding a folder a process just released) -- the card already
    went out, so this is settled and noted, never reported as a failed hand-off."""
    root, catalog_root = tmp_path / "green-work", tmp_path / "catalog"
    conv = forge_code_store.new_conversation(root, title="fix thing", thomas_project={"execution_id": "thomas-caseh"})
    cid = conv["id"]
    forge_code_store.append_agent_turn(root, cid, **_agent_turn())

    def _settle_writes_but_leaves_the_green(
        execution_id: str, *, promote: bool, summary: str, chat: str, checked: str = "", patch: str | None = None
    ) -> Path:
        # A real green_handoff.settle already caught remove_green's own
        # OSError internally and logged it; it still returns the submission.
        return tmp_path / "inbox" / f"self-{execution_id}"

    monkeypatch.setattr(green_handoff, "settle", _settle_writes_but_leaves_the_green)
    monkeypatch.setattr(green_checkout, "find_green", lambda execution_id: object())  # still there
    monkeypatch.setattr(green_checkout, "green_patch", lambda green: "")  # settle freezes the patch first (da23f510)
    issues: list[dict[str, Any]] = []
    monkeypatch.setattr(thomas_project, "record_issue", lambda **kwargs: issues.append(kwargs))

    submission = thomas_project.settle_if_finished(root, catalog_root, cid)

    assert submission == tmp_path / "inbox" / "self-thomas-caseh"
    stored = forge_code_store.load_conversation(catalog_root, cid)
    assert stored is not None
    assert stored["thomas_project"]["settled_at"]  # stamped -- the card already went out
    assert len(issues) == 1
    assert issues[0]["kind"] == "settle_green_kept_after_submission"


# ── New Important: the hand-off summary must name the change, not the done check's own reply ──


def test_a_done_settle_names_the_change_and_never_says_without_changing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """self_change_promoter.py builds the landed commit's subject from this summary's first line."""
    summaries: list[str] = []

    def _fake_settle(
        execution_id: str, *, promote: bool, summary: str, chat: str, checked: str = "", patch: str | None = None
    ) -> Path:
        summaries.append(summary)
        return tmp_path / "inbox" / f"self-{execution_id}"

    monkeypatch.setattr(green_handoff, "settle", _fake_settle)

    root, catalog_root = tmp_path / "green-work", tmp_path / "catalog"
    conv = forge_code_store.new_conversation(root, title="fix the thing", thomas_project={"execution_id": "thomas-sum"})
    cid = conv["id"]
    # The real work: a completed pass that actually changed files.
    forge_code_store.append_agent_turn(
        root, cid, **_agent_turn(changed_files=["readme.md", "app.py"], reason="2 file(s) changed")
    )
    # The done check's own final turn -- Autopilot's review, replying
    # without touching anything further. This is `last_agent` by the time
    # settle_if_finished runs, and must not be what the summary is built from.
    forge_code_store.append_agent_turn(
        root,
        cid,
        **_agent_turn(outcome="conversation", changed_files=[], reason="Thomas replied without changing files"),
    )

    thomas_project.settle_if_finished(root, catalog_root, cid)

    assert len(summaries) == 1
    assert "without changing files" not in summaries[0]
    assert "readme.md" in summaries[0]
    assert "app.py" in summaries[0]


# ── Ruling H (and its minor): a real turn, or a changed decision, stands a retry down ──


def _autopilot_failed_conversation(tmp_path: Path) -> tuple[Path, Path, str]:
    """A real Autopilot conversation, bound the way the app binds one, with one failed turn."""
    catalog_root, project_root = tmp_path / "ap-catalog", tmp_path / "ap-project"
    catalog_root.mkdir(parents=True, exist_ok=True)
    project_root.mkdir(parents=True, exist_ok=True)
    draft = forge_code_store.draft_conversation(title="fix thomas")
    cid = draft["id"]
    forge_code_store.persist_draft_with_user_turn(project_root, draft, "fix thomas")
    forge_code_store.append_agent_turn(
        project_root,
        cid,
        model="claude-cli",
        transcript="...TypeError: sprite is undefined",
        changed_files=["game.js"],
        returncode=1,
        ok=False,
        noop=False,
        reason="the run crashed before finishing",
        outcome="failed",
        report={"open_risks": []},
    )
    capability_report = ForgeCodeSettings.from_payload({"autonomy_level": ap.AUTOPILOT}).capability_report()
    forge_code_projects.bind_conversation(
        catalog_root, cid, project_root, settings=capability_report, allow_without_history=True
    )
    return catalog_root, project_root, cid


def test_a_real_user_turn_during_a_busy_retry_stops_the_continuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user turn added between two 409s means no continuation is started (Ruling H)."""
    calls: list[dict[str, Any]] = []
    responses = iter([(409, {"code": "agent_already_running"}), (200, {"ok": True})])

    async def fake_start(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        calls.append(body)
        return next(responses)

    catalog_root, project_root, cid = _autopilot_failed_conversation(tmp_path)

    async def sleep_while_you_type(_seconds: float) -> None:
        # Stands in for the wall-clock retry wait, during which a real
        # message from you arrives -- not one Autopilot wrote itself.
        forge_code_store.append_user_turn(project_root, cid, "actually, stop and let me look at this")

    # Fix round 1 minor: patch the module's own retry-sleep alias, not the
    # process-wide asyncio.sleep every other coroutine on the loop also awaits.
    monkeypatch.setattr(ap, "_sleep", sleep_while_you_type)
    monkeypatch.setattr(ap, "record_issue", lambda **kwargs: pytest.fail("a stand-down is not a refusal"))
    app = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = asyncio.run(ap.continue_after_turn(app, project_root, catalog_root, cid))

    assert decision.action == "continue"  # the ORIGINAL read, before your message arrived
    assert len(calls) == 1  # never retried once a real turn showed up


def test_a_changed_decision_with_no_new_user_turn_also_stops_the_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Minor: stand down when the fresh decision differs from the original, not only on a new user turn.

    No real user turn ever arrives here -- the wait records one more completed continuation run, so a reload
    answers `continue` with a message built from that newer run, where the original read carried the older one.
    There is no run limit to trip: the decision changed only because its evidence did.
    """
    calls: list[dict[str, Any]] = []
    responses = iter([(409, {"code": "agent_already_running"}), (200, {"ok": True})])

    async def fake_start(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        calls.append(body)
        return next(responses)

    catalog_root, project_root, cid = _autopilot_failed_conversation(tmp_path)
    # Eleven recorded continuation runs already -- the goal
    # (`autopilot_goal.goal_text`) leaves every one of these out, so
    # `original_goal` and `fresh_goal` end up identical; only the evidence differs.
    for _ in range(11):
        forge_code_store.append_user_turn(project_root, cid, ap.CONTINUATION_PREFIX + " ...")
        forge_code_store.append_agent_turn(
            project_root,
            cid,
            model="test",
            outcome="failed",
            reason="run ended",
            transcript='{"fc":"tool","name":"pytest"}',
            changed_files=[],
            returncode=1,
            ok=False,
            noop=False,
        )

    async def sleep_through_one_more_run(_seconds: float) -> None:
        forge_code_store.append_user_turn(project_root, cid, ap.CONTINUATION_PREFIX + " ...")
        forge_code_store.append_agent_turn(
            project_root,
            cid,
            model="test",
            outcome="failed",
            reason="a different crash",
            transcript='{"fc":"tool","name":"pytest"}',
            changed_files=[],
            returncode=1,
            ok=False,
            noop=False,
        )

    monkeypatch.setattr(ap, "_sleep", sleep_through_one_more_run)
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(ap, "record_issue", lambda **kwargs: recorded.append(kwargs))
    app = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = asyncio.run(ap.continue_after_turn(app, project_root, catalog_root, cid))

    assert decision.action == "continue"  # the ORIGINAL read
    assert len(calls) == 1  # stood down instead of retrying with a stale message


def test_a_changed_message_with_the_same_action_also_stops_the_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix round 2 minor: compare the WHOLE Decision, not just its action.

    Nobody sends a new user turn here. During the wait, a SECOND agent turn lands (as if a
    different path started and finished a run for this same conversation) -- a different
    failure, so `continuation_message` builds a different `.message` from it. The action stays
    "continue" both times; only the message goes stale. The old `fresh.action != decision.action`
    check could not see that and would have retried with the FIRST failure's evidence describing
    a crash that is no longer the current one.
    """
    calls: list[dict[str, Any]] = []
    responses = iter([(409, {"code": "agent_already_running"}), (200, {"ok": True})])

    async def fake_start(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        calls.append(body)
        return next(responses)

    catalog_root, project_root, cid = _autopilot_failed_conversation(tmp_path)

    async def sleep_while_another_run_lands(_seconds: float) -> None:
        forge_code_store.append_agent_turn(
            project_root,
            cid,
            model="claude-cli",
            transcript="a completely different crash",
            changed_files=[],
            returncode=3,
            ok=False,
            noop=False,
            reason="the run crashed before finishing -- a completely different failure",
            outcome="failed",
        )

    monkeypatch.setattr(ap, "_sleep", sleep_while_another_run_lands)
    monkeypatch.setattr(ap, "record_issue", lambda **kwargs: pytest.fail("a stand-down is not a refusal"))
    app = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = asyncio.run(ap.continue_after_turn(app, project_root, catalog_root, cid))

    assert decision.action == "continue"  # the ORIGINAL read, same action as the fresh one
    assert len(calls) == 1  # stood down anyway: the message underneath it had gone stale


# ── Fix round 2 minor: after_run's settle wires self_change_status.follow ──


def test_a_settled_submission_starts_self_change_status_follow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import thomas.server.self_change_status as self_change_status

    follow_calls: list[tuple[str, str]] = []

    async def _fake_follow(sid: str, chat: str, **kwargs: Any) -> str:
        follow_calls.append((sid, chat))
        return ""

    monkeypatch.setattr(self_change_status, "follow", _fake_follow)
    project_root, catalog_root = tmp_path / "green-work", tmp_path / "catalog"
    draft = forge_code_store.draft_conversation(
        title="change Thomas", thomas_project={"execution_id": "self-thomas-xyz"}
    )
    cid = draft["id"]
    forge_code_store.persist_draft_with_user_turn(project_root, draft, "change Thomas")
    forge_code_store.append_agent_turn(project_root, cid, **_agent_turn())
    forge_code_projects.bind_conversation(
        catalog_root,
        cid,
        project_root,
        settings=ForgeCodeSettings.from_payload({"autonomy_level": 3}).capability_report(),
        allow_without_history=True,
    )
    from thomas.server import hand_in_hold

    assert hand_in_hold.still_current(project_root, catalog_root, cid)
    submission_path = tmp_path / "inbox" / "self-thomas-xyz"
    settled: list[tuple[Path, Path, str, list[Any]]] = []

    def _fake_settle(root: Path, catalog: Path, conversation_id: str, *, expected_gen: list[Any]) -> Path:
        settled.append((root, catalog, conversation_id, expected_gen))
        return submission_path

    monkeypatch.setattr(ap.thomas_project, "settle_if_finished", _fake_settle)

    async def _run() -> None:
        await ap._settle_thomas_project(project_root, catalog_root, cid)
        for _ in range(10):  # let the fire-and-forget create_task actually run
            await asyncio.sleep(0)

    asyncio.run(_run())

    assert len(settled) == 1
    assert settled[0][:3] == (project_root, catalog_root, cid)
    assert settled[0][3]  # the booked finished turn is passed to settlement
    assert follow_calls == [("self-thomas-xyz", cid)]
