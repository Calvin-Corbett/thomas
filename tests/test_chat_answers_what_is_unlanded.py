"""Chat answers "what is still unlanded" from the ratchet's own records, through a read-only tool."""

from __future__ import annotations

import asyncio

from thomas.core.config import load_config
from thomas.server.app_helpers import _build_tools
from thomas.server.chat_tool_policy import _is_classified_tool
from thomas.server.chat_tool_policy_model import _SAFE_READ_TOOLS
from thomas.tools.self_unlanded import SelfUnlandedTool

REPORT = {
    "dev_sha": "d" * 40,
    "counts": {"awaiting_card": 1, "reported": 1, "not_for_ratchet": 1},
    "candidates": [
        {
            "sha": "a" * 40,
            "ref": "refs/heads/praxis/native-combined-20260913",
            "state": "awaiting_card",
            "reason": "waiting for your card",
        },
        {
            "sha": "b" * 40,
            "ref": "refs/heads/integration/unify-2026-08-14",
            "state": "reported",
            "reason": "the repair team did not finish: the run crashed",
        },
        {
            "sha": "c" * 40,
            "ref": "refs/remotes/origin/main",
            "state": "not_for_ratchet",
            "reason": "the public repository's history, which never goes to dev",
        },
    ],
}


def _ask(args: dict, report: dict = REPORT) -> str:
    result = asyncio.run(SelfUnlandedTool(lambda: report).execute(args))
    assert result.ok
    return str(result.data)


def test_it_says_what_is_unlanded_and_why() -> None:
    text = _ask({})

    assert text.startswith(f"Against dev {'d' * 12}: ")
    assert "waiting for your card" in text and "the repair team did not finish" in text
    assert "refs/remotes/origin/main" in text


def test_it_can_answer_for_one_state() -> None:
    text = _ask({"state": "reported"})

    assert "unify-2026-08-14" in text and "native-combined" not in text


def test_with_no_records_it_says_the_ratchet_has_not_run_here() -> None:
    assert "has no record here yet" in _ask({}, {"candidates": []})


def test_a_halt_is_said_first() -> None:
    halted = {**REPORT, "halted": {"reason": "1234 landed and broke tests/test_x.py::test_x"}}

    assert _ask({}, halted).startswith("The ratchet is stopped: 1234 landed and broke tests/test_x.py::test_x.")


def test_chat_has_the_tool_and_may_always_read_it() -> None:
    assert "self.unlanded" in _build_tools(load_config())
    assert "self.unlanded" in _SAFE_READ_TOOLS and _is_classified_tool("self.unlanded")
