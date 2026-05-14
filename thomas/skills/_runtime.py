from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from ._manifest import SkillBundle, read_skill_bundle


def _unique_paths(paths: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for path, origin in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists() and resolved.is_dir():
            out.append((resolved, origin))
    return out


def _repo_root(start: Path | None = None) -> Path | None:
    current = (start or Path(__file__)).resolve()
    anchor = current if current.is_dir() else current.parent
    for parent in (anchor, *anchor.parents):
        if (parent / 'pyproject.toml').exists() and (parent / 'thomas').exists():
            return parent
    return None


def builtin_skill_roots(*, cwd: Path | None = None) -> list[Path]:
    candidates: list[tuple[Path, str]] = []
    repo_root = _repo_root(cwd or Path(__file__))
    if repo_root is not None:
        candidates.append((repo_root / 'skills', 'builtin'))
    candidates.append((Path(sys.prefix).resolve() / 'skills', 'builtin'))
    return [path for path, _origin in _unique_paths(candidates)]


def resolve_builtin_promotion_root(*, cwd: Path | None = None) -> Path:
    repo_root = _repo_root(cwd or Path.cwd())
    if repo_root is not None:
        return repo_root / 'skills'
    return Path(sys.prefix).resolve() / 'skills'


def _codex_home_skill_root() -> Path | None:
    raw = str(os.environ.get('CODEX_HOME') or '').strip()
    if not raw:
        return None
    return Path(raw).expanduser() / 'skills'


def discover_native_skill_roots(*, cwd: Path | None = None) -> list[tuple[Path, str]]:
    root_cwd = Path(cwd) if cwd is not None else Path.cwd()
    candidates: list[tuple[Path, str]] = [(path, 'builtin') for path in builtin_skill_roots(cwd=root_cwd)]
    codex_home_root = _codex_home_skill_root()
    if codex_home_root is not None:
        candidates.append((codex_home_root, 'user'))
    candidates.extend(
        [
            (Path.home() / '.thomas' / 'skills', 'user'),
            (root_cwd / '.thomas' / 'skills', 'project_override'),
            (root_cwd / 'skills', 'project_local'),
        ]
    )
    return _unique_paths(candidates)


def discover_native_skills(*, cwd: Path | None = None) -> tuple[list[SkillBundle], list[str]]:
    rows: list[SkillBundle] = []
    roots = discover_native_skill_roots(cwd=cwd)
    seen: set[str] = set()
    for root, origin in roots:
        try:
            skill_files = list(root.rglob('SKILL.md'))
        except OSError:
            skill_files = []
        for skill_md in skill_files:
            bundle = read_skill_bundle(skill_md.parent, source_root=root, origin=origin)
            if bundle is None or bundle.key in seen:
                continue
            seen.add(bundle.key)
            rows.append(bundle)
    origin_rank = {'builtin': 0, 'user': 1, 'project_override': 2, 'project_local': 3, 'extra': 4, 'external': 5}
    rows.sort(key=lambda item: (item.name.lower(), origin_rank.get(str(item.origin or '').lower(), 99), item.path.lower()))
    return rows, [str(root) for root, _origin in roots]


def discover_external_skill_sources(root: Path) -> list[dict[str, Any]]:
    source_root = root.expanduser().resolve()
    if not source_root.exists() or not source_root.is_dir():
        raise FileNotFoundError(f'External root not found: {source_root}')

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for skill_md in source_root.rglob('SKILL.md'):
        skill_dir = skill_md.parent
        key = str(skill_dir.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        bundle = read_skill_bundle(skill_dir, source_root=source_root, origin='external')
        if bundle is None:
            continue
        rows.append(
            {
                'name': bundle.name,
                'description': bundle.description,
                'path': bundle.path,
                'skill_file': bundle.skill_file,
                'kind': 'bundle',
            }
        )

    for markdown in source_root.rglob('*.md'):
        if markdown.name == 'SKILL.md':
            continue
        if any(parent.name == '.git' for parent in markdown.parents):
            continue
        key = str(markdown.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                'name': markdown.stem,
                'description': f'External markdown template at {markdown.name}',
                'path': str(markdown.resolve()),
                'skill_file': str(markdown.resolve()),
                'kind': 'markdown_template',
            }
        )

    rows.sort(key=lambda item: (str(item.get('name') or '').lower(), str(item.get('path') or '').lower()))
    return rows
