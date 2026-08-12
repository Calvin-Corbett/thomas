"""Self-extension tool: let Thomas create new skills at runtime.

When Thomas hits a request it cannot fulfill with its current tools, it can
call the ``create_skill`` tool to scaffold a new skill bundle on disk. The
new bundle is written to the auto-discovered *user* skills root
(``~/.thomas/skills/<name>/SKILL.md``) and becomes available on the very next
turn via the normal skill-discovery pass (``thomas.skills.discover_native_skills``).

Why this is safe under runtime protection:
  - ``thomas/tools/`` is a runtime-protected directory, but that protection
    blocks an *agent's runtime filesystem writes INTO* protected dirs. This
    module is a developer-authored file (added at build time, not by Thomas at
    runtime), so it does not violate that rule.
  - The tool's own writes target ``~/.thomas/skills/`` (the user home tree),
    which is OUTSIDE the repo sandbox entirely and outside every protected
    runtime directory. Self-created skills therefore never touch
    ``thomas/tools``, ``thomas/agent``, ``thomas/core``, ``thomas/server`` or
    ``scripts``.
  - ``~/.thomas/skills`` is one of the default *trusted* skill roots
    (see ``thomas.skills.discover_native_skill_roots`` and
    ``thomas.agent.skills_policy``), so the new skill is trusted and selectable
    next turn without extra configuration.

The new skill is a markdown instruction bundle — it tells Thomas *how* and
*when* to use the new ability. To gain ability that needs a brand-new code
tool (one Thomas does not have at all), the scaffolded instructions guide
Thomas to use its existing primitive tools (shell / http / filesystem) to
accomplish the task, or to ask the user to wire credentials.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult

# Names an agent must never be able to scaffold over: these are the canonical
# meta/skill names that ship with Thomas or that would shadow a control skill.
_RESERVED_SKILL_NAMES = {
    "self-extend",
    "auto-skillify",
}

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NAME_CHARS_RE = re.compile(r"[^a-z0-9]+")


def _slugify(raw: str) -> str:
    """Turn a free-form name into a safe lowercase hyphenated slug."""
    lowered = str(raw or "").strip().lower()
    slug = _NAME_CHARS_RE.sub("-", lowered).strip("-")
    return slug


def _user_skills_root() -> Path:
    """The auto-discovered, writable, trusted USER skills root.

    This mirrors the ``("user")`` entry in
    ``thomas.skills.discover_native_skill_roots`` so that anything written here
    is picked up on the next discovery pass.
    """
    return Path.home() / ".thomas" / "skills"


def _yaml_escape(value: str) -> str:
    """Escape a value for a double-quoted YAML scalar."""
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()


def _build_skill_markdown(
    *,
    name: str,
    description: str,
    instructions: str,
    keywords: list[str],
    trigger: str,
) -> str:
    """Render a SKILL.md document with valid frontmatter + body.

    Frontmatter format matches ``thomas.skills._manifest.parse_frontmatter``:
    a ``---`` fenced block of ``key: value`` lines, where ``name`` must equal
    the directory name and ``description`` drives skill selection.
    """
    desc = _yaml_escape(description)
    if trigger:
        # Fold the trigger condition into the description so the selector and
        # the model both see *when* to reach for this skill.
        desc = f"{desc} Use when {trigger.strip()}".strip()

    lines: list[str] = ["---", f'name: "{_yaml_escape(name)}"', f'description: "{desc}"', "---", ""]

    body = str(instructions or "").strip()
    if not body.lstrip().startswith("#"):
        lines.append(f"# {name}")
        lines.append("")
    lines.append(body)

    if keywords:
        lines.append("")
        lines.append("## Keywords")
        lines.append(", ".join(keywords))

    lines.append("")
    return "\n".join(lines)


class CreateSkillTool(Tool):
    """Scaffold a new skill so Thomas gains an ability it currently lacks.

    Call this when the user asks for something you cannot do with your current
    tools (for example: sending email, posting to a service, a repeated
    multi-step workflow). The new skill is written to disk and becomes
    available on your next turn.
    """

    name = "create_skill"
    category = "self_extension"
    description = (
        "Give yourself a new ability you do not currently have. Scaffolds a new skill bundle on "
        "disk (a SKILL.md with instructions on how/when to use the ability), which becomes "
        "available to you on the NEXT turn. Use this the moment you hit a user request you "
        "cannot fulfill with your current tools (e.g. emailing someone, a new integration, or a "
        "repeated workflow worth capturing). After calling it, tell the user the new ability is "
        "ready and continue."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Short slug name for the new skill, e.g. 'send-email' or 'post-to-slack'. "
                    "Lowercase letters, digits and hyphens only."
                ),
            },
            "description": {
                "type": "string",
                "description": (
                    "One sentence describing what the skill does. This is what future turns "
                    "match against to decide when to use it."
                ),
            },
            "instructions": {
                "type": "string",
                "description": (
                    "Markdown body telling yourself HOW and WHEN to use this new ability: the "
                    "steps to take, which existing tools to call, what inputs are needed, and "
                    "any credentials/config the user must provide."
                ),
            },
            "trigger": {
                "type": "string",
                "description": (
                    "Optional. A plain-English condition for when this skill should activate, "
                    "e.g. 'the user asks to email someone'."
                ),
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional. Extra keywords that should surface this skill.",
            },
        },
        "required": ["name", "description", "instructions"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        raw_name = str(args.get("name") or "").strip()
        description = str(args.get("description") or "").strip()
        instructions = str(args.get("instructions") or "").strip()
        trigger = str(args.get("trigger") or "").strip()
        keywords_in = args.get("keywords") or []
        keywords = [str(k).strip() for k in keywords_in if str(k).strip()] if isinstance(keywords_in, list) else []

        # ── Validate name (slug, no traversal, not reserved) ──────────────
        slug = _slugify(raw_name)
        if not slug:
            return ToolResult(ok=False, error="create_skill requires a non-empty 'name'.")
        if not _SLUG_RE.match(slug):
            return ToolResult(
                ok=False,
                error=f"Invalid skill name {raw_name!r}: must be a lowercase hyphenated slug (e.g. 'send-email').",
            )
        if slug in _RESERVED_SKILL_NAMES:
            return ToolResult(
                ok=False,
                error=f"Skill name '{slug}' is reserved and cannot be overwritten.",
            )
        if not description:
            return ToolResult(ok=False, error="create_skill requires a 'description' (used to decide when to use it).")
        if not instructions:
            return ToolResult(
                ok=False,
                error="create_skill requires 'instructions' (the markdown body telling you how/when to use it).",
            )

        root = _user_skills_root()
        skill_dir = root / slug

        # Defense-in-depth: ensure the resolved target stays under the user
        # skills root (guards against any traversal that slipped past slugify).
        try:
            resolved_dir = skill_dir.resolve()
            resolved_root = root.resolve()
            resolved_dir.relative_to(resolved_root)
        except (ValueError, OSError):
            return ToolResult(ok=False, error=f"Refusing to write skill outside the user skills root: {skill_dir}")

        skill_md = skill_dir / "SKILL.md"
        already_existed = skill_md.exists()

        markdown = _build_skill_markdown(
            name=slug,
            description=description,
            instructions=instructions,
            keywords=keywords,
            trigger=trigger,
        )

        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_md.write_text(markdown, encoding="utf-8")
        except OSError as exc:
            return ToolResult(ok=False, error=f"Failed to write skill bundle: {exc}")

        note = (
            f"Skill '{slug}' {'updated' if already_existed else 'created'} at {skill_md}. "
            "It is a trusted user skill and will be discovered and available to you on your NEXT turn. "
            "Continue with the user's request now; on the next turn select this skill and follow its "
            "instructions to perform the new ability."
        )
        return ToolResult(
            ok=True,
            data={
                "skill_name": slug,
                "path": str(skill_dir),
                "skill_file": str(skill_md),
                "available_next_turn": True,
                "updated": already_existed,
                "note": note,
            },
        )


def register_self_extend_tools(registry) -> None:
    """Register the self-extension tool(s) into a tool registry."""
    registry.register(CreateSkillTool())
