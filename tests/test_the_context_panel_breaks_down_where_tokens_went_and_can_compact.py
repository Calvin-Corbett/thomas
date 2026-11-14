"""The context panel's numbers are real: where the tokens went, and a Compact button the loop honours."""

from __future__ import annotations

from pathlib import Path

from thomas.agent.context_breakdown import MAX_ROWS, context_breakdown
from thomas.forge.anvil import run_control

ROOT = Path(__file__).resolve().parents[1] / "thomas"


def _messages():
    return [
        {"role": "system", "content": "You are Thomas. " * 40},
        {"role": "user", "content": "get this game working please"},
        {
            "role": "assistant",
            "content": "On it.",
            "tool_calls": [{"id": "c1", "function": {"name": "read", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "file text " * 200},
        {"role": "assistant", "content": "Read it."},
    ]


def test_the_breakdown_names_each_part_and_the_tool_that_produced_a_result():
    rows = {row["label"]: row["tokens"] for row in context_breakdown(_messages(), 5000)}

    assert rows["Results of read"] > rows["Your messages"]
    assert rows["System prompt"] > 0 and rows["Thomas's replies"] > 0
    assert rows["Tool definitions"] > 0  # what the estimate carries beyond the messages


def test_the_rows_come_largest_first_and_never_run_past_the_limit():
    many = [
        {"role": "tool", "tool_call_id": f"t{i}", "name": f"tool{i}", "content": "x" * (100 * (i + 1))}
        for i in range(20)
    ]

    rows = context_breakdown(many, 0)

    assert len(rows) <= MAX_ROWS and rows[-1]["label"] == "Everything else"
    assert [r["tokens"] for r in rows[:-1]] == sorted((r["tokens"] for r in rows[:-1]), reverse=True)


def test_a_bad_breakdown_never_breaks_the_store_and_good_rows_survive(tmp_path):
    bad = [{"label": "ok", "tokens": 5}, {"label": 3, "tokens": 5}, {"label": "neg", "tokens": -1}, "x"]
    run_control.write_context(tmp_path, 100, 1000, bad)

    assert run_control.read_context(tmp_path)["breakdown"] == [{"label": "ok", "tokens": 5}]


def test_a_compaction_request_is_taken_once(tmp_path):
    assert run_control.take_compaction_request(tmp_path) is False
    run_control.request_compaction(tmp_path)

    assert run_control.take_compaction_request(tmp_path) is True
    assert run_control.take_compaction_request(tmp_path) is False


def test_the_chosen_window_is_kept_in_whole_25k_steps_and_clamped(tmp_path):
    assert run_control.read_context_cap(tmp_path) is None
    assert run_control.set_context_cap(tmp_path, 130_000) == 125_000  # rounds to the nearest step
    assert run_control.read_context_cap(tmp_path) == 125_000
    assert run_control.set_context_cap(tmp_path, 5_000) == 25_000  # never below one step
    assert run_control.set_context_cap(tmp_path, 9_000_000) == 2_000_000  # nor past the ceiling


def test_zero_or_nonsense_returns_to_the_models_own_window(tmp_path):
    run_control.set_context_cap(tmp_path, 300_000)

    assert run_control.set_context_cap(tmp_path, 0) is None
    assert run_control.read_context_cap(tmp_path) is None
    assert run_control.set_context_cap(tmp_path, "wide") is None


def test_the_profiles_own_window_is_kept_beside_the_one_in_force(tmp_path):
    run_control.write_context(tmp_path, 40_000, 500_000, [], 200_000)

    reading = run_control.read_context(tmp_path)
    assert reading["window"] == 500_000 and reading["model_window"] == 200_000
    run_control.write_context(tmp_path, 40_000, 200_000)  # nothing said: the one in force is the default
    assert run_control.read_context(tmp_path)["model_window"] == 200_000


def test_the_loop_asks_the_probe_and_the_runner_and_url_are_wired():
    loop = (ROOT / "agent" / "loop_core.py").read_text(encoding="utf-8")
    assert 'getattr(self, "run_directives_probe"' in loop and "if not forced and conv_tokens <" in loop
    assert "self._context_window = int(chosen)" in loop  # the window you chose is the loop's real window
    runner = (ROOT / "forge" / "anvil" / "dispatch_agent_loop.py").read_text(encoding="utf-8")
    assert "agent.run_directives_probe" in runner and "take_compaction_request" in runner
    assert "read_context_cap(control.directory)" in runner
    registration = (ROOT / "server" / "routes" / "evolve_agent_registration.py").read_text(encoding="utf-8")
    assert '("POST", "/api/evolve/agent/compact", "run_compact")' in registration
    assert '("POST", "/api/evolve/agent/context-window", "run_context_window")' in registration
    iteration = (ROOT / "agent" / "loop_execution.py").read_text(encoding="utf-8")
    assert '"context_breakdown": context_breakdown_of(messages, state.token_estimate)' in iteration
    assert "def context_breakdown_of(" in (ROOT / "agent" / "loop_turn_context.py").read_text(encoding="utf-8")
