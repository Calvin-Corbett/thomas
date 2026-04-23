import asyncio
import json
from pathlib import Path

from thomas.agent.loop import AgentLoop
from thomas.agent.skills_runtime import format_runtime_skills_context, resolve_runtime_skills
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.registry import ToolRegistry


class _CaptureLLM:
    def __init__(self, *, provider: str = "openai_compat") -> None:
        self.config = ModelConfig(
            name=f"dummy-{provider}",
            provider=provider,
            model="dummy",
            context_window=4096,
            max_tokens=128,
        )
        self.last_messages = []

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        self.last_messages = list(messages or [])
        _ = tools
        yield StreamEvent(type="token", data={"text": "done"})
        yield StreamEvent(type="done", data={})


def _write_skill(root: Path, name: str, description: str, *body_lines: str) -> None:
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join(body_lines) if body_lines else "- Follow the documented workflow."
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                f"# {name}",
                "",
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _build_cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "runtime")),
    )


def test_runtime_skills_selection_prefers_explicit_then_pinned(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.chdir(tmp_path)

    _write_skill(
        home_root / ".thomas", "explicit-skill", "Always use the explicit flow.", "- Keep changes deterministic."
    )
    _write_skill(
        home_root / ".thomas", "pinned-skill", "Always include the pinned behavior.", "- Preserve the pinned workflow."
    )
    _write_skill(home_root / ".thomas", "deploy-cloudflare", "Deploy Cloudflare workers carefully.", "- Verify routes.")

    state_path = cfg.memory.root_path / ".thomas" / "cli" / "skills.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"pinned": ["pinned-skill"]}, ensure_ascii=False), encoding="utf-8")

    selection = resolve_runtime_skills(
        cfg,
        prompt_text="please use $explicit-skill and deploy this cloudflare worker",
        relevance_text="deploy cloudflare worker release",
        route_path="coding_task",
        cwd=tmp_path,
        max_selected=3,
    )

    names = [s.name for s in selection.selected]
    assert len(names) >= 2
    assert names[0] == "explicit-skill"
    assert names[1] == "pinned-skill"
    reason_by_name = {s.name: selection.selected_reasons.get(s.key, "") for s in selection.selected}
    assert reason_by_name["explicit-skill"] == "explicit"
    assert reason_by_name["pinned-skill"] == "pinned"


def test_runtime_skills_context_format_includes_selected_instructions(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.chdir(tmp_path)

    _write_skill(
        home_root / ".thomas",
        "robot-ui",
        "Use live screenshots and verify before finishing.",
        "- Verify before finishing.",
    )
    selection = resolve_runtime_skills(
        cfg,
        prompt_text="use $robot-ui for this website pass",
        relevance_text="website verification",
        route_path="coding_task",
        cwd=tmp_path,
        max_selected=2,
    )
    ctx = format_runtime_skills_context(selection)
    assert "--- Runtime Skills ---" in ctx
    assert "robot-ui" in ctx
    assert "Verify before finishing" in ctx


def test_agent_loop_injects_runtime_skill_context_into_system_prompt(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.setenv("THOMAS_RUNTIME_SKILLS_ENABLED", "1")
    monkeypatch.chdir(tmp_path)

    _write_skill(home_root / ".thomas", "robot-theme", "Keep robot visuals consistent.", "- Reuse the sprite family.")

    llm = _CaptureLLM(provider="openai_compat")
    tools = ToolRegistry()
    agent = AgentLoop(cfg, llm, tools, conversation=[])

    async def _run_once():
        rows = []
        async for ev in agent.run("please use $robot-theme for this pass", tools_policy="never"):
            rows.append(ev)
        return rows

    events = asyncio.run(_run_once())
    start = next((e for e in events if e.type == EventType.AGENT_START), None)
    assert start is not None
    payload = start.data.get("skills") or {}
    assert int(payload.get("selected_count", 0) or 0) >= 1
    system_msg = llm.last_messages[0]
    assert str(system_msg.get("role")) == "system"
    text = str(system_msg.get("content") or "")
    assert "--- Runtime Skills ---" in text
    assert "robot-theme" in text


def test_runtime_skills_ignore_codex_roots_in_normal_discovery(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.chdir(tmp_path)

    _write_skill(home_root / ".codex", "codex-only-skill", "Legacy Codex skill.", "- This should not load.")
    selection = resolve_runtime_skills(
        cfg,
        prompt_text="please use $codex-only-skill",
        relevance_text="codex only skill",
        route_path="coding_task",
        cwd=tmp_path,
        max_selected=2,
    )
    assert all(".codex" not in root for root in selection.roots)
    assert "codex-only-skill" not in [s.name for s in selection.selected]


def test_runtime_skills_trust_project_local_skills_by_default(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.delenv("THOMAS_RUNTIME_SKILLS_TRUST_MODE", raising=False)
    monkeypatch.chdir(tmp_path)

    _write_skill(tmp_path, "trusted-cwd-skill", "Project-local Thomas skill.", "- Local skill.")
    selection = resolve_runtime_skills(
        cfg,
        prompt_text="please use $trusted-cwd-skill",
        relevance_text="",
        route_path="coding_task",
        cwd=tmp_path,
        max_selected=2,
    )
    assert "trusted-cwd-skill" in [s.name for s in selection.selected]
    assert not selection.blocked


def test_runtime_skills_require_explicit_for_risky_pinned_skills(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.setenv("THOMAS_RUNTIME_SKILLS_REQUIRE_EXPLICIT_RISK_APPROVAL", "1")
    monkeypatch.chdir(tmp_path)

    _write_skill(
        home_root / ".thomas",
        "deploy-prod",
        "Deploy production releases and touch billing/auth.",
        "- Deploy production release.",
        "- Update billing webhook and auth token.",
    )
    state_path = cfg.memory.root_path / ".thomas" / "cli" / "skills.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"pinned": ["deploy-prod"]}), encoding="utf-8")

    blocked = resolve_runtime_skills(
        cfg,
        prompt_text="ship the release now",
        relevance_text="deploy production release",
        route_path="coding_task",
        cwd=tmp_path,
        max_selected=2,
    )
    assert len(blocked.selected) == 0
    assert "risky_skill_requires_explicit_approval" in {str(item.get("code") or "") for item in (blocked.blocked or [])}

    allowed = resolve_runtime_skills(
        cfg,
        prompt_text="please use $deploy-prod now",
        relevance_text="deploy production release",
        route_path="coding_task",
        cwd=tmp_path,
        max_selected=2,
    )
    assert "deploy-prod" in [s.name for s in allowed.selected]
    assert "deploy-prod" in (allowed.approved_risky or [])


def test_runtime_skills_provider_conformance_same_selection_and_prompt(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.chdir(tmp_path)
    _write_skill(home_root / ".thomas", "robot-theme", "Keep robot visuals consistent.", "- Reuse the sprite family.")

    providers = ["openai_compat", "anthropic", "codex"]
    selected_sets = []
    prompt_snippets = []

    for _provider in providers:
        selection = resolve_runtime_skills(
            cfg,
            prompt_text="please use $robot-theme for this pass",
            relevance_text="robot theme",
            route_path="coding_task",
            cwd=tmp_path,
            max_selected=2,
        )
        selected_sets.append(tuple(sorted(skill.name for skill in selection.selected)))
        system_text = format_runtime_skills_context(selection)
        assert "--- Runtime Skills ---" in system_text
        assert "robot-theme" in system_text
        prompt_snippets.append(system_text.split("--- Runtime Skills ---", 1)[1][:220])

    assert len(set(selected_sets)) == 1
    assert len(set(prompt_snippets)) == 1


def test_runtime_skills_allows_unlimited_count_when_configured(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.delenv("THOMAS_RUNTIME_MAX_SKILLS", raising=False)
    monkeypatch.delenv("THOMAS_RUNTIME_MAX_SKILL_CHARS", raising=False)
    monkeypatch.chdir(tmp_path)

    for i in range(1, 6):
        _write_skill(home_root / ".thomas", f"big-skill-{i}", f"Big skill {i}.", f"- Step {i}.")

    selection = resolve_runtime_skills(
        cfg,
        prompt_text="please apply $big-skill-1, $big-skill-2, $big-skill-3, $big-skill-4, $big-skill-5",
        relevance_text="",
        route_path="coding_task",
        cwd=tmp_path,
        max_selected=0,
    )
    selected_names = [s.name for s in selection.selected]
    assert len(selected_names) == 5
    assert set(selected_names) == {f"big-skill-{i}" for i in range(1, 6)}


def test_runtime_skills_all_mode_and_unbounded_chars_env(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.setenv("THOMAS_RUNTIME_MAX_SKILLS", "all")
    monkeypatch.setenv("THOMAS_RUNTIME_MAX_SKILL_CHARS", "0")
    monkeypatch.setenv("THOMAS_RUNTIME_LOAD_ALL_SKILLS", "1")
    monkeypatch.chdir(tmp_path)

    for i in range(1, 7):
        _write_skill(home_root / ".thomas", f"long-skill-{i}", f"Long skill {i}.", "- " + "x " * 80)

    selection = resolve_runtime_skills(
        cfg,
        prompt_text="use all long-skill-1 long-skill-2 long-skill-3 long-skill-4 long-skill-5 long-skill-6",
        relevance_text="long skill",
        route_path="coding_task",
        cwd=tmp_path,
    )
    assert len(selection.selected) == 6
    assert {s.name for s in selection.selected} >= {f"long-skill-{i}" for i in range(1, 7)}
