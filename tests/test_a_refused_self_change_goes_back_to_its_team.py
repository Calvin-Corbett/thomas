"""A self-change the promoter refuses because dev moved goes back to its team, in the same green.

You asked that Autopilot "shouldnt stop until it ha a finoisherfd product it deems good failures will happena nd
he must fix them and continue". On 2026-09-24 two finished Thomas projects were refused after their greens had been
deleted, and a person rebased them. Real here: git greens, the conversation store and registry, the chat's task
records, the settle, Autopilot and the promoter. Stubbed: Build's start hook, and the promoter's verdict files.
"""

from __future__ import annotations

import asyncio
import functools
import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts.cage import self_change_promoter as sp

from thomas.core import task_bot_runtime, user_questions
from thomas.core.user_questions import UserQuestionBook
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.notifications import delegation_hooks
from thomas.server import chat_self_project, green_checkout, green_handoff, self_change_status, thomas_project
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.tools import cage_shell, trusted_card

ASK = "Make the Send button blue"
# The detail of self-thomas-a76cea17759f.verdict.json, as the promoter wrote it on 2026-09-24.
MOVED = (
    "the change no longer applies to dev: Applied patch to 'CHANGELOG.md' with conflicts.\n"
    "Applied patch to 'tests/test_agent_continuation_anchor.py' cleanly.\n"
    "Applied patch to 'tests/test_chat_mode_contract.py' cleanly.\nFalling back to direct application...\n"
    "Applied patch to 'tests/test_stopping_a_run_refreshes_the_work_it_leaves_behind.py' c"
)


def _git(cwd: Path, *args: str) -> str:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args]
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _blue(root: Path, files: dict[str, str]) -> Path:
    """A stand-in for Thomas's own source checkout, on a branch called dev like the real one."""
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    for args in (("init", "-q", "-b", "dev"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        _git(root, *args)
    return root


def _hook(w: SimpleNamespace):
    """Build's start route as a Thomas project sees it: a settled project is refused; else the message is a turn."""

    async def start(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        w.starts.append(dict(body))
        cid = body["conversation_id"]
        if ((forge_code_store.load_conversation(w.catalog, cid) or {}).get("thomas_project") or {}).get("settled_at"):
            return 409, {"ok": False, "code": "project_is_thomas_source", "error": "project_is_thomas_source"}
        row = forge_code_projects.conversation_metadata(w.catalog, cid) or {}
        forge_code_store.append_user_turn(Path(row.get("project_root") or body["project_root"]), cid, body["message"])
        requested = {"requested": {"autonomy_level": body.get("autonomy_level")}}
        forge_code_projects.update_conversation_settings(w.catalog, cid, requested)
        return 200, {"ok": True, "conversation_id": cid, "run_id": f"run-{len(w.starts)}"}

    return start


@pytest.fixture
def w(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    blue = _blue(tmp_path / "blue", {"README.md": "blue\n", "AGENTS.md": "agents\n", "CHANGELOG.md": "# log\n"})
    greens, catalog, board, outbox = (tmp_path / name for name in ("green", "catalog", "board", "outbox"))
    for folder in (greens / "work", greens / "git", catalog, board, outbox):  # a green root that exists gets no ACLs
        folder.mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(greens))
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(board))  # where the chat's task records live
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: blue)
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: catalog)
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: tmp_path / "inbox")
    monkeypatch.setattr(green_handoff, "_end_processes", lambda green: None)  # no cage runner in a test
    monkeypatch.setattr(self_change_status, "outbox_dir", lambda: outbox)
    monkeypatch.setattr(delegation_hooks, "emit_delegation_notification", lambda *a, **k: None)  # no desktop toast
    book = UserQuestionBook()
    monkeypatch.setattr(user_questions, "question_book", lambda: book)
    monkeypatch.setattr(chat_self_project, "_POLL_S", 0.01)
    monkeypatch.setattr(self_change_status, "follow", functools.partial(self_change_status.follow, poll_s=0.01))
    world = SimpleNamespace(blue=blue, greens=greens, catalog=catalog, board=board, outbox=outbox, book=book)
    world.starts, world.app = [], {APP_LOCAL_PORT: 8898}
    world.app[APP_PRAXIS_START_CODE_RUN] = _hook(world)
    return world


def _finish(root: Path, cid: str, *, files: dict[str, str] | None = None, reply: str = "") -> None:  # a run ends
    for rel, text in (files or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    changed = list(files or {})
    forge_code_store.append_agent_turn(
        root, cid, model="gpt", transcript=json.dumps({"fc": "final", "text": reply}) if reply else "",
        changed_files=changed, returncode=0, ok=True, noop=False,
        reason=f"{len(changed)} file(s) changed" if changed else "Thomas replied without changing files",
        outcome="completed" if changed else "conversation",
    )  # fmt: skip


async def _to_done(w: SimpleNamespace, root: Path, cid: str, files: dict[str, str]) -> None:  # a pass, done, settle
    # Since 2026-11-13 a finished pass is done at once: no done-check round between the pass and the hand-in.
    _finish(root, cid, files=files, reply="DONE: the checks pass.\nTITLE: The Send button is blue")
    assert (await ap.after_run(w.app, root, w.catalog, cid)).action == "done"


def _verdict(w: SimpleNamespace, cid: str, execution_id: str, status: str, detail: str) -> None:  # real shape
    sid = str((thomas_project.settled_record(w.catalog, cid) or {}).get("submission") or "")
    record = {"id": sid, "chat": "", "execution_id": execution_id, "submission_id": sid, "status": status,
              "detail": detail, "commit_sha": "", "files": [], "ts": time.time()}  # fmt: skip
    (w.outbox / f"{sid}.verdict.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


def _move_dev(w: SimpleNamespace, why: str) -> str:  # another change lands on dev after the green was made
    (w.blue / "AGENTS.md").write_text(f"agents, {why}\n", encoding="utf-8")
    _git(w.blue, "commit", "-q", "-am", why)
    return _git(w.blue, "rev-parse", "dev")


async def _eventually(check: Callable[[], Any], timeout: float = 10.0) -> Any:
    deadline = time.monotonic() + timeout
    while not check() and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    return check()


def _card(w: SimpleNamespace, eid: str) -> dict[str, Any]:
    return task_bot_runtime.get_execution(eid, w.board) or {}


async def _chat_send(w: SimpleNamespace, sid: str, events: list[dict[str, Any]]) -> tuple[str, Path, str]:
    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    card = await chat_self_project.start_background_delegation(
        w.app, session_id=sid, prompt=ASK, mode="auto", recent_messages=[], emit_event=emit, force=True,
        autonomy_level=ap.AUTOPILOT, file_access=2, workspace="project", specialist_id="coding",
    )  # fmt: skip
    return card["execution_id"], Path(w.starts[0]["project_root"]), w.starts[0]["conversation_id"]


async def _start(w: SimpleNamespace) -> tuple[Path, str, str]:
    started = await thomas_project.start_thomas_project(w.app, request=ASK, settings={"autonomy_level": 5}, port=8898)
    return Path(started["project_root"]), started["conversation_id"], started["execution_id"]


def test_dev_moving_sends_the_change_back_to_its_team_in_the_same_green_unspent(w: SimpleNamespace) -> None:
    async def scenario() -> SimpleNamespace:
        root, cid, eid = await _start(w)
        for _ in range(11):  # a long run of retries behind it before this pass got through
            forge_code_store.append_agent_turn(
                root, cid, model="gpt", transcript="", changed_files=["README.md"], returncode=1, ok=False,
                noop=False, reason="the run crashed before finishing", outcome="failed",
            )  # fmt: skip
            forge_code_store.append_user_turn(root, cid, f"{ap.CONTINUATION_PREFIX} toward the goal: {ASK}")
        await _to_done(w, root, cid, {"README.md": "Send is blue\n"})
        kept, dev = green_checkout.find_green(eid), _move_dev(w, "the hunt project landed")
        _verdict(w, cid, eid, "refused", MOVED)
        await _eventually(lambda: len(w.starts) >= 2)
        return SimpleNamespace(root=root, cid=cid, eid=eid, kept=kept, dev=dev)

    s = asyncio.run(scenario())
    assert s.kept is not None, "the green outlives the hand-off until the promoter's verdict"
    # Since 2026-11-13 no done check runs between them.
    assert len(w.starts) == 2 and w.starts[1]["conversation_id"] == s.cid, "start, then repair round"
    assert forge_code_projects.conversation_metadata(w.catalog, s.cid)["project_root"] == str(s.root), "same green"
    message = w.starts[1]["message"]
    assert (
        message.startswith(ap.REPAIR_PREFIX)
        and "repair round 1" in message
        and "of 3" not in message
        and MOVED in message
    )
    # Task 3h: its team has no shell, so dev is merged into the green before the round, never left as a git step.
    assert f"now stands on {s.dev}" in message and "git merge" not in message and "no file holds a conflict" in message
    assert "changelog.d/" in message and green_checkout.find_green(s.eid).base == s.dev
    git_dir = green_checkout.find_green(s.eid).git_dir
    assert _git(s.root, f"--git-dir={git_dir}", "cat-file", "-t", s.dev) == "commit", "the sha resolves in green"
    turns = ap._load_joined_conversation(s.root, w.catalog, s.cid)["turns"]
    assert ap._continuation_count(turns) == 1, "the pass that got through remains; the queued repair spends nothing"
    counted = ap.ran_continuations(turns)
    assert counted[0]["reason"] == "1 file(s) changed"
    _finish(s.root, s.cid, files={"changelog.d/send-button.md": "- The Send button is blue.\n"})
    after = ap.decide(ap._load_joined_conversation(s.root, w.catalog, s.cid))
    assert after.action == "done", "the merged change is handed in again; the many earlier retries do not stop it"


def test_a_landed_verdict_removes_the_green_it_kept_until_then(w: SimpleNamespace) -> None:
    async def scenario() -> tuple[bool, bool, str]:
        root, cid, eid = await _start(w)
        await _to_done(w, root, cid, {"README.md": "Send is blue\n"})
        waiting = green_checkout.find_green(eid) is not None and root.is_dir()
        _verdict(w, cid, eid, "landed", "on dev and in the running copy")
        return waiting, bool(await _eventually(lambda: not root.exists())), eid

    waiting, gone, eid = asyncio.run(scenario())
    assert waiting, "kept, awaiting your verdict"
    assert gone and green_checkout.find_green(eid) is None, "landed: the green is removed, as before"
    assert len(w.starts) == 1, "nothing more runs once it landed (the start; no done check since 2026-11-13)"


def test_a_decline_keeps_the_green_7_days_and_says_so(w: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict[str, Any]] = []

    async def scenario() -> tuple[dict[str, Any], Path, bool]:
        eid, root, cid = await _chat_send(w, "chat-no", events)
        await _to_done(w, root, cid, {"README.md": "Send is blue\n"})
        await _eventually(lambda: _card(w, eid).get("state") == "awaiting_proof")
        _verdict(w, cid, root.name, "declined", "you declined the change")
        cancelled = await _eventually(lambda: _card(w, eid).get("state") == "cancelled")
        await _eventually(lambda: [q for q in w.book.pending("chat-no") if "declined" in q["question"]])
        # Made 8 days ago and declined just now: an hourly sweep keeps it (7 days count from your decision).
        meta_file = w.greens / "git" / root.name / green_checkout.METADATA_NAME
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta_file.write_text(json.dumps({**meta, "created_at": meta["created_at"] - 8 * 86400}), encoding="utf-8")
        monkeypatch.setattr(chat_self_project, "_last_sweep", None)
        await chat_self_project._sweep_now_and_then(w.app)
        return _card(w, eid), root, bool(cancelled)

    card, root, cancelled = asyncio.run(scenario())
    assert cancelled and root.is_dir(), "a declined change stays in its green"
    assert all(t in card["progress_summary"] for t in ("declined", "7 days", str(root), "Nothing is retried")), card
    assert any(str(root) in str(e.get("last_progress") or "") for e in events), "and the chat is told"
    verdict_card = [q for q in w.book.pending("chat-no") if "declined" in q["question"]]
    assert verdict_card and any("7 days" in f["value"] for f in verdict_card[-1]["details"]["fields"])
    assert len(w.starts) == 1, "nothing is retried (the start; no done check since 2026-11-13)"


def test_four_refusals_each_get_a_repair_round_and_no_successor(w: SimpleNamespace) -> None:
    async def scenario() -> tuple[list[str], dict[str, Any], Path, str]:
        eid, root, cid = await _chat_send(w, "chat-moved", [])
        files, said = {"README.md": "Send is blue\n"}, []
        for n in range(1, 5):
            await _to_done(w, root, cid, files)
            assert await _eventually(lambda: _card(w, eid).get("state") == "awaiting_proof"), _card(w, eid)
            # The card can enter awaiting_proof just before its watcher resumes _await_verdict.
            # Give that watcher its next event-loop turn before supplying the verdict.
            await asyncio.sleep(0)
            _move_dev(w, f"landing {n}")
            before = len(w.starts)
            _verdict(w, cid, root.name, "refused", MOVED)
            assert await _eventually(lambda: len(w.starts) > before), f"no repair round {n}: {_card(w, eid)}"
            assert await _eventually(lambda: f"repair round {n}" in str(_card(w, eid).get("progress_summary")))
            said.append(str(_card(w, eid)["progress_summary"]))
            files = {"changelog.d/send-button.md": f"- The Send button is blue (merged dev, round {n}).\n"}
        return said, _card(w, eid), root, cid

    said, card, root, cid = asyncio.run(scenario())
    assert [f"repair round {n}" in text for n, text in enumerate(said, 1)] == [True] * 4
    assert all("of 3" not in text and "of 4" not in text for text in said), "the round is counted, never limited"
    assert len([s for s in w.starts if s["message"].startswith(ap.REPAIR_PREFIX)]) == 4, "no bound on rounds"
    assert not (thomas_project.settled_record(w.catalog, cid) or {}).get("successor"), "no new project takes over"
    assert card["state"] != "failed", card
    assert "stopped" not in card["progress_summary"]
    assert root.is_dir(), "the change stays in its green"


def test_the_request_names_changelog_d_the_size_rule_and_what_other_projects_changed(w: SimpleNamespace) -> None:
    other = green_checkout.create_green(blue=w.blue, execution_id="thomas-sibling01")
    (other.work / "README.md").write_text("Send is red\n", encoding="utf-8")
    (other.work / "thomas").mkdir()
    (other.work / "thomas" / "send_button.py").write_text("COLOUR = 'red'\n", encoding="utf-8")
    done = green_checkout.create_green(blue=w.blue, execution_id="thomas-landed01")
    (done.work / "landed.md").write_text("landed\n", encoding="utf-8")
    green_checkout.mark_settled(done)

    asyncio.run(_start(w))
    message = w.starts[0]["message"]
    assert message.startswith(ASK) and "changelog.d/<short-name>.md" in message and "never edit CHANGELOG.md" in message
    assert "800" in message and "allowed_large_files" in message and "max_growth_lines" in message
    assert "thomas-sibling01" in message and "thomas/send_button.py" in message and "README.md" in message
    assert "thomas-landed01" not in message and "landed.md" not in message, "a settled project is not running"
    assert _git(other.work, f"--git-dir={other.git_dir}", "diff", "--cached", "--name-only") == "", "never staged"


def test_the_verdict_names_every_file_that_no_longer_applies(tmp_path: Path) -> None:
    names = ["CHANGELOG.md", *(f"tests/web_node/test_a_rather_long_descriptive_name_{i:02d}.py" for i in range(9))]
    blue = _blue(tmp_path / "blue", dict.fromkeys(names, "first\nsecond\nthird\n"))
    green = green_checkout.create_green(blue=blue, execution_id="thomas-conflict01")
    for name in names:
        (green.work / name).write_text("first\nsecond, from the team\nthird\n", encoding="utf-8")
    sub = green_handoff.settle(green.execution_id, promote=True, summary="Fixed it.", chat="chat-1")
    for name in names:  # dev moves under it: another landing changed the same lines
        (blue / name).write_text("first\nsecond, from dev\nthird\n", encoding="utf-8")
    _git(blue, "commit", "-q", "-am", "another landing")
    (pins := tmp_path / "pins").mkdir()
    (pins / trusted_card.PIN_NAME).write_text(trusted_card.catalogue_digest(trusted_card.CATALOGUE_PATH))
    root, asked = cage_shell.cage_root(), "a change that no longer applies is refused before you are asked"
    promoter = sp.Promoter(repo=blue, cage_root=root, ask=lambda *_: pytest.fail(asked), pin_root=pins)
    promoter.audit = lambda _repo: []  # nobody unexpected can write Thomas's code
    outcome = promoter.promote(sub)
    verdict = json.loads((root / "outbox" / f"{sub.name}.verdict.json").read_text(encoding="utf-8"))
    assert outcome.status == verdict["status"] == "refused", verdict
    assert verdict["detail"].startswith("the change no longer applies to dev: "), verdict["detail"]
    assert sorted(verdict["conflicts"]) == sorted(names)
    assert all(name in verdict["detail"] for name in names), "every file, never cut mid-word"
    assert self_change_status.dev_moved(verdict)
