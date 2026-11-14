"""A team that worked a long time is not hidden by how much it wrote.

On 2026-11-05 ``GET /api/self/projects`` listed 85 projects and skipped 79 with "record is too large": the listing read
at most 2 MB of a conversation, and the teams that had done the most work wrote tens of MB of transcripts. The record
is streamed now, keeping only what the listing shows, and the restart pass cuts earlier transcripts to their tails
while it parses, so what either reads follows what it uses and not the size of the file.
"""

from __future__ import annotations

import json
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

from tests.restart_test_isolation import immediate_restart_retries, tmp_path_factory  # noqa: F401
from tests.test_a_restart_does_not_stop_a_thomas_project import (  # noqa: F401
    FIRST_RUN,
    _app,
    _restart,
    _stopped_run,
    isolated,
)
from thomas.forge.anvil import forge_code_store
from thomas.server import thomas_project
from thomas.server.routes import self_project_listing_cache as listing
from thomas.server.routes.evolve_agent_receipts import _save_action_receipt

MB = 1_000_000
# What a run's transcript looks like on disk: JSON lines, so quotes and newlines are escaped again inside the string.
_LINE = json.dumps(
    json.dumps({"fc": "tool", "name": "edit", "input": {"path": "thomas/x.py", "text": 'a "q" b\n' * 8}})
)[1:-1]


def _transcript(size: int) -> str:
    return json.loads('"' + (_LINE + "\\n") * (size // (len(_LINE) + 2)) + '"')


def _write_big(path: Path, cid: str, megabytes: int, turns: int = 11) -> None:
    """The conversation as forge_code_store writes it, with ``megabytes`` of transcripts spread over ``turns`` runs."""
    head = {
        "id": cid,
        "title": "Internet reach",
        "created_at": "2026-11-05T00:00:00+00:00",
        "updated_at": "2026-11-05T03:00:00+00:00",
        "thomas_project": {"execution_id": "thomas-0123456789ab"},
    }
    body = json.dumps(_transcript(megabytes * MB // turns))
    with path.open("w", encoding="utf-8") as out:
        out.write(json.dumps(head)[:-1] + ', "turns": [')
        for n in range(turns):
            user = {"role": "user", "text": "Add the reach plugin. " * 30, "ts": "2026-11-05T00:00:00+00:00"}
            agent = {"role": "agent", "model": "claude", "ts": "2026-11-05T00:01:00+00:00", "changed_files": ["a.py"],
                     "ok": True, "outcome": "completed", "run_id": f"run-{n}"}  # fmt: skip
            out.write((", " if n else "") + json.dumps(user) + ", ")
            out.write(json.dumps(agent)[:-1] + ', "transcript": ' + body + "}")
        out.write("]}")


def test_a_record_over_the_old_two_megabyte_cap_is_listed(tmp_path: Path) -> None:
    _write_big(tmp_path / "fc_big.json", "fc_big", 8)
    assert (tmp_path / "fc_big.json").stat().st_size > 4 * listing.MAX_WHOLE_FILE_BYTES // 16
    warnings: list[str] = []
    rows = listing.read_project_records(tmp_path, strict=True, warnings=warnings)
    assert warnings == [] and [row["id"] for row in rows] == ["fc_big"]
    turns = rows[0]["turns"]
    assert len(turns) == 22 and turns[-1]["outcome"] == "completed" and "transcript" not in turns[-1]
    assert len(turns[0]["text"]) == 256, "a user turn keeps the prefix the listing classifies by"


def test_a_fifty_megabyte_record_is_listed_in_bounded_memory(tmp_path: Path) -> None:
    _write_big(tmp_path / "fc_big.json", "fc_big", 50)
    size = (tmp_path / "fc_big.json").stat().st_size
    assert size > 50 * MB
    tracemalloc.start()
    try:
        rows = listing.read_project_records(tmp_path, strict=True)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert [row["id"] for row in rows] == ["fc_big"]
    assert peak < 4 * MB, f"reading {size // MB} MB held {peak // MB} MB at once"


def test_pathological_nesting_still_fails_safely_and_is_named(tmp_path: Path) -> None:
    deep = '{"id": "fc_deep", "thomas_project": {"execution_id": "e"}, "turns": [{"role": "agent", "transcript": '
    (tmp_path / "fc_deep.json").write_text(deep + "[" * 200_000, encoding="utf-8")
    (tmp_path / "fc_deep2.json").write_text('{"id": "fc_deep2", "turns": ' + "[" * 200_000, encoding="utf-8")
    warnings: list[str] = []
    failures: list[Any] = []
    assert listing.read_project_records(tmp_path, warnings=warnings, failures=failures) == []
    assert len(warnings) == 2 and all("unreadable" in text and "nested too deeply" in text for text in warnings)
    assert failures == [], "corruption is a warning; it does not hold the listing incomplete"


def test_a_record_past_the_safety_valve_is_listed_unreadable_with_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_big(tmp_path / "fc_big.json", "fc_big", 1, turns=2)
    (tmp_path / "fc_torn.json").write_text('{"id": "fc_torn", "turns": [', encoding="utf-8")
    monkeypatch.setattr(listing, "MAX_PROJECT_RECORD_BYTES", 100_000)
    warnings: list[str] = []
    failures: list[Any] = []
    assert listing.read_project_records(tmp_path, warnings=warnings, failures=failures) == []
    assert [entry.cid for entry in failures] == ["fc_big"], (
        "the too-large record is reported as a project it cannot read"
    )
    big = next(text for text in warnings if "fc_big" in text)
    torn = next(text for text in warnings if "fc_torn" in text)
    assert "safety limit" in big and "unreadable" not in big
    assert "unreadable" in torn


# ---- the restart pass --------------------------------------------------------------------------------------------


def _interrupted_big(tmp_path: Path, state: str, megabytes: int = 6) -> Any:
    """Team 8aed93's shape: runs that wrote megabytes, then the agent turn the earlier restart recorded as
    interrupted, with the repair request before it still the one waiting for an answer."""
    p = _stopped_run(tmp_path, kind="repair", state=state)
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    stamp = conversation["turns"][-1]["ts"]
    for turn in conversation["turns"]:
        if turn["role"] == "agent":
            turn["transcript"] = _transcript(megabytes * MB // 2)
    conversation["turns"].append(
        {
            "role": "agent",
            "model": "",
            "ts": stamp,
            "transcript": _transcript(megabytes * MB // 2),
            "changed_files": [],
            "returncode": None,
            "ok": False,
            "noop": True,
            "run_id": "run-before",
            "reason": "Thomas's server stopped before this run recorded an ending; carrying on after the restart.",
            "outcome": "interrupted",
        }  # fmt: skip
    )
    forge_code_store.write_conversation(p.root, conversation)
    path = thomas_project._live_file(p.root, p.cid)
    assert path.stat().st_size > megabytes * MB
    return p


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["running", "after_run_pending"])
async def test_a_big_record_whose_last_run_was_interrupted_is_carried_on(tmp_path: Path, state: str) -> None:
    p = _interrupted_big(tmp_path, state)
    found = _restart().survey(p.catalog, p.booted)
    assert [item.cid for item in found] == [p.cid], _restart().report()
    assert found[0].turn["role"] == "user" and found[0].after_run_pending
    app = _app(p.catalog, starts := [])
    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert report["resumed"] == [p.cid] and len(starts) == 1, report


def test_the_survey_keeps_every_field_and_only_the_tail_of_each_transcript(tmp_path: Path) -> None:
    p = _interrupted_big(tmp_path, "after_run_pending", megabytes=12)
    path = thomas_project._live_file(p.root, p.cid)
    whole = json.loads(path.read_text(encoding="utf-8"))
    cut = listing.read_conversation(path)
    tail = listing.TRANSCRIPT_TAIL_CHARS
    for kept, original in zip(cut["turns"], whole["turns"], strict=True):
        assert kept == {
            **original,
            **({"transcript": original["transcript"][-tail:]} if "transcript" in original else {}),
        }
    assert {k: v for k, v in cut.items() if k != "turns"} == {k: v for k, v in whole.items() if k != "turns"}


def test_the_survey_reads_a_big_record_in_bounded_memory(tmp_path: Path) -> None:
    p = _interrupted_big(tmp_path, "after_run_pending", megabytes=30)
    path = thomas_project._live_file(p.root, p.cid)
    tracemalloc.start()
    try:
        cut = listing.read_conversation(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert cut["turns"][-1]["outcome"] == "interrupted"
    assert peak < 12 * MB, f"reading {path.stat().st_size // MB} MB held {peak // MB} MB at once"


@pytest.mark.parametrize("failure", [MemoryError, RecursionError])
def test_a_record_the_survey_cannot_take_is_skipped_and_the_rest_carry_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[BaseException]
) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    big = _interrupted_big(tmp_path / "second", "after_run_pending")
    from thomas.forge.anvil.forge_code_conversations import _load_registry, _write_registry

    registry = _load_registry(p.catalog)
    registry[big.cid] = {"project_root": str(big.root), "settings": {}}
    _write_registry(p.catalog, registry)
    real = listing.read_conversation

    def read_conversation(path: Path) -> Any:
        if path == thomas_project._live_file(big.root, big.cid):
            raise failure()
        return real(path)

    monkeypatch.setattr(listing, "read_conversation", read_conversation)
    found: list[Any] = []
    for _ in range(_restart().READ_ATTEMPTS):
        try:
            found = _restart().survey(p.catalog, p.booted)
            break
        except (OSError, ValueError):  # what restart_pass retries
            continue
    assert [item.cid for item in found] == [p.cid]
    assert list(_restart().report()["unreadable"]) == [big.cid]
