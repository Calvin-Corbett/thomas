from __future__ import annotations

import scripts.forge.gates.openclaw_metric_parity_gate as gate


def _result_fixture(*, top_delta: int = 0, browser_delta: int = 0) -> dict:
    openclaw_top = 44
    openclaw_depth = {"browser": 43, "gateway": 13}
    thomas_depth = {
        "browser": openclaw_depth["browser"] + int(browser_delta),
        "gateway": openclaw_depth["gateway"] + 5,
    }
    return {
        "cli": {
            "thomas_top_level_commands": openclaw_top + int(top_delta),
            "openclaw_top_level_commands": openclaw_top,
            "thomas_depth_total": sum(thomas_depth.values()),
            "openclaw_depth_total": sum(openclaw_depth.values()),
            "thomas_subcommand_depth": thomas_depth,
            "openclaw_subcommand_depth": openclaw_depth,
        }
    }


def test_openclaw_metric_parity_gate_passes_when_all_metrics_meet_or_exceed():
    parity = gate._evaluate_cli_parity(_result_fixture(top_delta=3, browser_delta=0))
    assert parity["ok"] is True
    assert parity["summary"]["failed_checks"] == 0


def test_openclaw_metric_parity_gate_fails_when_browser_depth_is_below_baseline():
    parity = gate._evaluate_cli_parity(_result_fixture(top_delta=5, browser_delta=-9))
    assert parity["ok"] is False
    metrics = {row["metric"] for row in parity["failures"]}
    assert "cli.depth.browser" in metrics


def test_openclaw_metric_parity_gate_fails_when_top_level_command_count_is_below_baseline():
    parity = gate._evaluate_cli_parity(_result_fixture(top_delta=-1, browser_delta=0))
    assert parity["ok"] is False
    metrics = {row["metric"] for row in parity["failures"]}
    assert "cli.top_level_commands" in metrics

