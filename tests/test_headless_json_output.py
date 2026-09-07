"""Headless chat can answer as one JSON object (frontier parity: claude -p --output-format json, codex exec --json).

``python -m thomas.cli.headless_run --json "prompt"`` runs the same chat, keeps
the streamed text off stdout, and prints one line: the reply, the run-log
record's outcome and model, and the exit code. Scripts and the scheduler can
read it without scraping ANSI-decorated output.
"""

from __future__ import annotations

import json

from thomas.cli.headless_run import json_result, split_json_flag, strip_decorations


def test_the_streamed_decorations_are_stripped_and_the_reply_kept() -> None:
    captured = (
        "\x1b[90m[route auto, tools=on, autonomy=L3 full]\x1b[0m\n"
        "\x1b[90m[calling fs.read_file...]\x1b[0m ok\n"
        "\n\x1b[90m[iteration 2]\x1b[0m\n"
        "The answer is **42**.\nSecond line.\n"
    )
    assert strip_decorations(captured) == "ok\nThe answer is **42**.\nSecond line."


def test_json_result_carries_the_record_the_reply_and_the_exit_code() -> None:
    record = {
        "outcome": "success",
        "exit_code": 0,
        "model_profile": "codex",
        "model": "gpt-5.6-sol",
        "duration_s": 3.2,
        "error": "",
        "artifacts": ["out/report.md"],
        "prompt": "hi",
        "timestamp": "2026-09-05T14:00:00+00:00",
    }
    out = json.loads(json_result(captured="pong\n", record=record, exit_code=0))
    assert out == {
        "ok": True,
        "exit_code": 0,
        "outcome": "success",
        "model_profile": "codex",
        "model": "gpt-5.6-sol",
        "duration_s": 3.2,
        "reply": "pong",
        "verification": None,
        "tokens": None,
        "runtime_model": "",
        "tool_log": [],
        "checks": None,
        "iterations": None,
        "tool_calls": None,
        "error": "",
        "artifacts": ["out/report.md"],
    }
    failed = json.loads(json_result(captured="", record=None, exit_code=1))
    assert failed["ok"] is False and failed["exit_code"] == 1 and failed["reply"] == ""
    assert failed["outcome"] == "" and failed["artifacts"] == []


def test_the_json_flag_is_taken_out_of_the_chat_arguments() -> None:
    assert split_json_flag(["--json", "hello", "-m", "codex"]) == (True, ["hello", "-m", "codex"])
    assert split_json_flag(["hello", "--json"]) == (True, ["hello"])
    assert split_json_flag(["hello"]) == (False, ["hello"])


def test_the_clis_summary_lines_become_fields_not_reply_text() -> None:
    """A real run (2026-09-05 14:3xZ) put the verification line, the token line and
    the runtime line inside ``reply``; scripts want them as fields."""
    captured = """pong
Verification: 2/2 checks passed.
[tokens: 13128 prompt + 146 completion = 13274 total]
[runtime model: openai_codex/gpt-5.6-sol]
"""
    out = json.loads(json_result(captured=captured, record={"outcome": "success"}, exit_code=0))
    assert out["reply"] == "pong"
    assert out["verification"] == {"passed": 2, "total": 2}
    assert out["tokens"] == {"prompt": 13128, "completion": 146, "total": 13274}
    assert out["runtime_model"] == "openai_codex/gpt-5.6-sol"
    plain = json.loads(json_result(captured="hello", record=None, exit_code=0))
    assert plain["verification"] is None and plain["tokens"] is None and plain["runtime_model"] == ""


def test_tool_trace_checks_and_counts_are_fields_not_reply_text() -> None:
    """A real headless browser run (2026-09-05 16:00Z) put four tool lines, an
    Unchecked block and the iteration count inside ``reply``."""
    captured = """[shell.exec: failed 78ms]
{"ok": false, "error": "Exit code 255", "output": "[stderr] not recognized"}
[shell.exec: failed 265ms]
{"ok": false, "error": "Exit code 1", "output": "ParserError"}
[shell.exec: ok 109ms]
[eng.web_extract: ok 578ms]
Example Domain
Unchecked (no evidence either way):
- Open https://example.com in the browser and reply with only the page's title text.
(5 iterations, 4 tool calls)
"""
    out = json.loads(json_result(captured=captured, record={"outcome": "success"}, exit_code=0))
    assert out["reply"] == "Example Domain"
    assert [t["tool"] for t in out["tool_log"]] == ["shell.exec", "shell.exec", "shell.exec", "eng.web_extract"]
    assert [t["ok"] for t in out["tool_log"]] == [False, False, True, True]
    assert out["tool_log"][0]["ms"] == 78 and out["tool_log"][0]["detail"]["error"] == "Exit code 255"
    assert out["tool_log"][2]["detail"] is None
    assert out["checks"] == {
        "verified": [],
        "unchecked": ["Open https://example.com in the browser and reply with only the page's title text."],
    }
    assert out["iterations"] == 5 and out["tool_calls"] == 4
    plain = json.loads(json_result(captured="hello", record=None, exit_code=0))
    assert plain["tool_log"] == [] and plain["checks"] is None and plain["iterations"] is None
