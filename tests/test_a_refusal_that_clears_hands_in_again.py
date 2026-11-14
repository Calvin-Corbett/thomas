"""A refusal that clears by itself hands the change in again, once the running copy's work in its files is committed.

On 2026-09-25 between 03:25 and 03:45 four finished hand-ins were refused within minutes of each other, each only
because the running copy had uncommitted work in a file the change touched, and that work was committed shortly after.
Nothing tried again: only a refusal because dev moved on went anywhere. Real here: the whole server app with its
loopback guard, git greens and a git running copy, the conversation store and registry, the settle, the verdict
follower and the listing. Stubbed: Build's start hook, and the promoter's inbox and verdicts (Task 3c's fixtures).
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from scripts.cage import self_change_checks

from thomas.core import user_questions
from thomas.core.user_questions import UserQuestionBook
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.notifications import delegation_hooks
from thomas.server import green_checkout, green_handoff, issue_ledger, precard, thomas_project
from thomas.server import self_change_status as scs
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.self_project_routes import read_projects, register_self_project_routes

ASK = "Make the Send button blue"
CLAUDE = {"model": "claude:opus", "model_id": "opus", "autonomy_level": 5, "file_access": "project"}


def _withdraw(w: SimpleNamespace, sid: str) -> None:
    (w.tmp / "processed").mkdir(exist_ok=True)
    shutil.move(str(w.tmp / "inbox" / sid), str(w.tmp / "processed" / sid))


def _verdict(w: SimpleNamespace, started: dict[str, Any], sid: str, status: str, detail: str) -> None:
    record = {
        "id": sid,
        "submission_id": sid,
        "execution_id": started["execution_id"],
        "status": status,
        "detail": detail,
        "conflicts": [],
        "ts": time.time(),
    }
    (w.outbox / f"{sid}.verdict.json").write_text(json.dumps(record), encoding="utf-8")


def _finish_and_hand_in(w: SimpleNamespace, started: dict[str, Any], rel: str) -> str:
    root, cid = Path(started["project_root"]), started["conversation_id"]
    (root / rel).write_text("the team's change\n", encoding="utf-8")
    forge_code_store.append_agent_turn(
        root,
        cid,
        model="claude",
        transcript="Done",
        changed_files=[rel],
        returncode=0,
        ok=True,
        noop=False,
        reason="1 file changed",
        outcome="completed",
    )
    result = thomas_project.settle_if_finished(root, w.catalog, cid)
    assert result is not None
    return result.name


@pytest.fixture(autouse=True)
def isolated_persistence(tmp_path, monkeypatch):
    from thomas.core import persistence
    from thomas.server import keeper_guard

    state, reports = tmp_path / "state.json", tmp_path / "reports"
    monkeypatch.setattr(persistence, "_DEFAULT_STATE_FILE", state)
    monkeypatch.setattr(persistence, "_DEFAULT_REPORT_DIR", reports)
    monkeypatch.setattr(persistence, "_engine", persistence.PersistenceEngine(state, report_dir=reports))
    monkeypatch.setenv(keeper_guard.DROP_ENV, str(tmp_path / "keeper-drop"))
    monkeypatch.setattr(keeper_guard, "RESERVE_BYTES", 0)


REPO = Path(__file__).resolve().parents[1]
URL = "/api/self/projects/{}/hand-in-again"
SEND_BACK = "/api/self/projects/{}/send-back"
# Three of the four refusals of 2026-09-25, word for word from the promoter's outbox, and the files each names.
REAL = {
    "the running copy has uncommitted work in thomas/server/app_routes_init.py": ["thomas/server/app_routes_init.py"],
    "the running copy has uncommitted work in thomas/server/chat_self_project.py, thomas/server/thomas_project.py": [
        "thomas/server/chat_self_project.py",
        "thomas/server/thomas_project.py",
    ],
    "the running copy has uncommitted work in tests/conftest.py, thomas/server/routes/evolve_agent_autopilot.py": [
        "tests/conftest.py",
        "thomas/server/routes/evolve_agent_autopilot.py",
    ],
}
DIRTY = "the running copy has uncommitted work in README.md"
MOVED = "the change no longer applies to dev: Applied patch to 'AGENTS.md' with conflicts."


def _git(cwd: Path, *args: str) -> str:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args]
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _blue(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    for args in (("init", "-q", "-b", "dev"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        _git(root, *args)
    return root


async def _eventually(check, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while not check() and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    return check()


@pytest.fixture(scope="module")
def blue_seed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _blue(
        tmp_path_factory.mktemp("refusal-seed"),
        {"README.md": "blue\n", "AGENTS.md": "agents\n", "CHANGELOG.md": "# log\n"},
    )


@pytest.fixture
def fast(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blue_seed: Path) -> SimpleNamespace:
    # Keep real git hand-ins, without cloning the whole Thomas source checkout.
    folders = {name: tmp_path / name for name in ("greens", "catalog", "board", "outbox")}
    for folder in folders.values():
        folder.mkdir()
    for name in ("work", "git"):
        (folders["greens"] / name).mkdir()
    w = SimpleNamespace(tmp=tmp_path, starts=[], **folders)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(w.greens))
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(w.board))
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: w.catalog)
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: tmp_path / "inbox")
    monkeypatch.setattr(green_handoff, "_end_processes", lambda green: None)
    monkeypatch.setattr(scs, "outbox_dir", lambda: w.outbox)

    async def hook(body, *, port):
        w.starts.append({**body, "port": port})
        return 200, {"ok": True, "conversation_id": body["conversation_id"], "run_id": "test-run"}

    w.hook = hook
    blue = w.tmp / "blue"
    shutil.copytree(blue_seed, blue)
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: blue)
    # Other projects' patch summaries are unrelated to hand-in retry behavior.
    monkeypatch.setattr(green_handoff, "sibling_changes", lambda execution_id: {})
    monkeypatch.setattr(green_handoff, "size_problems", lambda execution_id: [])
    monkeypatch.setattr(thomas_project, "_patch_files", lambda execution_id: ["CHANGELOG.md"])
    # These greens have not integrated a newer dev tip.
    monkeypatch.setattr(green_checkout, "_dev_taken_in", lambda green: "")
    monkeypatch.setattr(green_handoff, "sibling_changes", lambda _eid: {})
    book = UserQuestionBook()
    monkeypatch.setattr(user_questions, "question_book", lambda: book)
    monkeypatch.setattr(delegation_hooks, "emit_delegation_notification", lambda *a, **k: None)  # no desktop toast
    monkeypatch.setattr(scs, "follow", functools.partial(scs.follow, poll_s=0.01))
    monkeypatch.setattr(scs, "HAND_IN_POLL_S", 0.01)
    monkeypatch.setattr(scs, "_WAITS", {})

    def checked(eid: str) -> precard.Checked:
        patch = green_checkout.green_patch(green_checkout.find_green(eid))
        return precard.Checked(
            state=precard.PASSED,
            line="Test fixture supplies the precard result; no checks run.",
            patch=patch,
            patch_sha256=precard.patch_sha256(patch),
        )

    monkeypatch.setattr(precard, "check_for_hand_in", checked)
    w.issues = []
    monkeypatch.setattr(issue_ledger, "record_issue", lambda **kw: w.issues.append(kw))
    w.blue, w.app = w.tmp / "blue", {APP_LOCAL_PORT: 8898, APP_PRAXIS_START_CODE_RUN: w.hook}
    return w


async def _client(w: SimpleNamespace) -> TestClient:
    app = web.Application()
    app[APP_PRAXIS_START_CODE_RUN] = w.hook
    register_self_project_routes(app, require_loopback=lambda request: None)
    client = TestClient(TestServer(app, host="127.0.0.1"))
    await client.start_server()
    return client


async def _begun(w: SimpleNamespace) -> dict[str, Any]:  # started the way the route starts one
    return await thomas_project.start_thomas_project(w.app, request=ASK, settings=CLAUDE, port=8898)


async def _refused(w: SimpleNamespace, detail: str = DIRTY, status: str = "refused") -> tuple[dict, str]:
    """A project changes README.md and is handed in, and the promoter answers it and moves it out of its inbox."""
    started = await _begun(w)
    sid = await asyncio.to_thread(_finish_and_hand_in, w, started, "README.md")
    _verdict(w, started, sid, status, detail)
    _withdraw(w, sid)
    return started, sid


def _rows(w: SimpleNamespace) -> dict[str, dict[str, Any]]:
    # These checks inspect refusal state, not sibling worktree diffs.
    return {row["conversation_id"]: row for row in read_projects(w.catalog, changed_files=False)["projects"]}


def _edit(w: SimpleNamespace, text: str = "another agent's edit\n") -> None:  # uncommitted work in the running copy
    (w.blue / "README.md").write_text(text, encoding="utf-8")


def _follow(w: SimpleNamespace, started: dict[str, Any], sid: str) -> asyncio.Task:
    work, cid = Path(started["project_root"]), started["conversation_id"]
    return asyncio.create_task(ap._follow_verdict(w.app, work, w.catalog, cid, sid, cid))


def _repairs(started: dict[str, Any]) -> int:
    conversation = forge_code_store.load_conversation(Path(started["project_root"]), started["conversation_id"])
    return thomas_project.repairs_done((conversation or {}).get("thomas_project") or {})


def test_the_refusal_is_recognised_with_its_files_and_no_other_is() -> None:
    for detail, files in REAL.items():
        assert scs.uncommitted_files({"status": "refused", "detail": detail}) == files
    others = [
        {"status": "refused", "detail": MOVED},
        {"status": "refused", "detail": "the change is already on dev"},
        {"status": "declined", "detail": DIRTY},
        {"status": "landed", "detail": ""},
        {},
        None,
    ]
    assert [scs.uncommitted_files(verdict) for verdict in others] == [[]] * len(others)
    assert not scs.dev_moved({"status": "refused", "detail": DIRTY})
    # The promoter's refusal is self_change_checks.running_copy_refusal (2026-10-09), run before the card and again
    # right after your answer.
    checks = (REPO / "scripts" / "cage" / "self_change_checks.py").read_text(encoding="utf-8")
    assert f'return "{scs.RUNNING_COPY_DIRTY}" + ", ".join(dirty' in checks, "the promoter's words are the contract"


def test_clean_is_the_promoters_own_test_read_without_writing_the_index(fast: SimpleNamespace) -> None:
    eid, blue, index = asyncio.run(_begun(fast))["execution_id"], fast.blue, fast.blue / ".git" / "index"
    files = ["README.md", "AGENTS.md", "docs/new.md"]  # docs/new.md: a file the change adds
    changes_by_tip: dict[str, list[tuple[str, str]]] = {}

    def both() -> tuple[list[str] | None, list[str]]:
        before = index.read_bytes()
        ours = green_handoff.uncommitted_in_running_copy(eid, files)
        assert index.read_bytes() == before, "read without writing the index other agents and the promoter use"
        tip = _git(blue, "rev-parse", "dev")
        if tip not in changes_by_tip:
            changes_by_tip[tip] = [("M" if self_change_checks.blob(blue, tip, path) else "A", path) for path in files]
        return ours, self_change_checks.blue_dirty(blue, tip, changes_by_tip[tip])

    seen = [both()]
    later = time.time() + 5
    os.utime(blue / "README.md", (later, later))  # stat-dirty, the same content: not work
    seen.append(both())
    _edit(fast)
    seen.append(both())
    _git(blue, "add", "README.md")
    (blue / ".git" / "index.lock").write_text("", encoding="utf-8")  # another agent holds the index
    seen.append(both())
    (blue / ".git" / "index.lock").unlink()
    (blue / "docs").mkdir()
    (blue / "docs" / "new.md").write_text("added\n", encoding="utf-8")  # the file the change adds is already there
    seen.append(both())
    _git(blue, "add", "-A")
    _git(blue, "commit", "-q", "-m", "their work, committed")
    seen.append(both())
    expected = [[], [], ["README.md"], ["README.md"], ["README.md", "docs/new.md"], []]
    assert [ours for ours, _ in seen] == expected
    assert [theirs for _, theirs in seen] == expected, "the promoter decides the same"


def test_a_refused_hand_in_waits_while_dirty_then_hands_the_same_green_in_once(
    fast: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[Any] = []
    real = green_handoff.uncommitted_in_running_copy
    monkeypatch.setattr(green_handoff, "uncommitted_in_running_copy", lambda *a: reads.append(real(*a)) or reads[-1])

    async def scenario() -> tuple[Any, ...]:
        started, sid = await _refused(fast)
        cid = started["conversation_id"]
        bound = thomas_project.settled_record(fast.catalog, cid)["bound_settings"]
        _edit(fast)
        follow = _follow(fast, started, sid)
        await _eventually(lambda: len(reads) >= 3)
        waiting, inbox = _rows(fast)[cid], sorted(p.name for p in (fast.tmp / "inbox").iterdir())
        _git(fast.blue, "commit", "-q", "-am", "their work, committed")
        await asyncio.wait_for(asyncio.shield(follow), timeout=60)
        handed, record = _rows(fast)[cid], thomas_project.settled_record(fast.catalog, cid)
        work, git_dir = green_checkout._paths(started["execution_id"])
        removing, inside = threading.Event(), []
        real_remove, real_run = green_checkout.remove_green, green_checkout._run

        def remove_green(green: green_checkout.Green, *, attempts: int = 3) -> None:
            if green.execution_id != started["execution_id"]:
                return real_remove(green, attempts=attempts)
            removing.set()
            try:
                time.sleep(0.5)
                return real_remove(green, attempts=attempts)
            finally:
                removing.clear()

        def run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
            if removing.is_set() and Path(cwd) == work:
                inside.append(args)
            return real_run(args, cwd=cwd)

        monkeypatch.setattr(green_checkout, "remove_green", remove_green)
        monkeypatch.setattr(green_checkout, "_run", run)
        _verdict(fast, started, f"{sid}-2", "landed", "on dev and in the running copy")
        # Git started inside the green holds its work folder, which Windows cannot delete.
        gone = await _eventually(lambda: not work.exists() and not git_dir.exists())
        gone = gone and green_checkout.find_green(started["execution_id"]) is None
        return started, sid, bound, waiting, inbox, handed, record, gone, inside

    started, sid, bound, waiting, inbox, handed, record, gone, inside = asyncio.run(scenario())
    again = f"{sid}-2"
    assert reads[:-1] and all(read == ["README.md"] for read in reads[:-1]) and reads[-1] == []
    assert inbox == [], "never handed in while the running copy still had the work"
    assert waiting["state"] == "waiting for the running copy" and "README.md" in waiting["detail"]
    assert waiting["last_verdict"]["detail"] == DIRTY and waiting["submission"] == sid
    processed, inbox_now = fast.tmp / "processed" / sid, fast.tmp / "inbox" / again
    assert (inbox_now / "change.patch").read_bytes() == (processed / "change.patch").read_bytes(), "the same green"
    assert record["submission"] == again and record["bound_settings"] == bound and bound
    assert (handed["state"], handed["submission"]) == ("awaiting verdict", again) and again in handed["detail"]
    assert (handed["last_verdict"]["submission"], handed["last_verdict"]["detail"]) == (sid, DIRTY)
    assert _repairs(started) == 0 and len(fast.starts) == 1, "no repair round, no Build run"
    assert inside == [], "no git may start inside the green while it is being removed: Windows then cannot delete it"
    assert gone, "the new hand-in's verdict is followed as usual: landed removes the green and both folders are deleted"


def test_a_second_refusal_waits_within_the_same_bound_then_gives_up_saying_why(
    fast: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(scs, "_clock", lambda: clock[0])

    async def scenario() -> tuple[Any, ...]:
        started, sid = await _refused(fast)
        cid, again = started["conversation_id"], f"{sid}-2"
        await _follow(fast, started, sid)  # clean already: handed in again at once
        _edit(fast, "more work\n")
        _verdict(fast, started, again, "refused", DIRTY)  # refused again, for the same reason
        _withdraw(fast, again)
        await _eventually(lambda: getattr(scs.hand_in_wait(cid), "sid", "") == again)
        since = scs.hand_in_wait(cid).since
        clock[0] += scs.HAND_IN_WAIT_S
        await _eventually(lambda: scs.hand_in_wait(cid).state == "gave up")
        return sid, cid, again, since, scs.hand_in_wait(cid).why, _rows(fast)[cid]

    sid, cid, again, since, why, row = asyncio.run(scenario())
    assert since == 1000.0, "a refusal of its own hand-in again waits within the first wait's bound"
    assert "6 hours" in why and "README.md" in why and "not handed in again" in why and URL.format(cid) in why
    assert (row["state"], row["detail"], row["submission"]) == ("refused", why, again)
    assert [issue["kind"] for issue in fast.issues] == ["hand_in_again_gave_up"]
    assert not (fast.tmp / "inbox" / f"{sid}-3").exists(), "nothing handed in after giving up"


def test_hand_in_again_says_why_it_cannot(fast: SimpleNamespace) -> None:
    async def scenario() -> list[tuple[int, str]]:
        client = await _client(fast)
        try:
            started = await _begun(fast)
            sid = await asyncio.to_thread(_finish_and_hand_in, fast, started, "README.md")
            cid = started["conversation_id"]

            async def answer(project_id: str = cid) -> tuple[int, str]:
                response = await client.post(URL.format(project_id))
                return response.status, (await response.json())["error"]

            answers = [await answer("fc_20260925T000000_abcdef"), await answer("-x"), await answer()]
            _withdraw(fast, sid)
            _verdict(fast, started, sid, "refused", MOVED)
            answers.append(await answer())
            _verdict(fast, started, sid, "landed", "")
            answers.append(await answer())
            _verdict(fast, started, sid, "refused", DIRTY)
            _edit(fast)
            dirty = await answer()
            green_checkout.remove_green(green_checkout.find_green(started["execution_id"]))
            return [*answers, await answer(), dirty]
        finally:
            await client.close()

    answers = asyncio.run(scenario())
    assert [status for status, _ in answers] == [404, 400, 409, 409, 409, 409, 409], answers
    assert "promoter's inbox" in answers[2][1]
    assert "dev moved on" in answers[3][1] and "send-back" in answers[3][1]
    assert "landed" in answers[4][1]
    assert "green" in answers[5][1] and "gone" in answers[5][1]
    assert "uncommitted work in README.md" in answers[6][1] and "commit" in answers[6][1]
    assert len(fast.starts) == 1 and not [p for p in (fast.tmp / "inbox").iterdir() if p.name.endswith("-2")]


def test_hand_in_again_answers_at_once_and_hands_in_after_its_check(
    fast: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 4 of 2026-09-25: the route ran the whole check inside the request, holding the lock send-back shares.

    The check is held open here, so what the route and the listing say WHILE it runs can be read."""
    from thomas.server import precard

    release, real = threading.Event(), precard.check_for_hand_in

    def held_check(execution_id: str) -> Any:
        assert release.wait(30), "the test never let the check finish"
        return real(execution_id)

    async def scenario() -> tuple[Any, ...]:
        client = await _client(fast)
        try:
            started, sid = await _refused(fast)  # refused, and no waiter: as after a restart
            monkeypatch.setattr(precard, "check_for_hand_in", held_check)  # held from the hand-in again on
            cid = started["conversation_id"]
            _edit(fast)
            orphan = _rows(fast)[cid]
            still = await client.post(URL.format(cid))
            _git(fast.blue, "commit", "-q", "-am", "their work, committed")
            done = await client.post(URL.format(cid))  # answered while the check is still held
            checking = _rows(fast)[cid]
            twice = await client.post(URL.format(cid))
            back = await client.post(SEND_BACK.format(cid), json={"findings": "a test fails"})
            answers = [(r.status, await r.json()) for r in (still, done, twice, back)]
            release.set()
            await _eventually(lambda: (fast.tmp / "inbox" / f"{sid}-2").is_dir())
            await _eventually(lambda: not scs.being_handed_in(cid))
            third = await client.post(URL.format(cid))
            answers.append((third.status, await third.json()))
            return started, sid, orphan, checking, answers, _rows(fast)[cid]
        finally:
            release.set()
            await client.close()

    started, sid, orphan, checking, answers, row = asyncio.run(scenario())
    (still, dirty), (done, answer), (twice, again), (back, held), (third, out) = answers
    assert orphan["state"] == "refused" and "nothing is waiting" in orphan["detail"]
    assert URL.format(started["conversation_id"]) in orphan["detail"]
    assert still == 409 and "README.md" in dirty["error"]
    assert (done, answer) == (202, {"ok": True, "conversation_id": started["conversation_id"],
                                    "execution_id": started["execution_id"], "refused": sid,
                                    "state": "checking"})  # fmt: skip
    assert checking["state"] == "checking" and "being checked" in checking["detail"]
    assert twice == 409 and "already being checked" in again["error"], "a second click never hands it in twice"
    assert back == 409 and "being checked" in held["error"], "send-back waits for the hand-in, not for a lock"
    assert third == 409 and "promoter's inbox" in out["error"]
    assert (row["state"], row["submission"], row["last_verdict"]["submission"]) == ("awaiting verdict", f"{sid}-2", sid)
    assert _repairs(started) == 0 and len(fast.starts) == 1
