"""Startup guidance discovery for Thomas.

This module centralizes how Thomas discovers high-priority local instruction
files and compacts them into a prompt-safe purpose brief.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_DEFAULT_GUIDANCE_FILES: Sequence[tuple[str, int, bool]] = (
    ("AGENTS.md", 10, False),
    ("IDENTITY.md", 8, False),
    ("USER.md", 8, False),
    ("SOUL.md", 8, False),
    ("definitions/autopoietic.md", 6, False),
    ("definitions/change-classification.md", 6, False),
    ("docs/PROJECT_SCOPE.md", 8, False),
    ("docs/ROUTING_FLOWCHART.md", 6, False),
    # README is fallback-only to avoid prompt bloat when dedicated guidance exists.
    ("README.md", 4, True),
)


@dataclass(frozen=True)
class GuidanceSourceStatus:
    path: str
    exists: bool
    selected: bool
    bullet_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": bool(self.exists),
            "selected": bool(self.selected),
            "bullet_count": int(self.bullet_count),
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _collect_md_bullets(text: str, *, limit: int) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("- "):
            lines.append(s[2:].strip())
        elif s.startswith("#"):
            lines.append(s.lstrip("# ").strip())
        if len(lines) >= int(limit):
            break
    return lines


def _build_compact_section(rel_path: str, bullets: list[str]) -> str:
    title = rel_path.replace("\\", "/")
    body = "\n".join(f"- {b}" for b in bullets)
    return f"[{title}]\n{body}"


def load_purpose_brief(
    *,
    root: Path | None = None,
    max_chars: int = 2_500,
) -> tuple[str, list[GuidanceSourceStatus]]:
    """Build a compact purpose brief from ordered local guidance files."""
    repo_root = Path(root) if root is not None else _repo_root()
    sections: list[str] = []
    statuses: list[GuidanceSourceStatus] = []

    for rel_path, bullet_limit, fallback_only in _DEFAULT_GUIDANCE_FILES:
        path = repo_root / rel_path
        exists = path.exists() and path.is_file()
        bullets: list[str] = []
        should_read = (not fallback_only) or (len(sections) == 0)
        if exists and should_read:
            try:
                raw = path.read_text(encoding="utf-8", errors="replace").strip()
                if raw:
                    bullets = _collect_md_bullets(raw, limit=int(bullet_limit))
            except Exception:
                bullets = []

        selected = bool(bullets)
        if selected:
            sections.append(_build_compact_section(rel_path, bullets))

        statuses.append(
            GuidanceSourceStatus(
                path=rel_path,
                exists=bool(exists),
                selected=bool(selected),
                bullet_count=len(bullets),
            )
        )

    text = "\n\n".join(sections).strip()
    if len(text) > int(max_chars):
        text = text[: int(max_chars) - 64].rstrip() + "\n...(purpose brief truncated)"
    return text, statuses


@lru_cache(maxsize=1)
def load_cached_purpose_brief() -> str:
    text, _ = load_purpose_brief()
    return text


@lru_cache(maxsize=1)
def guidance_bootstrap_report() -> dict[str, Any]:
    text, statuses = load_purpose_brief()
    return {
        "root": str(_repo_root()),
        "purpose_chars": len(text),
        "selected_sources": [s.path for s in statuses if s.selected],
        "sources": [s.to_dict() for s in statuses],
    }


def clear_guidance_cache() -> None:
    """Clear memoized guidance state (used by tests)."""
    load_cached_purpose_brief.cache_clear()
    guidance_bootstrap_report.cache_clear()
