#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import tomllib
except Exception:  # pragma: no cover
    import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def main() -> int:
    errors: list[str] = []

    pyproject_path = ROOT / 'pyproject.toml'
    init_path = ROOT / 'thomas' / '__init__.py'
    changelog_path = ROOT / 'CHANGELOG.md'

    try:
        pyproject = tomllib.loads(_read(pyproject_path))
        project_version = str((pyproject.get('project') or {}).get('version') or '').strip()
    except Exception as exc:
        errors.append(f'failed to parse {pyproject_path}: {exc}')
        project_version = ''

    init_text = _read(init_path)
    m = re.search(r"__version__\s*=\s*\"([^\"]+)\"", init_text)
    init_version = m.group(1).strip() if m else ''
    if not init_version:
        errors.append(f'could not find __version__ in {init_path}')

    if project_version and init_version and project_version != init_version:
        errors.append(
            f'version mismatch: pyproject.toml={project_version} vs thomas/__init__.py={init_version}'
        )

    changelog_text = _read(changelog_path)
    if '## [Unreleased]' not in changelog_text:
        errors.append('CHANGELOG.md is missing "## [Unreleased]" section')

    target_version = project_version or init_version
    if target_version:
        version_header = re.compile(rf'^## \[{re.escape(target_version)}\](?:\s*-\s*\d{{4}}-\d{{2}}-\d{{2}})?\s*$', re.M)
        if not version_header.search(changelog_text):
            errors.append(
                f'CHANGELOG.md is missing a section header for version [{target_version}]'
            )

    if errors:
        print('release hygiene: FAIL')
        for err in errors:
            print(f'- {err}')
        return 1

    print('release hygiene: PASS')
    print(f'- version: {target_version}')
    print('- changelog sections present: Unreleased + current version')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
