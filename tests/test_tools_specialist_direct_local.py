from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_tools_specialist_support import _direct_token
from thomas.marketplace.specialists import tools as mod
from thomas.marketplace.specialists.tools import (
    ToolSpecialist,
)


async def test_direct_fast_path_writes_file_and_returns_exact_path_and_contents(tmp_path: Path) -> None:
    target = tmp_path / "probe.txt"
    specialist = ToolSpecialist(config=None, llm=None, tools=None)

    events = []
    async for event in specialist._run_direct_fast_path(
        f"Use your tools to create the file {target} containing PROBE_FILE_OK, then answer with only the exact file path and contents.",
        _direct_token(),
    ):
        events.append(event)

    assert target.read_text(encoding="utf-8") == "PROBE_FILE_OK"
    assert [event["type"] for event in events] == ["tool_start", "tool_result", "text", "done"]
    assert events[2]["text"] == f"{target}\nPROBE_FILE_OK"
    assert events[3]["content"] == f"{target}\nPROBE_FILE_OK"
async def test_direct_fast_path_writes_file_with_exactly_prefix_removed(tmp_path: Path) -> None:
    target = tmp_path / "probe-exactly.txt"
    specialist = ToolSpecialist(config=None, llm=None, tools=None)

    events = []
    async for event in specialist._run_direct_fast_path(
        f"Use your tools to create the file {target} containing exactly SPEED_OK, then answer with only the exact file path and contents.",
        _direct_token(),
    ):
        events.append(event)

    assert target.read_text(encoding="utf-8") == "SPEED_OK"
    assert [event["type"] for event in events] == ["tool_start", "tool_result", "text", "done"]
    assert events[2]["text"] == f"{target}\nSPEED_OK"
    assert events[3]["content"] == f"{target}\nSPEED_OK"
async def test_direct_fast_path_writes_file_and_stops_before_followup_sentence(tmp_path: Path) -> None:
    target = tmp_path / "probe-sentence-stop.txt"
    specialist = ToolSpecialist(config=None, llm=None, tools=None)

    events = []
    async for event in specialist._run_direct_fast_path(
        (
            f"Use your tools to create the file {target} containing exactly MISSION_UI_OK. "
            "Reply briefly and hand it to the task manager."
        ),
        _direct_token(),
    ):
        events.append(event)

    assert target.read_text(encoding="utf-8") == "MISSION_UI_OK"
    assert [event["type"] for event in events] == ["tool_start", "tool_result", "text", "done"]


@pytest.mark.asyncio
async def test_direct_fast_path_writes_file_and_honors_two_line_path_contents_prompt(tmp_path: Path) -> None:
    target = tmp_path / "probe-two-line.txt"
    specialist = ToolSpecialist(config=None, llm=None, tools=None)

    events = []
    async for event in specialist._run_direct_fast_path(
        (
            f"Use your tools to create the file {target} containing PROBE_FILE_OK, "
            "then answer with only the full file path on one line and the file contents on the next line."
        ),
        _direct_token(),
    ):
        events.append(event)

    assert target.read_text(encoding="utf-8") == "PROBE_FILE_OK"
    assert [event["type"] for event in events] == ["tool_start", "tool_result", "text", "done"]
    assert events[2]["text"] == f"{target}\nPROBE_FILE_OK"
    assert events[3]["content"] == f"{target}\nPROBE_FILE_OK"


@pytest.mark.asyncio
async def test_direct_fast_path_runs_python_probe_and_returns_number(tmp_path: Path) -> None:
    target = tmp_path / "probe_calc.py"
    specialist = ToolSpecialist(config=None, llm=None, tools=None)

    events = []
    async for event in specialist._run_direct_fast_path(
        f"Use your tools to create {target} that prints 17*19, run it, then answer with only the printed number.",
        _direct_token(),
    ):
        events.append(event)

    assert target.read_text(encoding="utf-8") == "print(17*19)\n"
    assert [event["type"] for event in events] == ["tool_start", "tool_result", "tool_start", "tool_result", "text", "done"]
    assert events[4]["text"] == "323"
    assert events[5]["content"] == "323"


@pytest.mark.asyncio
async def test_direct_fast_path_opens_app_and_returns_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    specialist = ToolSpecialist(config=None, llm=None, tools=None)
    seen: dict[str, object] = {}

    async def _fake_launch(app_name: str) -> str:
        seen["app_name"] = app_name
        return f"{app_name} opened"

    monkeypatch.setattr(mod, "_launch_local_application", _fake_launch)

    events = []
    async for event in specialist._run_direct_fast_path(
        "Use your tools to open Notepad, then answer with only OK.",
        _direct_token(),
    ):
        events.append(event)

    assert [event["type"] for event in events] == ["tool_start", "tool_result", "text", "done"]
    assert events[0]["name"] == "direct.open_app"
    assert events[0]["args"] == {"app": "Notepad"}
    assert events[1]["result"] == "Notepad opened"
    assert events[2]["text"] == "OK"
    assert events[3]["content"] == "OK"
    assert seen == {"app_name": "Notepad"}


@pytest.mark.asyncio
async def test_direct_fast_path_finds_file_on_desktop_and_returns_full_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specialist = ToolSpecialist(config=None, llm=None, tools=None)
    target = Path(r"D:\Desktop\search-fastpath-probe.txt")

    monkeypatch.setattr(mod, "_find_named_file_on_desktop", lambda name: target)

    events = []
    async for event in specialist._run_direct_fast_path(
        "Use your tools to find the file named search-fastpath-probe.txt on the Desktop, then answer with only the full file path.",
        _direct_token(),
    ):
        events.append(event)

    assert [event["type"] for event in events] == ["tool_start", "tool_result", "text", "done"]
    assert events[0]["name"] == "direct.find_file"
    assert events[0]["args"] == {"name": "search-fastpath-probe.txt", "scope": "Desktop"}
    assert events[1]["result"] == str(target)
    assert events[2]["text"] == str(target)
    assert events[3]["content"] == str(target)


@pytest.mark.asyncio
async def test_direct_fast_path_does_not_special_case_broad_game_build_requests() -> None:
    specialist = ToolSpecialist(config=None, llm=None, tools=None)

    events = []
    async for event in specialist._run_direct_fast_path(
        "Build me a game on my Desktop.",
        _direct_token(),
    ):
        events.append(event)

    assert events == []


@pytest.mark.asyncio
async def test_direct_fast_path_creates_weekday_reminder_and_honors_ok_fail_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specialist = ToolSpecialist(config=None, llm=None, tools=None)
    seen: dict[str, object] = {}

    async def _fake_create(task_name: str, message: str, *, time_text: str):  # noqa: ANN001
        seen["task_name"] = task_name
        seen["message"] = message
        seen["time_text"] = time_text
        return Path(r"D:\LocalApp\ThomasBrowser9AMTest.ps1"), f"{task_name} Ready"

    monkeypatch.setattr(mod, "_create_weekday_local_reminder", _fake_create)

    events = []
    async for event in specialist._run_direct_fast_path(
        (
            "Use your tools to create a recurring weekday 9:00 AM local reminder named "
            "Thomas Browser 9AM Test that shows the message THOMAS_9AM_OK. "
            "Do it now. If it works, answer with only OK. If it fails, answer with only FAIL: and the blocker."
        ),
        _direct_token(),
    ):
        events.append(event)

    assert [event["type"] for event in events] == ["tool_start", "tool_result", "tool_start", "tool_result", "text", "done"]
    assert events[0]["name"] == "direct.write_reminder_script"
    assert events[1]["result"] == r"D:\LocalApp\ThomasBrowser9AMTest.ps1"
    assert events[2]["name"] == "direct.schedule_task"
    assert events[3]["result"] == "Thomas Browser 9AM Test Ready"
    assert events[4]["text"] == "OK"
    assert events[5]["content"] == "OK"
    assert seen == {
        "task_name": "Thomas Browser 9AM Test",
        "message": "THOMAS_9AM_OK",
        "time_text": "9:00 AM",
    }
