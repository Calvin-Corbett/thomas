"""Tests for the evolve planner -- the autonomous cross-category target picker."""

from __future__ import annotations

from pathlib import Path

from thomas.forge.anvil.evolve_planner import (
    EvolveBacklog,
    normalize_focus,
    plan_backlog,
    render_backlog_markdown,
    risk_for_category,
)


def _scaffold_repo(tmp_path: Path) -> Path:
    """Build a synthetic Thomas tree that trips every detector."""
    thomas = tmp_path / "thomas"
    thomas.mkdir()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    # Oversized file -> refactor goal (over the 1500-line hard limit).
    (thomas / "big_module.py").write_text("\n".join(f"value_{i} = {i}" for i in range(1600)), encoding="utf-8")

    # Many broad exception handlers -> reliability goal (threshold is 8).
    flaky = ["def f():"]
    for i in range(10):
        flaky += ["    try:", f"        do_{i}()", "    except Exception:", "        pass"]
    (thomas / "flaky.py").write_text("\n".join(flaky), encoding="utf-8")

    # Security markers -> hardening goal (high risk).
    (thomas / "risky.py").write_text(
        "import subprocess, pickle, yaml, requests\n"
        "subprocess.run(cmd, shell=True)\n"
        "eval(expr)\n"
        "requests.get(url, verify=False)\n"
        "pickle.loads(blob)\n"
        "yaml.load(text)\n",
        encoding="utf-8",
    )

    # TODO/FIXME markers -> features goal (threshold is 5).
    (thomas / "wip.py").write_text("\n".join(f"# TODO: build feature {i}" for i in range(6)), encoding="utf-8")

    # xfail markers -> tests goal (threshold is 4).
    (tests_dir / "test_sample.py").write_text(
        "\n".join(f"@pytest.mark.xfail\ndef test_{i}():\n    assert True" for i in range(5)),
        encoding="utf-8",
    )
    return tmp_path


def test_plan_backlog_picks_across_all_categories(tmp_path):
    root = _scaffold_repo(tmp_path)
    backlog = plan_backlog(root, limit=20)
    assert isinstance(backlog, EvolveBacklog)
    categories = {g.category for g in backlog.goals}
    # The planner chose work in every dimension, not just skills/refactor.
    assert {"refactor", "reliability", "security", "tests", "features"} <= categories


def test_security_goal_is_high_risk_refactor_is_low():
    # Pure mapping check, independent of the scan.
    assert risk_for_category("security") == "high"
    assert risk_for_category("refactor") == "low"
    assert risk_for_category("tests") == "low"


def test_focus_boosts_matching_category_to_the_top(tmp_path):
    root = _scaffold_repo(tmp_path)
    focused = plan_backlog(root, focus="hardening", limit=20)
    assert focused.focus == "security"
    assert focused.top is not None
    assert focused.top.category == "security"


def test_category_allowlist_filters_backlog(tmp_path):
    root = _scaffold_repo(tmp_path)
    only_refactor = plan_backlog(root, categories={"refactor"}, limit=20)
    assert only_refactor.goals  # there is refactor work
    assert {g.category for g in only_refactor.goals} == {"refactor"}


def test_goals_carry_actionable_prompts_and_targets(tmp_path):
    root = _scaffold_repo(tmp_path)
    backlog = plan_backlog(root, limit=20)
    for goal in backlog.goals:
        assert goal.goal_prompt.strip(), "every goal needs an instruction for the engine"
        assert goal.id and ":" in goal.id
        assert goal.risk_tier in ("low", "medium", "high")
        assert 0.0 <= goal.leverage <= 1.0


def test_normalize_focus_maps_aliases():
    assert normalize_focus("hardening") == "security"
    assert normalize_focus("perf") == "efficiency"
    assert normalize_focus("UI") == "ux"
    assert normalize_focus("") == ""
    assert normalize_focus("banana") == ""


def test_healthy_repo_yields_empty_backlog(tmp_path):
    (tmp_path / "thomas").mkdir()
    (tmp_path / "thomas" / "clean.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    backlog = plan_backlog(tmp_path, limit=20)
    assert backlog.goals == []
    md = render_backlog_markdown(backlog)
    assert "healthy" in md.lower()


def test_backlog_roundtrips_through_dict(tmp_path):
    root = _scaffold_repo(tmp_path)
    backlog = plan_backlog(root, limit=20)
    restored = EvolveBacklog.from_dict(backlog.to_dict())
    assert [g.id for g in restored.goals] == [g.id for g in backlog.goals]
    assert restored.signals == backlog.signals
