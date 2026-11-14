"""A change checked before your card goes back to its team with the findings: POST /api/self/projects/{id}/send-back.

On 2026-09-25 two hand-ins were checked before your card and both broke tests that pass on dev. They were withdrawn
from the promoter's inbox, and their teams could not be reached: settling had unbound each conversation from its
green, so Build answered 409 project_is_thomas_source. A declined card was the same dead end. Real here: the whole
server app with its own loopback guard, git greens, the conversation store and registry, the settle and Autopilot's
repair round. Stubbed: Build's start hook (Task 3b's stand-in, which refuses a settled conversation as Build does), and
the promoter's inbox and verdict files. The fixtures and fakes are Task 3b's and Task 3c's.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_a_refused_self_change_goes_back_to_its_team import _hook
from tests.test_a_thomas_project_starts_without_chat import (  # noqa: F401 -- w is the fixture
    ASK,
    CLAUDE,
    _client,
    _finish_and_hand_in,
    _listed,
    _start,
    _verdict,
    w,
)
from thomas.core.acceptance_notes import without_thomas_notes
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import chat_self_project, green_checkout, thomas_project, thomas_project_successor
from thomas.server.routes import autopilot_sent_back
from thomas.server.routes import evolve_agent_autopilot as ap

URL = "/api/self/projects/{}/send-back"
# What an independent check found on 2026-09-25, in the shape a reviewer writes it.
FINDINGS = (
    "tests/test_architecture.py fails: thomas/core/x.py now imports thomas.server.\n"
    "tests/test_routing.py launched the real Claude program from a test (a routing bug).\n"
    "17 tests that pass on dev fail with this change."
)


def _build(w: SimpleNamespace) -> None:
    """Task 3b's Build stand-in, noting the repair round due as each run starts; ``w.refuse`` refuses a repair start."""
    start, w.due, w.refuse = _hook(w), [], ""

    async def hook(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        cid = body["conversation_id"]
        root = str((forge_code_projects.conversation_metadata(w.catalog, cid) or {}).get("project_root") or "")
        conversation = forge_code_store.load_conversation(Path(root), cid) if root else None  # bound, in temp
        w.due.append(thomas_project.repair_due(conversation or {}))
        if w.refuse and (
            body["message"].startswith(ap.REPAIR_PREFIX)
            or ("This is a fresh project continuing" in body["message"] and w.refuse == "successor_refused")
        ):
            return 409, {"ok": False, "code": w.refuse, "error": w.refuse}
        status, result = await start(body, port=port)
        if 200 <= status < 300:
            forge_code_projects.update_conversation_settings(
                w.catalog, cid, {"requested": {key: body[key] for key in CLAUDE if key in body}}
            )
        return status, result

    w.hook = hook


async def _handed_in(client: Any, w: SimpleNamespace, rel: str = "README.md") -> tuple[dict[str, Any], str]:
    started = await _start(client)
    return started, await asyncio.to_thread(_finish_and_hand_in, w, started, rel)


def _withdraw(w: SimpleNamespace, sid: str) -> None:
    """Out of the promoter's inbox, moved and never deleted: withdrawn by hand, or processed once answered."""
    (w.tmp / "processed").mkdir(exist_ok=True)
    shutil.move(str(w.tmp / "inbox" / sid), str(w.tmp / "processed" / sid))


async def _send_back(client: Any, cid: str, body: Any) -> tuple[int, dict[str, Any]]:
    response = await client.post(URL.format(cid), json=body)
    return response.status, await response.json()


def _repair_starts(w: SimpleNamespace) -> list[dict[str, Any]]:
    return [start for start in w.starts if start["message"].startswith(ap.REPAIR_PREFIX)]


def test_findings_that_are_not_text_or_too_long_are_refused_and_nothing_starts(w: SimpleNamespace) -> None:
    async def scenario() -> tuple[list[tuple[int, str]], str]:
        client = await _client(w)
        try:
            started, sid = await _handed_in(client, w)
            _withdraw(w, sid)
            cid, answers = started["conversation_id"], []
            for body in (["findings"], {}, {"findings": " \n "}, {"findings": 7}, {"findings": "x" * 20_001}):
                status, payload = await _send_back(client, cid, body)
                answers.append((status, payload["error"]))
            for bad in ("-leading-dash", "x" * 161):  # not the chat-id pattern
                status, payload = await _send_back(client, bad, {"findings": FINDINGS})
                answers.append((status, payload["error"]))
            raw = await client.post(URL.format(cid), data=b"not json", headers={"Content-Type": "application/json"})
            answers.append((raw.status, (await raw.json())["error"]))
            return answers, cid
        finally:
            await client.close()

    answers, cid = asyncio.run(scenario())
    assert [status for status, _ in answers] == [400] * 8, answers
    assert "JSON object" in answers[0][1] and "findings" in answers[1][1] and "findings" in answers[2][1]
    assert "20000" in answers[4][1] and "conversation id" in answers[5][1] and "not JSON" in answers[7][1]
    assert _repair_starts(w) == [] and thomas_project.settled_record(w.catalog, cid) is not None, "still handed in"


def test_only_a_handed_in_thomas_project_can_be_sent_back(w: SimpleNamespace) -> None:
    async def scenario() -> list[int]:
        client = await _client(w)
        try:
            running = await _start(client)  # its team still has it
            empty = await _start(client)  # finished without changing a file: nothing was handed in
            work, done = Path(empty["project_root"]), empty["conversation_id"]
            forge_code_store.append_agent_turn(
                work, done, model="claude", transcript="", changed_files=[], returncode=0, ok=True, noop=False,
                reason="Thomas replied without changing files", outcome="completed",
            )  # fmt: skip
            assert await asyncio.to_thread(thomas_project.settle_if_finished, work, w.catalog, done) is None
            assert thomas_project.settled_record(w.catalog, done)["submission"] == "", "settled, nothing handed in"
            ids = ("fc_20260925T000000_abcdef", "c:fc_x", running["conversation_id"], done)
            return [(await _send_back(client, cid, {"findings": FINDINGS}))[0] for cid in ids]
        finally:
            await client.close()

    assert asyncio.run(scenario()) == [404, 404, 404, 404]
    assert _repair_starts(w) == []


def test_a_change_that_cannot_go_back_is_refused_with_the_reason(w: SimpleNamespace) -> None:
    async def scenario() -> tuple[list[tuple[int, str]], list[dict[str, Any]]]:
        _build(w)
        client = await _client(w)
        try:
            landed, waiting, gone, refused = [await _handed_in(client, w) for _ in range(4)]
            _verdict(w, landed[0], landed[1], "landed", "on dev and in the running copy")
            _withdraw(w, landed[1])
            _withdraw(w, gone[1])
            green_checkout.remove_green(green_checkout.find_green(gone[0]["execution_id"]))
            _withdraw(w, refused[1])
            answers = []
            for started, _ in (landed, waiting, gone):
                status, payload = await _send_back(client, started["conversation_id"], {"findings": FINDINGS})
                answers.append((status, payload["error"]))
            w.refuse = "execution_blocked"  # Build answers the repair round's start with a refusal
            status, payload = await _send_back(client, refused[0]["conversation_id"], {"findings": FINDINGS})
            answers.append((status, payload["error"]))
            return answers, [landed[0], waiting[0], gone[0]]
        finally:
            await client.close()

    answers, untouched = asyncio.run(scenario())
    assert [status for status, _ in answers] == [409, 409, 409, 409], answers
    assert "already landed" in answers[0][1] and "new project" in answers[0][1]
    assert "promoter's inbox" in answers[1][1] and "answer or decline it first" in answers[1][1]
    assert "green" in answers[2][1] and "gone" in answers[2][1]
    assert "no run started" in answers[3][1] and "Build refused" in answers[3][1]
    for started in untouched:  # a refused send-back changes nothing: still handed in, still unbound
        cid = started["conversation_id"]
        assert thomas_project.settled_record(w.catalog, cid) is not None
        assert forge_code_projects.conversation_metadata(w.catalog, cid) is None
    assert len(_repair_starts(w)) == 0 and len(w.due) == 5, "only the refused round reached Build's start"


def test_a_checked_change_goes_back_to_its_team_with_the_findings(w: SimpleNamespace) -> None:
    # Withdrawn with no verdict; declined at your card; refused before it for a reason its team cannot merge away.
    verdicts = ("", "declined", "refused")

    async def scenario() -> tuple[list[tuple[Any, ...]], dict[str, dict[str, Any]]]:
        _build(w)
        client = await _client(w)
        try:
            sent = []
            for verdict in verdicts:
                started, sid = await _handed_in(client, w)
                if verdict:
                    _verdict(w, started, sid, verdict, f"{verdict}: the change is not on dev")
                _withdraw(w, sid)
                status, answer = await _send_back(client, started["conversation_id"], {"findings": FINDINGS})
                due = w.due[-1]  # what Autopilot saw as the round began
                sent.append((verdict or "withdrawn", started, sid, status, answer, due))
            return sent, await _listed(client)
        finally:
            await client.close()

    sent, listed = asyncio.run(scenario())
    starts = _repair_starts(w)
    assert len(starts) == len(verdicts) and len(sent) == len(verdicts)
    for (case, started, sid, status, answer, due), start in zip(sent, starts):
        cid, eid, work = started["conversation_id"], started["execution_id"], Path(started["project_root"])
        assert status == 200, (case, answer)
        assert answer == {"ok": True, "conversation_id": cid, "execution_id": eid, "round": 1}, case
        assert forge_code_projects.conversation_metadata(w.catalog, cid)["project_root"] == str(work), case
        assert thomas_project.settled_record(w.catalog, cid) is None, f"{case}: its green's conversation is live again"
        assert (due["round"], due["why"], due["detail"], due["sid"]) == (1, thomas_project.SENT_BACK, FINDINGS, sid)
        assert "README.md" in due["changed_files"], f"{case}: the repair knows the changed patch"
        message = start["message"]
        assert "Files already changed in this copy: README.md" in message, case
        assert message.index("Run the failing checks") < message.index("Re-run the checks"), case
        assert (
            start["conversation_id"] == cid and "repair round 1" in message and "of 3" not in message and ASK in message
        ), case
        assert FINDINGS in message, f"{case}: the findings, in full"
        assert "git merge" not in message and "dev has moved" not in message, f"{case}: dev did not move"
        assert "tests/test_architecture.py" in message.split(FINDINGS)[0] and "evidence" in message, case
        turns = forge_code_store.load_conversation(work, cid)["turns"]
        assert (turns[-1]["role"], turns[-1]["text"]) == ("user", message), f"{case}: Build took it, it runs"
        row = listed[cid]
        assert (row["state"], row["execution_id"]) == ("repair round 1", eid), case
        assert row["last_verdict"] == {"submission": sid, "status": "sent_back", "detail": FINDINGS.splitlines()[0]}


def test_a_change_sent_back_more_than_three_times_keeps_getting_repair_rounds(w: SimpleNamespace) -> None:
    async def scenario() -> tuple[dict[str, Any], list[tuple[int, dict[str, Any]]]]:
        _build(w)
        client = await _client(w)
        try:
            started = await _start(client)
            sid = await asyncio.to_thread(_finish_and_hand_in, w, started, "README.md")
            answers = []
            for n in range(1, 7):
                _withdraw(w, sid)
                answers.append(await _send_back(client, started["conversation_id"], {"findings": f"round {n}: x"}))
                sid = await asyncio.to_thread(_finish_and_hand_in, w, started, f"fix-{n}.md")
            return started, answers
        finally:
            await client.close()

    started, answers = asyncio.run(scenario())
    assert [(status, answer.get("round")) for status, answer in answers] == [(200, n) for n in range(1, 7)]
    assert all("successor" not in answer for _, answer in answers), "no new project ever takes over"
    assert len(_repair_starts(w)) == 6, "every round reached its team"
    conversation = forge_code_store.load_conversation(Path(started["project_root"]), started["conversation_id"])
    assert thomas_project.repairs_spent(conversation) == "", "the project is never marked spent"
    assert [r["round"] for r in conversation["thomas_project"]["repairs"]] == [1, 2, 3, 4, 5, 6]
    assert all("of 3" not in start["message"] for start in _repair_starts(w))


def test_chat_card_follows_successor_and_keeps_its_green_reserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, new, eid = "old-project", "next-project", "self-thomas-green"
    project_root = tmp_path / "green"
    catalog_root = tmp_path / "catalog"
    conversation = forge_code_store.draft_conversation(
        title="Change Thomas", thomas_project={"execution_id": eid, "successor": {"conversation_id": new}}
    )
    conversation["id"] = old
    forge_code_store.write_conversation(project_root, conversation)
    emitted: list[str] = []

    class Emitter:
        async def progress(self, record: dict[str, Any], *, text: str, **kwargs: Any) -> None:
            emitted.append(text)

    card = chat_self_project._Card(
        app={},
        eid="chat-card",
        root=tmp_path,
        cid=old,
        execution_id=eid,
        project_root=project_root,
        catalog_root=catalog_root,
        emitter=Emitter(),
        bot=None,
    )
    monkeypatch.setattr(chat_self_project, "_sleep", lambda _: asyncio.sleep(0))
    monkeypatch.setattr(chat_self_project, "_run_active", lambda app, cid: False)
    monkeypatch.setattr(chat_self_project.task_bot_runtime, "get_execution", lambda eid, root: {})
    monkeypatch.setattr(chat_self_project, "_update", lambda card, **fields: fields)

    async def settled(card: Any) -> bool:
        assert card.cid == new
        assert eid in chat_self_project._greens_in_use({})
        return False

    monkeypatch.setattr(chat_self_project, "_settled", settled)
    # The old project's terminal phase must never end its Chat card before the successor is followed.
    monkeypatch.setattr(
        chat_self_project, "_check", lambda card: (False, ("ended", "stopped") if card.cid == old else ("settled", ""))
    )
    green = green_checkout.Green(eid, project_root, tmp_path / "git", "base", tmp_path)
    monkeypatch.setattr(chat_self_project.green_checkout, "find_green", lambda requested: green)
    monkeypatch.setattr(chat_self_project.green_checkout, "green_root", lambda: tmp_path)
    (tmp_path / "work").mkdir()
    (tmp_path / "git" / eid).mkdir(parents=True)
    forge_code_store.write_conversation(tmp_path / "work" / eid, conversation)
    monkeypatch.setattr(chat_self_project.thomas_project, "project_phase", lambda root, catalog, cid: ("waiting", ""))
    assert chat_self_project._claim(green, {}) is None  # the old record is terminal, but its successor is not
    asyncio.run(chat_self_project.follow_card(card))
    assert card.cid == new
    assert len(emitted) == 1 and "new Thomas project carries" in emitted[0]
    assert "stopped" not in emitted[0]
    assert chat_self_project._claim(green, {}) is None  # the card still owns this checkout
    chat_self_project._FOLLOWED.pop(card.eid, None)
    assert chat_self_project._claim(green, {}) is None  # even between runs after the follower stops
    chat_self_project._RESUMING.discard(eid)


def test_a_dev_moved_refusal_after_many_rounds_sends_the_change_back_again_not_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, eid = "old-project", "self-thomas-green"
    project_root, catalog_root = tmp_path / "green", tmp_path / "catalog"
    conversation = forge_code_store.draft_conversation(
        title="Change Thomas",
        thomas_project={"execution_id": eid, "repairs": [{"round": n} for n in range(1, 4)]},
    )
    conversation["id"] = old
    forge_code_store.write_conversation(project_root, conversation)
    verdict = {"status": "refused", "detail": "the change no longer applies to dev"}
    emitted: list[str] = []

    class Emitter:
        async def progress(self, record: dict[str, Any], *, text: str, **kwargs: Any) -> None:
            emitted.append(text)

        async def failed(self, record: dict[str, Any], *, text: str, **kwargs: Any) -> None:
            emitted.append(text)

    card = chat_self_project._Card(
        app={},
        eid="chat-card",
        root=tmp_path,
        cid=old,
        execution_id=eid,
        project_root=project_root,
        catalog_root=catalog_root,
        emitter=Emitter(),
        bot=None,
    )
    monkeypatch.setattr(
        chat_self_project.thomas_project,
        "settled_record",
        lambda root, cid: {
            "submission": "last-hand-in",
            "repairs": [{"round": n} for n in range(1, 4)],
        },
    )
    monkeypatch.setattr(chat_self_project.self_change_status, "read_hand_in_state", lambda sid: verdict)
    monkeypatch.setattr(chat_self_project.self_change_status, "verdict_arrived", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_self_project.task_bot_runtime, "get_execution", lambda eid, root: {})
    monkeypatch.setattr(chat_self_project, "_update", lambda card, **fields: fields)
    monkeypatch.setattr(chat_self_project, "_POLL_S", 0.01)
    monkeypatch.setattr(chat_self_project, "_IDLE_GRACE_S", 0.5)

    def fail(*args: Any, **kwargs: Any) -> dict[str, Any]:
        emitted.append(str(kwargs.get("summary")))
        return {}

    monkeypatch.setattr(chat_self_project.task_bot_runtime, "fail_execution", fail)
    sent_back: list[int] = []

    async def repairing(card: chat_self_project._Card, submission: str, detail: str, number: int) -> bool:
        sent_back.append(number)
        return True

    monkeypatch.setattr(chat_self_project, "_repairing", repairing)

    assert asyncio.run(chat_self_project._settled(card)) is True
    assert sent_back == [4], "a fourth round, not a failure or a new project"
    assert all("stopped" not in text for text in emitted)
    assert not any("new Thomas project carries" in text for text in emitted)


def test_five_rounds_in_a_row_each_start_exactly_one_repair(w: SimpleNamespace) -> None:
    _build(w)

    async def scenario() -> list[tuple[int, Any]]:
        client = await _client(w)
        try:
            started, sid = await _handed_in(client, w)
            statuses = []
            for n in range(1, 6):
                _withdraw(w, sid)
                status, answer = await _send_back(client, started["conversation_id"], {"findings": f"round {n}"})
                statuses.append((status, answer.get("round")))
                sid = await asyncio.to_thread(_finish_and_hand_in, w, started, f"retry-fix-{n}.md")
            return statuses
        finally:
            await client.close()

    assert asyncio.run(scenario()) == [(200, n) for n in range(1, 6)]
    assert len(_repair_starts(w)) == 5


def test_a_refused_fourth_round_stays_due_and_is_never_a_successor(w: SimpleNamespace) -> None:
    _build(w)

    async def scenario() -> tuple[dict[str, Any], tuple[int, dict[str, Any]]]:
        client = await _client(w)
        try:
            started, sid = await _handed_in(client, w)
            for n in (1, 2, 3):
                _withdraw(w, sid)
                status, _ = await _send_back(client, started["conversation_id"], {"findings": f"round {n}"})
                assert status == 200
                sid = await asyncio.to_thread(_finish_and_hand_in, w, started, f"retry-fix-{n}.md")
            _withdraw(w, sid)
            w.refuse = "execution_blocked"
            return started, await _send_back(client, started["conversation_id"], {"findings": "last review"})
        finally:
            await client.close()

    started, (status, refusal) = asyncio.run(scenario())
    assert status == 409 and "no run started" in refusal["error"] and "successor" not in refusal
    conversation = forge_code_store.load_conversation(Path(started["project_root"]), started["conversation_id"])
    assert thomas_project.repair_due(conversation)["round"] == 4, "the fourth round is still owed to its team"
    assert thomas_project.repairs_spent(conversation) == ""


@pytest.mark.parametrize("why", ["dev_moved", "too_large", "sent_back"])
def test_every_reason_keeps_getting_rounds_and_is_never_spent_after_three(tmp_path: Path, why: str) -> None:
    root = tmp_path / "green-work"
    rounds = [{"round": n, "why": why, "detail": "d", "dev": "", "sid": "", "at": ""} for n in (1, 2, 3)]
    project = {"execution_id": "thomas-x", "repairs": rounds}
    conv = forge_code_store.new_conversation(root, title="t", thomas_project=project)
    assert thomas_project.prepare_repair(root, tmp_path / "catalog", conv["id"], why=why, detail="the findings") == 4
    stored = forge_code_store.load_conversation(root, conv["id"])
    assert thomas_project.repairs_spent(stored) == ""
    assert [r["round"] for r in stored["thomas_project"]["repairs"]] == [1, 2, 3, 4]


def test_autopilot_names_a_sent_back_round_for_what_it_is() -> None:
    due = {"round": 1, "why": thomas_project.SENT_BACK, "detail": FINDINGS, "dev": "abc123", "sid": "self-x", "at": ""}
    conversation = {"id": "fc_x", "turns": [{"role": "user", "text": ASK}], "thomas_project": {"repairs": [due]}}
    decision = ap.decide(conversation)
    assert decision.action == "repair" and "sent back" in decision.reason and "too large" not in decision.reason
    assert decision.message == ap.repair_message(ASK, due) and "abc123" not in decision.message


def test_a_caller_on_another_machine_cannot_send_a_change_back(w: SimpleNamespace) -> None:
    async def scenario() -> int:
        client = await _client(w, remote="203.0.113.7")
        try:
            return (await client.post(URL.format("fc_20260925T000000_abcdef"), json={"findings": FINDINGS})).status
        finally:
            await client.close()

    assert asyncio.run(scenario()) == 403
    assert w.starts == []
