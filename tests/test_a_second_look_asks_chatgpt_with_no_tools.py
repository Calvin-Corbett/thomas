"""A second look is one plain ChatGPT call with no tools, and anything but an answer is no verdict (2026-10-25).

A fake client stands in for ChatGPT: these tests never call the real model.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest
from scripts.cage import window_review as wr

from thomas.core import chatgpt_review as cr
from thomas.server.precard import clocks, review, review_job


class FakeClient:
    answer: dict[str, Any] = {"text": "", "tool_calls": []}
    error: Exception | None = None
    delay: float = 0.0
    seen: list[dict[str, Any]] = []

    def __init__(self, config: Any, **kwargs: Any) -> None:
        FakeClient.seen.append({"config": config, "kwargs": kwargs})

    async def chat(self, messages: list[dict[str, Any]], tools: Any = None) -> dict[str, Any]:
        FakeClient.seen[-1].update(messages=messages, tools=tools)
        if FakeClient.delay:
            await asyncio.sleep(FakeClient.delay)
        if FakeClient.error is not None:
            raise FakeClient.error
        return FakeClient.answer


@pytest.fixture(autouse=True)
def fake(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    FakeClient.answer, FakeClient.error, FakeClient.delay, FakeClient.seen = (
        {"text": "", "tool_calls": []},
        None,
        0.0,
        [],
    )
    monkeypatch.setattr(cr, "LLMClient", FakeClient)
    return FakeClient


def _body(out: str) -> dict[str, Any]:
    data = json.loads(out)
    assert data["type"] == "result"
    return data


def test_an_answer_comes_back_as_a_result_with_no_tools_offered(fake: type[FakeClient]) -> None:
    fake.answer = {"text": '{"verdict": "SAFE", "findings": []}', "tool_calls": []}
    code, out = cr.ask("the prompt", model="gpt-6.1-sol", effort="high", timeout=5)
    assert code == 0 and _body(out) == {"type": "result", "is_error": False, "result": fake.answer["text"]}
    [call] = fake.seen
    assert call["tools"] is None and call["messages"] == [{"role": "user", "content": "the prompt"}]
    assert call["config"].provider == "openai_codex" and call["config"].model == "gpt-6.1-sol"
    assert call["kwargs"] == {"fallback_configs": [], "failover_enabled": False}, "no other model may answer"


@pytest.mark.parametrize(
    ("answer", "error", "why"),
    [
        ({"text": "x", "tool_calls": [{"id": "1", "name": "shell", "arguments": "{}"}]}, None, "asked for a tool"),
        ({"text": "  ", "tool_calls": []}, None, "answered with nothing"),
        (None, RuntimeError("ChatGPT OAuth is not connected."), "OAuth is not connected"),
    ],
    ids=["tool call", "empty", "signed out"],
)
def test_anything_but_an_answer_is_an_error(
    fake: type[FakeClient], answer: dict[str, Any] | None, error: Exception | None, why: str
) -> None:
    fake.answer, fake.error = answer or {}, error
    code, out = cr.ask("p", timeout=5)
    body = _body(out)
    assert code != 0 and body["is_error"] is True and why in body["result"]


def test_no_answer_in_time_is_a_timeout(fake: type[FakeClient]) -> None:
    fake.delay = 1.0
    code, out = cr.ask("p", timeout=0.05)
    assert code == 124 and "did not answer within" in _body(out)["result"]


def test_a_cancelled_check_cancels_the_direct_request_and_keeps_its_clock(tmp_path, monkeypatch):
    started = threading.Event()
    stopped = threading.Event()

    async def chat(self, messages, tools=None):
        started.set()
        try:
            await asyncio.sleep(5)
        finally:
            stopped.set()

    monkeypatch.setattr(FakeClient, "chat", chat)
    with review_job.cancellable() as cancel, clocks.recording(tmp_path, "direct") as record:
        trigger = threading.Thread(target=lambda: (started.wait(2), cancel.set()))
        trigger.start()
        try:
            with pytest.raises(review_job.Cancelled):
                review.run_reviewer(["chatgpt", cr.DEFAULT_MODEL, cr.DEFAULT_EFFORT], str(tmp_path), "p", 0.5)
        finally:
            trigger.join(timeout=3)
    assert started.is_set() and stopped.is_set()
    assert record["stages"]["second_look_cli"]["seconds"] < 0.5


@pytest.mark.parametrize("read", [wr.changed_files, review.changed_files_text], ids=["window", "precard"])
def test_no_file_outside_the_copy_reaches_the_prompt(tmp_path: Path, read: Any) -> None:
    copy, secret = tmp_path / "copy", tmp_path / "secret.txt"
    copy.mkdir()
    secret.write_text("PRIVATE", encoding="utf-8")
    (copy / "ok.py").write_text("FINE = 1\n", encoding="utf-8")
    names = ["ok.py", secret.as_posix(), "../secret.txt"]
    try:
        os.symlink(secret, copy / "link.py")
        names.append("link.py")
    except OSError:  # Windows lets an unprivileged account make no links; the other names still prove the rule
        pass
    diff = "".join(f"diff --git a/{name} b/{name}\n+x\n" for name in names)
    text = read(copy, diff)
    assert "FINE = 1" in text and "PRIVATE" not in text
