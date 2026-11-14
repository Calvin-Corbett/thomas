from __future__ import annotations

from pathlib import Path

from thomas.agent import loop_execution
from thomas.agent.loop_execution_setup import ExecutionSetup, prepare_execution_setup
from thomas.agent.loop_provider_runtime import ProviderPromptWindow, projected_wait_seconds
from thomas.agent.loop_tool_protocol import (
    _canonical_code_tool_name,
    _failed_tool_signature,
    _tool_result_with_recovery,
)
from thomas.agent.loop_turn_context import prepare_turn_context

ROOT = Path(__file__).resolve().parent.parent


def test_loop_execution_stays_below_800_lines() -> None:
    source = ROOT / "thomas" / "agent" / "loop_execution.py"
    assert len(source.read_text(encoding="utf-8").splitlines()) < 800


def test_existing_helper_imports_remain_compatible() -> None:
    assert loop_execution._canonical_code_tool_name is _canonical_code_tool_name
    assert loop_execution._failed_tool_signature is _failed_tool_signature
    assert loop_execution._tool_result_with_recovery is _tool_result_with_recovery
    assert loop_execution._connection_error_message is not None
    assert loop_execution._TPM_WAIT_SLICE_SECONDS == 20.0


def test_setup_helpers_are_normal_imports() -> None:
    assert ExecutionSetup.__module__ == "thomas.agent.loop_execution_setup"
    assert prepare_execution_setup.__module__ == "thomas.agent.loop_execution_setup"
    assert prepare_turn_context.__module__ == "thomas.agent.loop_turn_context"


def test_provider_prompt_window_tracks_and_projects_usage(monkeypatch) -> None:
    ticks = iter((100.0, 100.0, 100.0, 101.0))
    monkeypatch.setattr("thomas.agent.loop_provider_runtime.time.monotonic", lambda: next(ticks))
    window = ProviderPromptWindow(100)

    assert window.record(40) == 40
    assert window.observed_average() == 40
    wait_seconds, projected, overage = window.projected_wait_seconds(70)
    assert wait_seconds == 60.0
    assert (projected, overage) == (110, 40)


def test_projected_wait_discards_expired_entries() -> None:
    entries = [(1.0, 75), (70.0, 20)]

    wait, projected, current = projected_wait_seconds(
        entries,
        prompt_budget=100,
        next_prompt_tokens=70,
        now_ts=80.0,
    )

    assert (wait, projected, current) == (0.0, 90, 20)
    assert entries == [(70.0, 20)]
