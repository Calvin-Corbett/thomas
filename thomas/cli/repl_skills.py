"""Native Thomas skill discovery and expansion for the REPL."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from thomas.skills import discover_native_skills

log = logging.getLogger(__name__)


@dataclass
class SkillDefinition:
    """A loaded Thomas-native skill template."""

    name: str
    description: str = ""
    template: str = ""
    args: list[str] = field(default_factory=list)
    source: Path | None = None
    origin: str = ""


def _skill_args(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or '').strip()
    if not text:
        return []
    return [chunk.strip() for chunk in text.split(',') if chunk.strip()]


def list_all_skills() -> dict[str, SkillDefinition]:
    """Discover all Thomas-native skills keyed by name."""
    skills: dict[str, SkillDefinition] = {}
    bundles, _roots = discover_native_skills(cwd=Path.cwd())
    for bundle in bundles:
        if bundle.name in skills:
            continue
        skills[bundle.name] = SkillDefinition(
            name=bundle.name,
            description=str(bundle.description or bundle.name),
            template=str(bundle.body or '').strip(),
            args=_skill_args(bundle.metadata.get('args')),
            source=Path(bundle.skill_file),
            origin=str(bundle.origin or ''),
        )
    return skills


def expand_skill(skill: SkillDefinition, user_args: str = '') -> str:
    """Expand a skill template, substituting ``{{args}}`` with *user_args*."""
    expanded = skill.template
    if '{{args}}' in expanded:
        expanded = expanded.replace('{{args}}', user_args.strip())
    elif user_args.strip():
        expanded = f"{expanded}\n\n{user_args.strip()}"
    return expanded