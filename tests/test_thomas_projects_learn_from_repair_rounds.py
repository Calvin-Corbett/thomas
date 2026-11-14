"""What earlier Thomas projects were sent back for reaches the next project's team.

You said on 2026-09-25: "he is really dumb like it doenst seem like he is learning anything". A repair round's reason
was written only on its own project's record, so the next team made the same mistake again. Now every round
``thomas_project.prepare_repair`` stamps lands in one ledger in your Thomas data folder, and the next project's first
message counts what came back most often. Real here: the whole server app and its start and send-back routes, git
greens, the conversation store, the check's own findings text. Stubbed: Build's start hook and the promoter's files.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_a_checked_change_goes_back_to_its_team import FINDINGS, _build, _handed_in, _send_back, _withdraw
from tests.test_a_thomas_project_starts_without_chat import MOVED, _client, _start, w  # noqa: F401 -- w: fixture
from thomas.forge.anvil import forge_code_store
from thomas.server import repair_ledger, thomas_project, thomas_project_words
from thomas.server.precard import handover, report
from thomas.server.precard.lint import LintResult
from thomas.server.proof.compare import Verdict

HEADING = "What earlier Thomas projects were sent back for most often"
TIP = "0123456789abcdef"
LESSONS_NOTE = repair_ledger.lessons_note  # the real count: the shared ``w`` fixture blanks it (cdeba624)


@pytest.fixture
def ledger(w: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> Path:  # noqa: F811
    monkeypatch.setenv("THOMAS_DATA_DIR", str(w.tmp / "data"))  # a data folder of this test's own
    monkeypatch.setattr(repair_ledger, "lessons_note", LESSONS_NOTE)  # the count is what these tests check
    return repair_ledger.ledger_path()


def _found(**blocks: Any) -> str:
    """``report.findings_text`` with only the named blocks filled in."""
    verdict = Verdict(
        findings=blocks.get("findings", ()), added=blocks.get("added", ()), excused=(), flaky=(),
        unconfirmed=blocks.get("unconfirmed", ()), timed_out=blocks.get("timed_out", ()),
    )  # fmt: skip
    linted = LintResult(True, "", blocks.get("ruff", ()), blocks.get("unformatted", ()))
    return report.findings_text(TIP, verdict, linted, blocks.get("size", ()), blocks.get("broke", ""))


T = ("tests/test_x.py::test_a",)
# One repair round of every kind the checks write: (why, detail, the kind it lands as).
ROUNDS = [
    (thomas_project.SENT_BACK, _found(findings=T), "regressed"),
    (thomas_project.SENT_BACK, _found(added=T), "added_fail"),
    (thomas_project.SENT_BACK, _found(unconfirmed=T), "unconfirmed"),
    (thomas_project.SENT_BACK, _found(timed_out=T), "timed_out"),
    (thomas_project.SENT_BACK, _found(broke="ImportError: no module x"), "broke"),
    (thomas_project.SENT_BACK, _found(ruff=("x.py:1:1 F401",)), "ruff"),
    (thomas_project.SENT_BACK, _found(unformatted=("x.py",)), "unformatted"),
    (thomas_project.SENT_BACK, _found(size=("x.py: 900 lines",)), "size"),
    (thomas_project.DEV_MOVED, report.conflict_findings(TIP, "error: patch failed: AGENTS.md:1"), "conflict"),
    (thomas_project.DEV_MOVED, MOVED, "conflict"),  # the promoter's own dev-moved refusal
    (thomas_project.SENT_BACK, handover.moved_findings("a" * 64, "b" * 64), "moved"),
    (thomas_project.TOO_LARGE, "thomas/server/x.py grows to 900 lines", "too_large"),
]


def _records(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def _fresh_rounds(started: dict[str, Any]) -> None:
    """Forget a project's earlier rounds, so one project can be given more than three kinds."""
    work, cid = Path(started["project_root"]), started["conversation_id"]
    conversation = forge_code_store.load_conversation(work, cid)
    conversation["thomas_project"].pop("repairs", None)
    forge_code_store.write_conversation(work, conversation)


def _repair(w: SimpleNamespace, started: dict[str, Any], why: str, detail: str) -> int:  # noqa: F811
    _fresh_rounds(started)
    args = (Path(started["project_root"]), w.catalog, started["conversation_id"])
    return thomas_project.prepare_repair(*args, why=why, detail=detail)


async def _one_start(w: SimpleNamespace) -> dict[str, Any]:  # noqa: F811
    client = await _client(w)
    try:
        return await _start(client)
    finally:
        await client.close()


def _started_message(w: SimpleNamespace) -> str:  # noqa: F811
    asyncio.run(_one_start(w))
    return w.starts[-1]["message"]


def test_a_repair_round_of_each_kind_lands_one_record_of_that_kind(w: SimpleNamespace, ledger: Path) -> None:  # noqa: F811
    started = asyncio.run(_one_start(w))
    for why, detail, kind in ROUNDS:
        before = _records(ledger)
        assert _repair(w, started, why, detail) == 1, kind
        added = _records(ledger)[len(before) :]
        assert [(r["kind"], r["why"]) for r in added] == [(kind, why)], kind
        assert detail not in json.dumps(added), f"{kind}: the kind is kept, never the findings"


def test_a_manual_send_back_lands_its_first_sentence_through_the_route(w: SimpleNamespace, ledger: Path) -> None:  # noqa: F811
    long = "Your changelog says the cache is cleared on restart " + "and it is not " * 30 + ". Second sentence."

    async def scenario() -> list[int]:
        _build(w)
        client = await _client(w)
        try:
            statuses = []
            for findings in (FINDINGS, long):
                started, sid = await _handed_in(client, w)
                _withdraw(w, sid)
                statuses.append((await _send_back(client, started["conversation_id"], {"findings": findings}))[0])
            return statuses
        finally:
            await client.close()

    assert asyncio.run(scenario()) == [200, 200]
    said = [(r["kind"], r["why"], r["said"]) for r in _records(ledger)]
    first = "tests/test_architecture.py fails: thomas/core/x.py now imports thomas.server."
    assert said[0] == (repair_ledger.MANUAL, thomas_project.SENT_BACK, first)
    assert said[1][2] == long[: repair_ledger.SAID_MAX_CHARS].rstrip() and len(said[1][2]) <= 200
    assert len(said) == 2


def test_a_project_started_after_rounds_carries_the_count(w: SimpleNamespace, ledger: Path) -> None:  # noqa: F811
    assert HEADING not in _started_message(w), "no rounds recorded yet: no section at all"
    started = asyncio.run(_one_start(w))
    for why, detail in [ROUNDS[0][:2]] * 3 + [ROUNDS[-1][:2]] + [(thomas_project.SENT_BACK, FINDINGS)]:
        assert _repair(w, started, why, detail) == 1
    message = _started_message(w)
    section = message.split(HEADING, 1)[1].split("\n\n", 1)[0].splitlines()[1:]
    assert section == [
        "- 3 times: tests that pass on dev failed with the change",
        "- 1 time: the change broke the repo's size rule",
        "- 1 time: sent back by hand: tests/test_architecture.py fails: thomas/core/x.py now imports thomas.server.",
    ]
    last_lesson = thomas_project_words.LESSONS[-1]
    assert message.index(last_lesson) < message.index(HEADING), "after the lessons"


def test_the_count_shows_at_most_five_kinds_most_frequent_first(ledger: Path) -> None:
    kinds = list(repair_ledger.KIND_WORDS)[:7]
    records = [{"kind": kind, "why": "sent_back", "at": ""} for n, kind in enumerate(kinds) for _ in range(n + 1)]
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps(records), encoding="utf-8")
    lines = repair_ledger.lessons_note().splitlines()[1:]
    assert len(lines) == 5
    assert lines[0] == f"- 7 times: {repair_ledger.KIND_WORDS[kinds[6]]}"
    assert [int(line.split()[1]) for line in lines] == [7, 6, 5, 4, 3]


@pytest.mark.parametrize("broken", ["garbage", "folder"])
def test_an_unreadable_ledger_stops_neither_a_round_nor_a_start(w: SimpleNamespace, ledger: Path, broken: str) -> None:  # noqa: F811
    ledger.parent.mkdir(parents=True)
    if broken == "garbage":
        ledger.write_bytes(b"\xff\xfe{ not json")
    else:
        ledger.mkdir()  # a folder where the file goes: it can be neither read nor replaced
    message = _started_message(w)
    assert HEADING not in message and len(w.starts) == 1
    started = asyncio.run(_one_start(w))
    assert _repair(w, started, *ROUNDS[0][:2]) == 1, "the round was stamped"
    stored = forge_code_store.load_conversation(Path(started["project_root"]), started["conversation_id"])
    assert stored["thomas_project"]["repairs"][-1]["why"] == thomas_project.SENT_BACK
    if broken == "garbage":  # an unreadable ledger starts over with the round
        assert [r["kind"] for r in _records(ledger)] == ["regressed"]
    else:
        assert ledger.is_dir() and HEADING not in _started_message(w)


def test_the_ledger_never_grows_past_its_bound(w: SimpleNamespace, ledger: Path) -> None:  # noqa: F811
    bound = repair_ledger.MAX_RECORDS
    old = [{"kind": "ruff", "why": "sent_back", "at": str(n)} for n in range(bound - 1)]
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps(old), encoding="utf-8")
    started = asyncio.run(_one_start(w))
    three = _found(findings=T, added=T, size=("x.py: 900 lines",))
    assert _repair(w, started, thomas_project.SENT_BACK, three) == 1
    records = _records(ledger)
    assert len(records) == bound
    assert [r["kind"] for r in records[-3:]] == ["regressed", "added_fail", "size"]
    assert records[0]["at"] == "2", "the two oldest went"
    assert list(ledger.parent.glob("*.tmp")) == [], "written atomically, no scratch left"
