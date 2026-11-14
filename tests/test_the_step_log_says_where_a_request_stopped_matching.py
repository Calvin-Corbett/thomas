"""Every codex request notes in the step log which part first differs from the last request with its cache key.

On 2026-11-06 only 25% of Build's prompt tokens were served from cache while each call resent about 90% of the call
before it, and no Build run kept a copy of what it sent. Regression for thomas.core.request_drift and its call in
thomas.core.llm_streaming_codex._build_openai_codex_request.
"""

from __future__ import annotations

import json
import types

import pytest

from thomas.core import capture_context, request_drift
from thomas.core.llm_streaming_codex import _build_openai_codex_request

TOOLS = [{"type": "function", "function": {"name": "read", "description": "read a file", "parameters": {}}}]


@pytest.fixture(autouse=True)
def _fresh():
    request_drift.reset()
    yield
    request_drift.reset()


def _items(*texts: str) -> list[dict]:
    return [{"role": "user", "content": text} for text in texts]


def test_the_first_request_of_a_key_has_nothing_to_compare() -> None:
    assert request_drift.compare("k", TOOLS, "sys", _items("a")) == {}


def test_a_request_that_only_grows_at_the_end_changes_nothing() -> None:
    request_drift.compare("k", TOOLS, "sys", _items("a", "b"))
    verdict = request_drift.compare("k", TOOLS, "sys", _items("a", "b", "c"))
    assert verdict == {"items": 3, "items_before": 2, "first_change": "none"}


def test_it_names_the_first_part_that_changed() -> None:
    request_drift.compare("k", TOOLS, "sys", _items("a"))
    assert request_drift.compare("k", TOOLS, "other", _items("a"))["first_change"] == "instructions"
    assert request_drift.compare("k", [], "other", _items("a"))["first_change"] == "tools"
    request_drift.compare("k", [], "other", [{"type": "reasoning", "id": "r1"}, {"role": "user", "content": "a"}])
    verdict = request_drift.compare("k", [], "other", [{"role": "user", "content": "a"}])
    assert verdict["first_change"] == "item" and verdict["item"] == 0
    assert (verdict["was"], verdict["now"]) == ("reasoning", "user")


def test_items_taken_off_the_end_are_a_change() -> None:
    request_drift.compare("k", TOOLS, "sys", _items("a", "b"))
    verdict = request_drift.compare("k", TOOLS, "sys", _items("a"))
    assert verdict["first_change"] == "item" and verdict["item"] == 1 and verdict["now"] == "(nothing)"


def test_keys_are_compared_apart() -> None:
    request_drift.compare("run", TOOLS, "sys", _items("a"))
    assert request_drift.compare("helper", TOOLS, "other", _items("z")) == {}
    assert request_drift.compare("run", TOOLS, "sys", _items("a", "b"))["first_change"] == "none"


def test_a_codex_request_writes_its_verdict_and_no_prompt_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("THOMAS_STEP_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("THOMAS_STEP_LOG", raising=False)
    owner = types.SimpleNamespace(config=types.SimpleNamespace(model="gpt-test", reasoning_effort=""))
    token = capture_context.set_capture_run("run-drift")
    try:
        first = [{"role": "system", "content": "SECRET-SYSTEM"}, {"role": "user", "content": "SECRET-TASK"}]
        _build_openai_codex_request(owner, first, TOOLS)
        _build_openai_codex_request(owner, [*first, {"role": "assistant", "content": "SECRET-REPLY"}], TOOLS)
    finally:
        capture_context.reset(token)
    text = "".join(path.read_text(encoding="utf-8") for path in tmp_path.glob("steps-*.jsonl"))
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    requests = [row for row in rows if row["step"] == "request"]
    assert len(requests) == 1 and requests[0]["first_change"] == "none" and requests[0]["model"] == "gpt-test"
    assert requests[0]["key"].startswith("thomas-run-")
    assert "SECRET" not in text
