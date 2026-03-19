from pathlib import Path

from thomas.cli.repl_skills import list_all_skills
from thomas.skills import discover_native_skills


def _write_skill(root: Path, name: str, description: str, body: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / 'SKILL.md').write_text(
        '\n'.join(
            [
                '---',
                f'name: {name}',
                f'description: {description}',
                '---',
                '',
                f'# {name}',
                '',
                body,
                '',
            ]
        ),
        encoding='utf-8',
    )


def test_repl_catalog_matches_native_skill_catalog_and_prefers_builtin(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / 'repo'
    (repo_root / 'thomas').mkdir(parents=True)
    (repo_root / 'pyproject.toml').write_text('[project]\nname="tmp"\nversion="0.0.0"\n', encoding='utf-8')
    home_root = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home_root))
    monkeypatch.setenv('USERPROFILE', str(home_root))

    _write_skill(repo_root / 'skills', 'shared-skill', 'Builtin version.', 'builtin instructions')
    _write_skill(home_root / '.thomas' / 'skills', 'shared-skill', 'User version.', 'user instructions')
    _write_skill(home_root / '.thomas' / 'skills', 'user-skill', 'User skill.', 'user body')
    _write_skill(repo_root / '.thomas' / 'skills', 'project-override-skill', 'Project override skill.', 'project body')

    monkeypatch.chdir(repo_root)
    bundles, _roots = discover_native_skills(cwd=repo_root)
    repl_skills = list_all_skills()

    assert set(repl_skills.keys()) == {bundle.name for bundle in bundles}
    assert repl_skills['shared-skill'].source == repo_root / 'skills' / 'shared-skill' / 'SKILL.md'
    assert 'Builtin version.' in repl_skills['shared-skill'].description