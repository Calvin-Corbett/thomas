from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.marketplace.specialists import tools as mod
from thomas.marketplace.specialists.tools import (
    _extract_main_headline_text,
    _extract_strict_output,
    _fetch_browser_main_text,
    _fetch_browser_title,
    _find_named_file_on_desktop,
    _normalize_requested_content,
    _parse_clock_time,
    _resolve_app_launch_target,
    _should_force_tool_first,
    _should_require_output_only,
)


def test_should_force_tool_first_matches_explicit_tool_requests() -> None:
    assert _should_force_tool_first("Use your tools to create a file in the repo.") is True
    assert _should_force_tool_first("Run a command and show me the output.") is True
    assert _should_force_tool_first("Open https://example-tool.org and answer with only the exact main headline.") is True
    assert _should_force_tool_first("Build me a game on my Desktop.") is False
    assert _should_force_tool_first("Tell me a joke about snakes.") is False


def test_should_require_output_only_matches_strict_output_prompts() -> None:
    assert _should_require_output_only("Answer with only the printed number.") is True
    assert _should_require_output_only("Reply with exactly the path.") is True
    assert _should_require_output_only("Explain what you are doing.") is False


def test_normalize_requested_content_strips_exactly_prefix() -> None:
    assert _normalize_requested_content("exactly SPEED_OK") == "SPEED_OK"
    assert _normalize_requested_content('"exactly quoted"') == "exactly quoted"
    assert _normalize_requested_content("PROBE_FILE_OK") == "PROBE_FILE_OK"


def test_parse_clock_time_supports_12_hour_inputs() -> None:
    assert _parse_clock_time("9:00 AM") == (9, 0)
    assert _parse_clock_time("12:15 AM") == (0, 15)
    assert _parse_clock_time("12:30 PM") == (12, 30)
    assert _parse_clock_time("7:45 PM") == (19, 45)


def test_resolve_app_launch_target_supports_known_aliases_and_exe_fallback() -> None:
    assert _resolve_app_launch_target("Notepad") == ("Notepad", "notepad.exe")
    assert _resolve_app_launch_target("calculator") == ("calculator", "calc.exe")
    assert _resolve_app_launch_target("AcmeTool") == ("AcmeTool", "AcmeTool.exe")


def test_find_named_file_on_desktop_prefers_direct_desktop_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    desktop = home / "Desktop"
    desktop.mkdir(parents=True)
    target = desktop / "search-fastpath-probe.txt"
    target.write_text("SEARCH_OK", encoding="utf-8")
    monkeypatch.setattr(mod.Path, "home", staticmethod(lambda: home))

    assert _find_named_file_on_desktop("search-fastpath-probe.txt") == target


def test_extract_strict_output_prefers_tool_facts_for_common_probe_shapes() -> None:
    assert (
        _extract_strict_output(
            "Use your tools to create calc.py, run it, then answer with only the printed number.",
            "The script is written. Running it now.323",
            ["323\r\n"],
        )
        == "323"
    )
    assert (
        _extract_strict_output(
            "Use your tools to create calc.py, run it, then answer with only the printed number.",
            "",
            ["runtime-workflow-test-codex-2026-04-03.txt\r\n", ""],
        )
        == ""
    )
    assert (
        _extract_strict_output(
            "Use your tools to open the page and answer with only the exact main headline on the page.",
            "Checking now.\nExampleSite: The AI that actually does things",
            ["ExampleSite: The AI that actually does things"],
        )
        == "ExampleSite: The AI that actually does things"
    )
    assert (
        _extract_strict_output(
            "Use your tools to open the page and answer with only the exact main headline on the page.",
            "I’m opening the page directly and checking the visible primary heading text.ExampleSite: The AI that actually does things",
            [],
        )
        == "ExampleSite: The AI that actually does things"
    )
    assert (
        _extract_strict_output(
            r"Use your tools to create the file D:\Desktop\probe.txt and answer with only the exact file path and contents.",
            "Wrote it.",
            ["PROBE_FILE_OK"],
        )
        == "D:\\Desktop\\probe.txt\nPROBE_FILE_OK"
    )
    assert (
        _extract_strict_output(
            r"Use your tools to create the file D:\Desktop\probe.txt containing PROBE_FILE_OK, then answer with only the exact file path and contents.",
            "Creating the requested probe file, then I'll return only the path and contents.",
            [],
        )
        == "D:\\Desktop\\probe.txt\nPROBE_FILE_OK"
    )
    assert (
        _extract_strict_output(
            r"Use your tools to create the file D:\Desktop\probe.txt containing PROBE_FILE_OK, then answer with only the full file path on one line and the file contents on the next line.",
            "",
            ["PROBE_FILE_OK"],
        )
        == "D:\\Desktop\\probe.txt\nPROBE_FILE_OK"
    )
    assert (
        _extract_strict_output(
            "Use your tools to create a recurring weekday 9:00 AM local reminder named Thomas Browser 9AM Test that shows the message THOMAS_9AM_OK. Do it now. If it works, answer with only OK. If it fails, answer with only FAIL: and the blocker.",
            "Thomas Browser 9AM Test Ready",
            ["Thomas Browser 9AM Test Ready"],
        )
        == "OK"
    )
    assert (
        _extract_strict_output(
            "Use your tools to create a recurring weekday 9:00 AM local reminder named Thomas Browser 9AM Test that shows the message THOMAS_9AM_OK. Do it now. If it works, answer with only OK. If it fails, answer with only FAIL: and the blocker.",
            "Connection failed after 3 attempts",
            [],
        )
        == "FAIL: Connection failed after 3 attempts"
    )


def test_extract_main_headline_text_prefers_h1_then_meta_then_title() -> None:
    assert (
        _extract_main_headline_text(
            "<html><head><title>Fallback Title</title></head><body><h1>ExampleSite: The AI that actually does things</h1></body></html>"
        )
        == "ExampleSite: The AI that actually does things"
    )
    assert (
        _extract_main_headline_text(
            '<html><head><meta property="og:title" content="ExampleSite Meta Title"><title>Fallback Title</title></head><body></body></html>'
        )
        == "ExampleSite Meta Title"
    )


@pytest.mark.asyncio
async def test_fetch_browser_title_prefers_title_then_headline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_execute(self, args):  # noqa: ANN001
        _ = self
        assert args["headline_only"] is True
        return SimpleNamespace(ok=True, data={"title": "ExampleSite Home", "headline": "Ignored Headline", "text": ""}, error=None)

    monkeypatch.setattr(mod.BrowserOpenTool, "execute", _fake_execute)

    assert await _fetch_browser_title("https://example-tool.org") == "ExampleSite Home"


@pytest.mark.asyncio
async def test_fetch_browser_title_retries_with_fresh_session_after_initial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_execute(self, args):  # noqa: ANN001
        _ = self
        calls.append(dict(args))
        if len(calls) == 1:
            return SimpleNamespace(ok=False, data=None, error="startup race")
        return SimpleNamespace(ok=True, data={"title": "ExampleSite Home", "headline": "", "text": ""}, error=None)

    monkeypatch.setattr(mod.BrowserOpenTool, "execute", _fake_execute)

    assert await _fetch_browser_title("https://example-tool.org") == "ExampleSite Home"
    assert [call["session"] for call in calls] == ["headline-read", "headline-read-retry"]
    assert all(call.get("headline_only") is True for call in calls)


@pytest.mark.asyncio
async def test_fetch_browser_main_text_prefers_extracted_text(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_execute(self, args):  # noqa: ANN001
        _ = self
        assert args["lane"] == "read"
        assert "headline_only" not in args
        return SimpleNamespace(
            ok=True,
            data={
                "title": "ExampleSite Home",
                "headline": "ExampleSite: The AI that actually does things",
                "text": "ExampleSite helps you automate local machine work quickly.",
            },
            error=None,
        )

    monkeypatch.setattr(mod.BrowserOpenTool, "execute", _fake_execute)

    assert (
        await _fetch_browser_main_text("https://example-tool.org")
        == "ExampleSite helps you automate local machine work quickly."
    )
