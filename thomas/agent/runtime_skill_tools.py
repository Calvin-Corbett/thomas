"""Structured runtime-skill discovery for model-owned selection.

These tools expose an inventory and exact skill loading. They never compare a
user prompt with keywords or choose a skill on the model's behalf.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from thomas.agent.skills_policy import evaluate_skill_trust, load_runtime_skill_trust_policy
from thomas.agent.skills_runtime import RuntimeSkill, discover_runtime_skills
from thomas.tools.base import Tool, ToolResult


def _normalize(value: object) -> str:
    return str(value or "").strip().lower()


class _RuntimeSkillTool(Tool):
    category = "skills"

    def __init__(self, config: Any, cwd: Path) -> None:
        self._config = config
        self._cwd = Path(cwd)

    def _inventory(self) -> tuple[list[RuntimeSkill], Any]:
        skills, _roots = discover_runtime_skills(self._config, cwd=self._cwd)
        policy = load_runtime_skill_trust_policy(self._config, cwd=self._cwd)
        return skills, policy

    @staticmethod
    def _trusted(skill: RuntimeSkill, policy: Any) -> tuple[bool, str]:
        return evaluate_skill_trust(
            skill_name=skill.name,
            skill_file=skill.skill_file,
            skill_sha256=skill.skill_sha256,
            policy=policy,
        )


class ListRuntimeSkillsTool(_RuntimeSkillTool):
    name = "skills.list"
    description = (
        "List available trusted skills so you can decide whether one helps this turn. "
        "Call this based on your own judgment; Thomas does not keyword-match the user's prose."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        _ = args
        skills, policy = self._inventory()
        rows: list[dict[str, Any]] = []
        for skill in skills:
            trusted, reason = self._trusted(skill, policy)
            if policy.mode == "enforce" and not trusted:
                continue
            rows.append(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "risk_level": skill.risk_level,
                    "requires_explicit_user_invocation": skill.risk_level == "high",
                    "trust": reason,
                }
            )
        return ToolResult(ok=True, data={"skills": rows, "count": len(rows)})


class UseRuntimeSkillTool(_RuntimeSkillTool):
    name = "skills.use"
    description = (
        "Load one exact trusted skill after you have chosen it. This validates trust and returns "
        "the skill instructions; it does not infer a skill from prompt wording. High-risk skills "
        "require the user to invoke them explicitly with $skill-name."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Exact skill name returned by skills.list.",
            }
        },
        "required": ["name"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        requested = _normalize(args.get("name"))
        skills, policy = self._inventory()
        matches = [skill for skill in skills if _normalize(skill.name) == requested]
        if len(matches) != 1:
            return ToolResult(ok=False, error=f"Unknown or ambiguous skill: {requested}")

        skill = matches[0]
        trusted, reason = self._trusted(skill, policy)
        if policy.mode == "enforce" and not trusted:
            return ToolResult(ok=False, error=f"Skill '{skill.name}' is not trusted ({reason}).")
        if skill.risk_level == "high":
            return ToolResult(
                ok=False,
                error=(
                    f"Skill '{skill.name}' is high risk and cannot be selected organically. "
                    f"The user must invoke ${skill.name} explicitly."
                ),
            )

        return ToolResult(
            ok=True,
            data={
                "name": skill.name,
                "description": skill.description,
                "skill_file": skill.skill_file,
                "skill_sha256": skill.skill_sha256,
                "instructions": skill.excerpt,
                "trust": reason,
            },
        )


def register_runtime_skill_tools(registry: Any, config: Any, cwd: Path) -> None:
    registry.register(ListRuntimeSkillsTool(config, cwd))
    registry.register(UseRuntimeSkillTool(config, cwd))
