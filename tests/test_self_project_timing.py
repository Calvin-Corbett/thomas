"""The project list reports only durations bounded by persisted timestamps."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from thomas.server.routes.self_project_timing import add_timings


def _pending(tmp_path: Path, sid: str, **fields: object) -> None:
    outbox = tmp_path / "outbox"
    outbox.mkdir(exist_ok=True)
    (outbox / f"{sid}.pending.json").write_text(json.dumps(fields), encoding="utf-8")


def _stamp(second: int) -> str:
    return datetime.fromtimestamp(second, timezone.utc).isoformat()


def test_project_stage_times_and_today_slowest_use_only_recorded_intervals(tmp_path: Path) -> None:
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    first = int(datetime(2026, 10, 15, 10, tzinfo=timezone.utc).timestamp())
    folder = tmp_path / ".thomas" / "evolve" / "agent"
    folder.mkdir(parents=True)
    (folder / "hand_in_clocks.jsonl").write_text(
        json.dumps(
            {
                "conversation_id": "today",
                "stages": {
                    "check_for_hand_in": {"start": _stamp(first + 110), "end": _stamp(first + 140), "seconds": 30},
                    "second_look": {"start": _stamp(first + 140), "end": _stamp(first + 160), "seconds": 20},
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "conversation_id": "yesterday",
                "stages": {"check_for_hand_in": {"seconds": 3000}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    rows = [{"conversation_id": "today"}, {"conversation_id": "yesterday"}]
    conversations = {
        "today": {
            "turns": [
                {"role": "user", "ts": _stamp(first)},
                {"role": "agent", "ts": _stamp(first + 100), "run_id": "one"},
                {"role": "user", "ts": _stamp(first + 170), "text": "Autopilot: continuing: repair round"},
                {"role": "agent", "ts": _stamp(first + 190), "run_id": "two"},
            ]
        },
        "yesterday": {"turns": [{"role": "user", "ts": _stamp(first - 86400)}]},
    }
    result = add_timings(rows, conversations, tmp_path, now=now)
    assert rows[0]["timings_seconds"] == {
        "building": 100,
        "checks": 30,
        "second_look": 20,
        "repair_rounds": 20,
        "card_wait": None,
    }
    assert result["slowest_today"] == "Slowest today: building (100s measured)"


def test_done_check_run_is_not_counted_as_building(tmp_path: Path) -> None:
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    first = int(datetime(2026, 10, 15, 10, tzinfo=timezone.utc).timestamp())
    rows = [{"conversation_id": "check"}]
    conversations = {
        "check": {
            "turns": [
                {"role": "user", "ts": _stamp(first), "text": "Autopilot: continuing: done check"},
                {"role": "agent", "ts": _stamp(first + 90), "run_id": "check-run"},
            ]
        }
    }
    result = add_timings(rows, conversations, tmp_path, now=now)
    assert rows[0]["timings_seconds"]["building"] is None
    assert result["slowest_today"] is None


def test_missing_endpoints_are_not_invented(tmp_path: Path) -> None:
    rows = [{"conversation_id": "unfinished"}]
    conversations = {"unfinished": {"turns": [{"role": "user", "ts": _stamp(100)}]}}
    result = add_timings(rows, conversations, tmp_path)
    assert all(value is None for value in rows[0]["timings_seconds"].values())
    assert result["slowest_today"] is None


def test_today_uses_project_start_even_when_its_last_run_was_yesterday(tmp_path: Path) -> None:
    now = datetime(2026, 10, 15, 12, tzinfo=timezone(timedelta(hours=2)))
    started = datetime(2026, 10, 14, 23, tzinfo=timezone.utc)
    first = int(started.timestamp())
    rows = [{"conversation_id": "today"}]
    conversations = {
        "today": {
            "turns": [
                {"role": "user", "ts": _stamp(first)},
                {"role": "agent", "ts": _stamp(first + 20), "run_id": "one"},
                {"role": "user", "ts": _stamp(first + 3600), "text": "Autopilot: continuing: repair round"},
                {"role": "agent", "ts": _stamp(first + 3630), "run_id": "two"},
            ]
        }
    }
    result = add_timings(rows, conversations, tmp_path, now=now)
    assert rows[0]["timings_seconds"]["building"] == 20
    assert rows[0]["timings_seconds"]["repair_rounds"] == 30
    assert result["slowest_today"] == "Slowest today: repair rounds (30s measured)"


def test_multiple_hand_ins_add_only_their_measured_intervals(tmp_path: Path) -> None:
    folder = tmp_path / ".thomas" / "evolve" / "agent"
    folder.mkdir(parents=True)
    (folder / "hand_in_clocks.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "conversation_id": "project",
                    "stages": {
                        "check_for_hand_in": {"start": _stamp(first), "end": _stamp(first + span)},
                        "second_look": {"start": _stamp(first + span), "end": _stamp(first + span + 2)},
                    },
                }
            )
            for first, span in ((100, 3), (200, 5))
        )
        + "\n",
        encoding="utf-8",
    )
    rows = [{"conversation_id": "project"}]
    add_timings(rows, {"project": {}}, tmp_path)
    assert rows[0]["timings_seconds"]["checks"] == 8
    assert rows[0]["timings_seconds"]["second_look"] == 4


def test_card_wait_uses_only_persisted_prompt_intervals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("thomas.server.routes.self_project_timing.outbox_dir", lambda: tmp_path / "outbox")
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    first = int(datetime(2026, 10, 15, 10, tzinfo=timezone.utc).timestamp())
    _pending(
        tmp_path,
        "self-one",
        chat="project",
        card_prompts=[{"start": first + 10, "end": first + 40}, {"start": first + 50, "end": first + 140}],
    )
    _pending(tmp_path, "self-other", chat="other", card_prompts=[{"start": first, "end": first + 10000}])
    _pending(tmp_path, "self-incomplete", chat="other", card_prompts=[{"start": first + 150}])
    rows = [{"conversation_id": "project"}, {"conversation_id": "other"}]
    conversations = {
        "project": {
            "turns": [{"role": "user", "ts": _stamp(first)}],
            "thomas_project": {"submission": "self-one"},
        },
        "other": {
            "turns": [{"role": "user", "ts": _stamp(first)}],
            "thomas_project": {"submission": "self-incomplete"},
        },
    }
    result = add_timings(rows, conversations, tmp_path, now=now)
    assert rows[0]["timings_seconds"]["card_wait"] == 120
    assert rows[1]["timings_seconds"]["card_wait"] is None
    assert result["slowest_today"] == "Slowest today: waiting for your card (120s measured)"


def test_completed_card_wait_comes_from_final_verdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("thomas.server.routes.self_project_timing.outbox_dir", lambda: tmp_path / "outbox")
    folder = tmp_path / "outbox"
    folder.mkdir()
    (folder / "self-done.verdict.json").write_text(
        json.dumps({"chat": "project", "card_prompts": [{"start": 100, "end": 140}]}), encoding="utf-8"
    )
    rows = [{"conversation_id": "project"}]
    add_timings(rows, {"project": {"thomas_project": {"submission": "self-done"}}}, tmp_path)
    assert rows[0]["timings_seconds"]["card_wait"] == 40


def test_chat_started_project_card_wait_uses_chat_session_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("thomas.server.routes.self_project_timing.outbox_dir", lambda: tmp_path / "outbox")
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    first = int(datetime(2026, 10, 15, 10, tzinfo=timezone.utc).timestamp())
    _pending(
        tmp_path,
        "self-chat",
        chat="chat-session",
        card_prompts=[{"start": first + 30, "end": first + 150}],
    )
    rows = [{"conversation_id": "project"}]
    conversations = {
        "project": {
            "turns": [
                {"role": "user", "ts": _stamp(first)},
                {"role": "agent", "ts": _stamp(first + 40), "run_id": "build"},
            ],
            "thomas_project": {"submission": "self-chat", "chat_session_id": "chat-session"},
        }
    }
    result = add_timings(rows, conversations, tmp_path, now=now)
    assert rows[0]["timings_seconds"]["card_wait"] == 120
    assert result["slowest_today"] == "Slowest today: waiting for your card (120s measured)"


def test_card_wait_does_not_borrow_another_chats_final_verdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("thomas.server.routes.self_project_timing.outbox_dir", lambda: tmp_path / "outbox")
    folder = tmp_path / "outbox"
    folder.mkdir()
    (folder / "self-done.verdict.json").write_text(
        json.dumps({"chat": "other", "card_prompts": [{"start": 100, "end": 140}]}), encoding="utf-8"
    )
    rows = [{"conversation_id": "project"}]
    add_timings(rows, {"project": {"thomas_project": {"submission": "self-done"}}}, tmp_path)
    assert rows[0]["timings_seconds"]["card_wait"] is None


def test_card_wait_rejects_partial_and_implausible_prompts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("thomas.server.routes.self_project_timing.outbox_dir", lambda: tmp_path / "outbox")
    _pending(
        tmp_path,
        "self-one",
        chat="project",
        card_prompts=[
            {"start": 42},
            {"start": 50, "end": 49},
            {"start": "60", "end": 70},
            {"start": 80, "end": 80 + 86401},
        ],
    )
    rows = [{"conversation_id": "project"}]
    add_timings(rows, {"project": {"thomas_project": {"submission": "self-one"}}}, tmp_path)
    assert rows[0]["timings_seconds"]["card_wait"] is None


def test_clock_seconds_without_two_endpoints_do_not_count(tmp_path: Path) -> None:
    folder = tmp_path / ".thomas" / "evolve" / "agent"
    folder.mkdir(parents=True)
    (folder / "hand_in_clocks.jsonl").write_text(
        json.dumps({"conversation_id": "project", "stages": {"check_for_hand_in": {"seconds": 123}}}),
        encoding="utf-8",
    )
    rows = [{"conversation_id": "project"}]
    add_timings(rows, {"project": {}}, tmp_path)
    assert rows[0]["timings_seconds"]["checks"] is None
