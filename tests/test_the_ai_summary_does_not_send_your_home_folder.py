"""The summary Boot Doctor asks your model for shows your home folder as ``~``.

The findings now carry absolute paths (the config file, the data folders, each database) and the last lines of the
startup log, all of which contain the account name when they sit under your home folder. The model is only told what
it needs: where the fault is, not whose account it is on.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.core import boot_ai_summary
from thomas.core.config import ModelConfig

HOME = r"C:\Users\alice"


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the model client with one that records the prompt it is handed."""
    prompts: list[str] = []

    class FakeClient:
        def __init__(self, cfg, failover_enabled: bool = False) -> None:
            pass

        def stream_chat(self, messages, tools=None):
            prompts.append(messages[-1]["content"])
            return self._events()

        async def _events(self):
            yield SimpleNamespace(type="token", data={"text": "a summary"})

        async def close(self) -> None:
            pass

    monkeypatch.setattr(boot_ai_summary, "LLMClient", FakeClient)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path(HOME)))
    return prompts


def _finding(detail: str) -> SimpleNamespace:
    return SimpleNamespace(status="fail", check="database_integrity", detail=detail)


def _summary(findings: list[SimpleNamespace], *, reason: str = "runtime not detected", repairs=()) -> str:
    cfg = ModelConfig(name="m", provider="local", model="stub")
    return asyncio.run(
        boot_ai_summary.ai_boot_summary(model_cfg=cfg, reason=reason, findings=findings, repairs=list(repairs))
    )


def test_your_home_folder_is_not_in_the_prompt_and_the_rest_of_the_path_is(sent: list[str]) -> None:
    detail = rf"{HOME}\Thomas\runtime\.thomas\runs.sqlite3: file is not a database"

    assert _summary([_finding(detail)]) == "a summary"

    (prompt,) = sent
    assert "alice" not in prompt
    assert r"~\Thomas\runtime\.thomas\runs.sqlite3: file is not a database" in prompt


@pytest.mark.parametrize(
    "spelling",
    [
        "C:/Users/alice/Thomas/thomas.toml",
        r"c:\users\ALICE\Thomas\thomas.toml",
        "File 'C:\\\\Users\\\\alice\\\\Thomas\\\\thomas.toml', line 3",
    ],
)
def test_every_spelling_of_the_home_folder_is_hidden(sent: list[str], spelling: str) -> None:
    _summary([_finding(spelling)])

    assert "alice" not in sent[0].lower()
    assert "~" in sent[0]


def test_the_log_tail_and_the_repairs_and_the_reason_are_hidden_too(sent: list[str]) -> None:
    tail = rf'last lines of the probe log:\n    File "{HOME}\Thomas\thomas\server\app.py", line 9'

    _summary(
        [_finding(tail)],
        reason=rf"start failed in {HOME}\Thomas",
        repairs=[rf"Startup probe failed. Log: {HOME}\Thomas\runtime\probe.log"],
    )

    assert "alice" not in sent[0]


def test_a_sibling_folder_that_only_starts_with_the_same_name_is_left_alone(sent: list[str]) -> None:
    _summary([_finding(rf"{HOME}2\Thomas\thomas.toml and {HOME}\Thomas\thomas.toml")])

    assert rf"{HOME}2\Thomas\thomas.toml and ~\Thomas\thomas.toml" in sent[0]


def test_text_without_your_home_folder_is_sent_unchanged(sent: list[str]) -> None:
    _summary([_finding(r"D:\Thomas\runtime\.thomas\runs.sqlite3: file is not a database")])

    assert r"D:\Thomas\runtime\.thomas\runs.sqlite3: file is not a database" in sent[0]


def test_a_home_folder_that_cannot_be_found_leaves_the_text_as_it_is(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_home(cls) -> Path:
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "home", classmethod(no_home))

    assert boot_ai_summary.hide_home_folder(r"C:\Users\alice\x") == r"C:\Users\alice\x"
