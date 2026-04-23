from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(slots=True)
class SkillBundle:
    name: str
    path: str
    skill_file: str
    source_root: str
    description: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)
    thomas_metadata: dict[str, Any] = field(default_factory=dict)
    origin: str = ""

    @property
    def key(self) -> str:
        return str(self.path).strip().lower()


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    raw = str(text or "")
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    frontmatter = match.group(1)
    body = raw[match.end() :]
    payload: dict[str, str] = {}
    for line in frontmatter.splitlines():
        row = str(line or "").strip()
        if not row or row.startswith("#") or ":" not in row:
            continue
        key, _, value = row.partition(":")
        payload[key.strip()] = value.strip().strip('"').strip("'")
    return payload, body


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _load_thomas_metadata(skill_dir: Path) -> dict[str, Any]:
    meta_path = skill_dir / "THOMAS_SKILL.json"
    if not meta_path.exists():
        return {}
    try:
        payload = json.loads(_read_text(meta_path))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _body_lines(body: str) -> list[str]:
    lines: list[str] = []
    in_code_block = False
    for line in str(body or "").splitlines():
        stripped = str(line or "").rstrip()
        marker = stripped.strip()
        if marker.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        lines.append(stripped)
    return lines


def skill_description(metadata: dict[str, Any], body: str) -> str:
    frontmatter_desc = str(metadata.get("description") or "").strip()
    if frontmatter_desc:
        return frontmatter_desc[:240]
    for line in _body_lines(body):
        text = str(line or "").strip()
        if not text or text.startswith("#"):
            continue
        return text[:240]
    return ""


def excerpt_body(body: str, *, max_chars: int = 1100) -> str:
    collected: list[str] = []
    count = 0
    for line in _body_lines(body):
        text = str(line or "").strip()
        if not text:
            if collected and collected[-1] != "":
                collected.append("")
                count += 1
            continue
        clipped = text[:220] + ("..." if len(text) > 220 else "")
        next_count = count + len(clipped) + 1
        if next_count > max_chars:
            break
        collected.append(clipped)
        count = next_count
    return "\n".join(collected).strip()


def read_skill_bundle(skill_dir: Path, *, source_root: Path, origin: str) -> SkillBundle | None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    raw = _read_text(skill_md)
    metadata, body = parse_frontmatter(raw)
    description = skill_description(metadata, body)
    return SkillBundle(
        name=str(skill_dir.name),
        path=str(skill_dir.resolve()),
        skill_file=str(skill_md.resolve()),
        source_root=str(source_root.resolve()),
        description=description,
        body=body,
        metadata=metadata,
        thomas_metadata=_load_thomas_metadata(skill_dir),
        origin=str(origin or "").strip(),
    )


def validate_skill_bundle(skill_dir: Path) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        issues.append({"code": "missing_skill_file", "message": "SKILL.md is required."})
        return issues
    metadata, body = parse_frontmatter(_read_text(skill_md))
    name = str(metadata.get("name") or "").strip()
    description = skill_description(metadata, body)
    if not name:
        issues.append({"code": "missing_name", "message": "Frontmatter must include a non-empty name."})
    if not description:
        issues.append({"code": "missing_description", "message": "Skill must expose a usable description."})
    if name and name != skill_dir.name:
        issues.append(
            {
                "code": "name_mismatch",
                "message": f"Frontmatter name '{name}' must match directory name '{skill_dir.name}'.",
            }
        )
    return issues