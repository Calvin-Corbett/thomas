import asyncio
import json
from pathlib import Path

from thomas.agent.loop import AgentLoop
from thomas.agent.skills_runtime import (
    format_runtime_skills_context,
    resolve_runtime_skills,
)
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


def _write_skill(root: Path, name: str, body: str) -> None:
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")


def _build_cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "runtime")),
    )


def test_runtime_skills_selection_prefers_explicit_then_pinned(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    codex_home = tmp_path / "codex-home"
    home_root.mkdir(parents=True, exist_ok=True)
    codex_home.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.delenv("THOMAS_SKILLS_EXTRA_DIRS", raising=False)

    _write_skill(
        codex_home,
        "explicit-skill",
        "# Explicit Skill\n- Always use explicit flow\n- Keep changes deterministic",
    )
    _write_skill(
        codex_home,
        "pinned-skill",
        "# Pinned Skill\n- Always include pinned behavior",
    )
    _write_skill(
        codex_home,
        "deploy-cloudflare",
        "# Cloudflare Deploy\n- Deploy Cloudflare Workers and verify routes",
    )

    state_path = cfg.memory.root_path / ".thomas" / "cli" / "skills.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"pinned": ["pinned-skill"]}, ensure_ascii=False),
        encoding="utf-8",
    )

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
    codex_home = tmp_path / "codex-home"
    home_root.mkdir(parents=True, exist_ok=True)
    codex_home.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.delenv("THOMAS_SKILLS_EXTRA_DIRS", raising=False)

    _write_skill(
        codex_home,
        "robot-ui",
        "# Robot UI\n- Use live screenshots\n- Verify before finishing",
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
    codex_home = tmp_path / "codex-home"
    home_root.mkdir(parents=True, exist_ok=True)
    codex_home.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("THOMAS_RUNTIME_SKILLS_ENABLED", "1")
    monkeypatch.delenv("THOMAS_SKILLS_EXTRA_DIRS", raising=False)

    _write_skill(
        codex_home,
        "robot-theme",
        "# Robot Theme\n- Keep robot visuals consistent\n- Reuse existing sprite family",
    )

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

    assert llm.last_messages
    system_msg = llm.last_messages[0]
    assert str(system_msg.get("role")) == "system"
    text = str(system_msg.get("content") or "")
    assert "--- Runtime Skills ---" in text
    assert "robot-theme" in text


def test_runtime_skills_blocks_untrusted_cwd_skills_by_default(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    home_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("THOMAS_SKILLS_EXTRA_DIRS", raising=False)
    monkeypatch.delenv("THOMAS_RUNTIME_SKILLS_TRUST_MODE", raising=False)

    # In default trust mode, cwd/skills is discovered but not trusted.
    skill_dir = tmp_path / "skills" / "untrusted-cwd-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Untrusted\n- Local cwd skill\n", encoding="utf-8")

    selection = resolve_runtime_skills(
        cfg,
        prompt_text="please use $untrusted-cwd-skill",
        relevance_text="",
        route_path="coding_task",
        cwd=tmp_path,
        max_selected=2,
    )
    assert int(selection.discovered_count) >= 1
    assert len(selection.selected) == 0
    codes = {str(item.get("code") or "") for item in (selection.blocked or [])}
    assert "untrusted_skill" in codes


def test_runtime_skills_require_explicit_for_risky_pinned_skills(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    codex_home = tmp_path / "codex-home"
    home_root.mkdir(parents=True, exist_ok=True)
    codex_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("THOMAS_RUNTIME_SKILLS_REQUIRE_EXPLICIT_RISK_APPROVAL", "1")
    monkeypatch.delenv("THOMAS_SKILLS_EXTRA_DIRS", raising=False)

    _write_skill(
        codex_home,
        "deploy-prod",
        "# Deploy Prod\n- Deploy production release\n- Update billing webhook and auth token",
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
    blocked_codes = {str(item.get("code") or "") for item in (blocked.blocked or [])}
    assert "risky_skill_requires_explicit_approval" in blocked_codes

    allowed = resolve_runtime_skills(
        cfg,
        prompt_text="please use $deploy-prod now",
        relevance_text="deploy production release",
        route_path="coding_task",
        cwd=tmp_path,
        max_selected=2,
    )
    selected_names = [s.name for s in allowed.selected]
    assert "deploy-prod" in selected_names
    assert "deploy-prod" in (allowed.approved_risky or [])


def test_runtime_skills_provider_conformance_same_selection_and_prompt(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_cfg(tmp_path)
    home_root = tmp_path / "home"
    codex_home = tmp_path / "codex-home"
    home_root.mkdir(parents=True, exist_ok=True)
    codex_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setenv("USERPROFILE", str(home_root))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.delenv("THOMAS_SKILLS_EXTRA_DIRS", raising=False)

    _write_skill(
        codex_home,
        "robot-theme",
        "# Robot Theme\n- Keep robot visuals consistent\n- Reuse existing sprite family",
    )

    providers = ["openai_compat", "anthropic", "codex"]
    selected_sets = []
    prompt_snippets = []

    async def _run_for_provider(provider: str):
        llm = _CaptureLLM(provider=provider)
        tools = ToolRegistry()
        agent = AgentLoop(cfg, llm, tools, conversation=[])
        events = []
        async for ev in agent.run("please use $robot-theme for this pass", tools_policy="never"):
            events.append(ev)
        return llm, events

    for provider in providers:
        llm, events = asyncio.run(_run_for_provider(provider))
        start = next((e for e in events if e.type == EventType.AGENT_START), None)
        assert start is not None
        payload = start.data.get("skills") or {}
        selected = tuple(sorted(str(row.get("name") or "") for row in (payload.get("selected") or [])))
        selected_sets.append(selected)

        assert llm.last_messages
        system_text = str((llm.last_messages[0] or {}).get("content") or "")
        assert "--- Runtime Skills ---" in system_text
        assert "robot-theme" in system_text
        prompt_snippets.append(system_text.split("--- Runtime Skills ---", 1)[1][:220])

    assert len(set(selected_sets)) == 1
    assert len(set(prompt_snippets)) == 1
