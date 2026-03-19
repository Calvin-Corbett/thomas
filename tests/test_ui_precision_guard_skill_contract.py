from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_AGENTS = ROOT / "AGENTS.md"
UI_SKILL = ROOT / ".codex" / "skills" / "ui-precision-guard" / "SKILL.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_repo_web_ui_policy_requires_common_practice_logic_mode() -> None:
    agents = _read(ROOT_AGENTS)
    skill = _read(UI_SKILL)

    assert "thomas/server/web/**" in agents
    assert "Common-Practice Logic Mode" in agents
    assert "## Common-Practice Logic Mode" in skill
    assert "Does this overpower the primary workflow" in skill
    assert "Status/task chrome should be compact by default" in skill
