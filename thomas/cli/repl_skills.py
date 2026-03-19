"""Skill discovery and expansion for the Thomas REPL.

Skills are markdown prompt templates stored in ``~/.thomas/skills/`` or
``.thomas/skills/`` relative to the project root.  Each ``.md`` file becomes
a named skill whose front-matter (YAML between ``---`` fences) can declare a
``description`` and argument placeholders.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class SkillDefinition:
    """A loaded skill template."""

    name: str
    description: str = ""
    template: str = ""
    args: list[str] = field(default_factory=list)
    source: Path | None = None


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split YAML front-matter from body text.

    Returns ``(meta_dict, body)`` where *meta_dict* is empty if there is no
    front-matter.
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}, text
    raw = m.group(1)
    body = text[m.end() :]
    meta: dict[str, Any] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
    return meta, body


def _discover_skill_dirs() -> list[Path]:
    """Return candidate skill directories (project-local first, then user-global)."""
    dirs: list[Path] = []
    # Project-local
    local = Path.cwd() / ".thomas" / "skills"
    if local.is_dir():
        dirs.append(local)
    # User-global
    user = Path.home() / ".thomas" / "skills"
    if user.is_dir() and user != local:
        dirs.append(user)
    return dirs


def list_all_skills() -> dict[str, SkillDefinition]:
    """Discover and return all available skills keyed by name."""
    skills: dict[str, SkillDefinition] = {}
    for skill_dir in _discover_skill_dirs():
        for md in sorted(skill_dir.glob("*.md")):
            name = md.stem
            if name in skills:
                continue  # project-local takes priority
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, body = _parse_frontmatter(text)
            description = str(meta.get("description", "")).strip() or name
            args_raw = meta.get("args", "")
            args = [a.strip() for a in str(args_raw).split(",") if a.strip()] if args_raw else []
            skills[name] = SkillDefinition(
                name=name,
                description=description,
                template=body.strip(),
                args=args,
                source=md,
            )
    return skills


def expand_skill(skill: SkillDefinition, user_args: str = "") -> str:
    """Expand a skill template, substituting ``{{args}}`` with *user_args*."""
    expanded = skill.template
    if "{{args}}" in expanded:
        expanded = expanded.replace("{{args}}", user_args.strip())
    elif user_args.strip():
        expanded = f"{expanded}\n\n{user_args.strip()}"
    return expanded
