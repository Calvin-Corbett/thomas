from __future__ import annotations

import json

import scripts.forge.gates.release_lane_policy as mod


def test_lane_policy_passes_for_dev_to_prod() -> None:
    result = mod.evaluate_lane_policy(
        base_branch="prod",
        head_branch="dev",
        required_base="prod",
        required_head="dev",
    )
    assert result["ok"] is True
    assert result["violations"] == []


def test_lane_policy_fails_when_head_is_not_dev() -> None:
    result = mod.evaluate_lane_policy(
        base_branch="prod",
        head_branch="feature/new-ui",
        required_base="prod",
        required_head="dev",
    )
    assert result["ok"] is False
    assert any("head branch must be 'dev'" in item for item in result["violations"])


def test_lane_policy_cli_json_strict_returns_nonzero(capsys) -> None:
    rc = mod.run(
        [
            "--base",
            "prod",
            "--head",
            "feature/unsafe",
            "--require-base",
            "prod",
            "--require-head",
            "dev",
            "--json",
            "--strict",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
