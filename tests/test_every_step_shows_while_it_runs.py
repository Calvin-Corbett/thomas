"""A Build team's step is visible while it runs, and a missed edit says where the text is (2026-10-26).

You asked: "be more watchful of him you should be able to see every single thing he is doing at any moment". The
transcript held only finished steps, so a 10-minute test run was silence until it ended: the translator now writes a
``tool_started`` line when a tool call is complete, which the Code page leaves out (its result is the row). Three
teams in an hour each missed the same ``diff.create`` three times or more, editing from a reading their own earlier
edits had changed; the miss now shows the closest text in the file.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from thomas.core.events import EventType
from thomas.forge.anvil.dispatch_agent_loop_translator import _AgentLoopForgeTranslator
from thomas.tools.diff import CreateDiffTool

REPO_ROOT = Path(__file__).resolve().parents[1]


def _translate(feed: list[tuple[EventType, dict[str, Any]]]) -> list[dict[str, Any]]:
    emitted: list[dict[str, Any]] = []
    translator = _AgentLoopForgeTranslator(emitted.append)
    for kind, data in feed:
        translator.feed(kind.value, data)
    return emitted


def test_a_step_is_written_when_it_starts_and_its_result_still_names_its_command() -> None:
    emitted = _translate([
        (EventType.TOOL_CALL_START, {"tool_id": "t1", "tool_name": "shell.exec"}),
        (EventType.TOOL_CALL_ARGS_DELTA, {"tool_id": "t1", "delta": '{"command": "python -m pytest tests/test_x.py"}'}),
        (EventType.TOOL_CALL_END, {"tool_id": "t1"}),
        (EventType.TOOL_RESULT, {"tool_id": "t1", "tool_name": "shell.exec", "result": "3 passed", "ok": True}),
    ])  # fmt: skip
    kinds = [event.get("fc") for event in emitted]
    assert kinds.index("tool_started") < kinds.index("tool_result"), kinds
    started = next(event for event in emitted if event.get("fc") == "tool_started")
    assert started["name"] == "shell.exec" and "pytest tests/test_x.py" in started["text"]
    result = next(event for event in emitted if event.get("fc") == "tool_result")
    assert "pytest tests/test_x.py" in result.get("command", ""), "the start leaves the arguments to the result too"


def test_the_code_page_shows_the_result_and_not_the_start() -> None:
    out = subprocess.run(
        ["node", str(REPO_ROOT / "tests" / "web_node" / "code_tool_started_is_not_a_row.mjs"),
         str(REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_events.js")],
        capture_output=True, check=False, text=True, encoding="utf-8", timeout=30,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr
    html = json.loads(out.stdout)["html"]
    assert "STARTED-ONLY-MARKER" not in html and "RESULT-MARKER" in html


def test_a_missed_edit_shows_the_closest_text_with_its_line(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import os\n\n\ndef start(port):\n    serve(port=port, host='0.0.0.0')\n", "utf-8")
    result = asyncio.run(
        CreateDiffTool(tmp_path).execute(
            {
                "file": "app.py",
                "old_str": "def start(port):\n    serve(port)\n",
                "new_str": "def start(port):\n    pass\n",
            }
        )
    )
    assert not result.ok and "old_str not found in app.py" in str(result.error)
    assert "closest text in the file now" in str(result.error)
    assert "     4\tdef start(port):" in str(result.error) and "serve(port=port" in str(result.error)


def test_a_miss_with_nothing_close_says_only_not_found(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x = 1\n", "utf-8")
    result = asyncio.run(
        CreateDiffTool(tmp_path).execute({"file": "app.py", "old_str": "completely different\n", "new_str": "y\n"})
    )
    assert not result.ok and "closest text" not in str(result.error)


def test_a_provider_that_streams_no_argument_deltas_still_shows_the_step(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """On 2026-10-26 every ``tool_started`` line one provider wrote read ``{}``: it sends a call's arguments whole
    with its end and none as deltas, so the start knew the tool and not what it was doing. Run through the real loop."""
    from tests.test_agent_loop_tool_streaming import _SlowEchoTool, _TwoToolLLM
    from thomas.agent.loop import AgentLoop
    from thomas.core.config import AppConfig, ModelConfig
    from thomas.tools.registry import ToolRegistry

    monkeypatch.chdir(tmp_path)
    tools = ToolRegistry()
    tools.register(_SlowEchoTool())
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    agent = AgentLoop(cfg, _TwoToolLLM(), tools, conversation=[])

    async def run_once() -> list[dict[str, Any]]:
        emitted: list[dict[str, Any]] = []
        translator = _AgentLoopForgeTranslator(emitted.append)
        async for event in agent.run("run both tools", tools_policy="always"):
            translator.feed(event.type.value, event.data)
        return emitted

    started = [event for event in asyncio.run(run_once()) if event.get("fc") == "tool_started"]
    assert [event["name"] for event in started] == ["slow.echo", "slow.echo"]
    assert "0.05" in started[0]["text"] and "0.2" in started[1]["text"], started
