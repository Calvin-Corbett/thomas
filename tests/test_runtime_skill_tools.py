from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from tests.test_agent_skills_runtime import _build_cfg, _write_skill
from thomas.agent.runtime_skill_tools import ListRuntimeSkillsTool, UseRuntimeSkillTool
from thomas.agent.skills_runtime import resolve_runtime_skills
from thomas.marketplace.specialists.reasoning_context import read_tool_specs


def _prepare(tmp_path: Path, monkeypatch) -> tuple[object, Path]:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.chdir(tmp_path)
    return cfg, home_root


def test_model_can_list_and_load_an_exact_trusted_skill(tmp_path: Path, monkeypatch) -> None:
    cfg, home_root = _prepare(tmp_path, monkeypatch)
    _write_skill(home_root / ".thomas", "chart-craft", "Build clear charts.", "- Preserve supplied data.")

    listed = asyncio.run(ListRuntimeSkillsTool(cfg, tmp_path).safe_execute({}))
    loaded = asyncio.run(UseRuntimeSkillTool(cfg, tmp_path).safe_execute({"name": "chart-craft"}))

    assert listed.ok
    assert "chart-craft" in {row["name"] for row in listed.data["skills"]}
    assert loaded.ok
    assert "Preserve supplied data" in loaded.data["instructions"]


def test_keyword_environment_switch_cannot_select_a_skill(tmp_path: Path, monkeypatch) -> None:
    cfg, home_root = _prepare(tmp_path, monkeypatch)
    monkeypatch.setenv("THOMAS_RUNTIME_SKILLS_AUTO_RELEVANCE", "1")
    _write_skill(home_root / ".thomas", "chart-craft", "Build clear charts.", "- Preserve supplied data.")

    selection = resolve_runtime_skills(
        cfg,
        prompt_text="make me a chart",
        relevance_text="chart craft",
        route_path="coding_task",
        cwd=tmp_path,
    )

    assert selection.selected == []


def test_ordinary_prose_cannot_select_or_approve_a_named_skill(tmp_path: Path, monkeypatch) -> None:
    cfg, home_root = _prepare(tmp_path, monkeypatch)
    _write_skill(home_root / ".thomas", "chart-craft", "Build clear charts.", "- Preserve supplied data.")

    for prompt in (
        "please use the skill chart-craft",
        "I approve chart-craft for this task",
        "I authorize all chart skills",
    ):
        selection = resolve_runtime_skills(
            cfg,
            prompt_text=prompt,
            relevance_text="chart craft",
            route_path="coding_task",
            cwd=tmp_path,
        )
        assert selection.selected == []


def test_high_risk_skill_requires_literal_user_invocation(tmp_path: Path, monkeypatch) -> None:
    cfg, home_root = _prepare(tmp_path, monkeypatch)
    _write_skill(
        home_root / ".thomas",
        "production-deploy",
        "Deploy and delete production resources.",
        "- Delete the prior production deployment.",
    )

    loaded = asyncio.run(UseRuntimeSkillTool(cfg, tmp_path).safe_execute({"name": "production-deploy"}))

    assert not loaded.ok
    assert "$production-deploy" in str(loaded.error)


def test_chat_reasoning_exposes_structured_skill_choice_to_the_model() -> None:
    tools = {
        name: SimpleNamespace(
            name=name,
            description=name,
            parameters={"type": "object", "properties": {}},
        )
        for name in ("skills.list", "skills.use")
    }
    registry = SimpleNamespace(get=tools.get)

    offered = {spec["function"]["name"] for spec in read_tool_specs(registry)}

    assert offered == {"skills.list", "skills.use"}
