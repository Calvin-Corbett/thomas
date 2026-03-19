import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from thomas.agent.skills_runtime import resolve_runtime_skills
from thomas.cli.compat_skills import skills
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.skills import create_skill_draft, list_draft_issues, promote_skill_draft, review_skill_draft


def _fake_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(memory=SimpleNamespace(root_path=tmp_path))


def _app_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        models={'local': ModelConfig(name='local', model='dummy')},
        default_model='local',
        memory=MemoryConfig(root=str(tmp_path / 'runtime')),
    )


def test_skills_cli_scan_distill_review_promote_roundtrip(tmp_path: Path, monkeypatch) -> None:
    cfg = _fake_config(tmp_path)
    runner = CliRunner()
    home_root = tmp_path / 'home'
    external_root = tmp_path / 'external'
    monkeypatch.setenv('HOME', str(home_root))
    monkeypatch.setenv('USERPROFILE', str(home_root))
    source_dir = external_root / 'demo-skill'
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / 'SKILL.md').write_text(
        '---\nname: demo-skill\ndescription: External demo skill.\n---\n\n# demo\n\n- external instructions\n',
        encoding='utf-8',
    )

    res_scan = runner.invoke(skills, ['scan-external', '--root', str(external_root), '--json'], obj={'config': cfg})
    assert res_scan.exit_code == 0, res_scan.output
    scan_payload = json.loads(res_scan.output)
    assert scan_payload['count'] == 1

    res_distill = runner.invoke(
        skills,
        ['distill', '--source', str(source_dir), '--name', 'thomas-demo', '--json'],
        obj={'config': cfg},
    )
    assert res_distill.exit_code == 0, res_distill.output
    draft_payload = json.loads(res_distill.output)
    draft_id = draft_payload['draft_id']

    res_review = runner.invoke(skills, ['review', draft_id, '--json'], obj={'config': cfg})
    assert res_review.exit_code == 0, res_review.output

    res_promote = runner.invoke(skills, ['promote', draft_id, '--target', 'user', '--json'], obj={'config': cfg})
    assert res_promote.exit_code == 0, res_promote.output
    promote_payload = json.loads(res_promote.output)
    assert promote_payload['status'] == 'promoted'
    assert str(promote_payload['promoted_to']).endswith('thomas-demo')


def test_distilled_drafts_are_not_auto_selected_until_promoted(tmp_path: Path, monkeypatch) -> None:
    cfg = _app_config(tmp_path)
    home_root = tmp_path / 'home'
    external_root = tmp_path / 'external'
    monkeypatch.setenv('HOME', str(home_root))
    monkeypatch.setenv('USERPROFILE', str(home_root))
    monkeypatch.chdir(tmp_path)

    source_dir = external_root / 'clip-ops'
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / 'SKILL.md').write_text(
        '---\nname: clip-ops\ndescription: External clip skill.\n---\n\n# clip ops\n\n- find clips\n',
        encoding='utf-8',
    )

    manifest = create_skill_draft(cfg, source=str(source_dir), name='clip-ops-native')
    draft_id = str(manifest['draft_id'])

    before = resolve_runtime_skills(
        cfg,
        prompt_text='please use $clip-ops-native',
        relevance_text='clip ops',
        route_path='coding_task',
        cwd=tmp_path,
        max_selected=2,
    )
    assert 'clip-ops-native' not in [skill.name for skill in before.selected]

    review_skill_draft(cfg, draft_id=draft_id)
    promote_skill_draft(cfg, draft_id=draft_id, target='user', cwd=tmp_path)

    after = resolve_runtime_skills(
        cfg,
        prompt_text='please use $clip-ops-native',
        relevance_text='clip ops',
        route_path='coding_task',
        cwd=tmp_path,
        max_selected=2,
    )
    assert 'clip-ops-native' in [skill.name for skill in after.selected]


def test_no_copy_policy_blocks_promotion_and_check_reports_it(tmp_path: Path, monkeypatch) -> None:
    cfg = _fake_config(tmp_path)
    runner = CliRunner()
    home_root = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home_root))
    monkeypatch.setenv('USERPROFILE', str(home_root))

    source_dir = tmp_path / 'external' / 'copied-skill'
    source_dir.mkdir(parents=True, exist_ok=True)
    source_text = '---\nname: copied-skill\ndescription: External copied skill.\n---\n\n# copied\n\n- identical text\n'
    (source_dir / 'SKILL.md').write_text(source_text, encoding='utf-8')

    manifest = create_skill_draft(cfg, source=str(source_dir), name='copied-skill-native')
    draft_id = str(manifest['draft_id'])
    generated_dir = Path(str(((manifest.get('generated') or {}).get('path') or '')))
    (generated_dir / 'SKILL.md').write_text(source_text, encoding='utf-8')
    (generated_dir / 'THOMAS_SKILL.json').write_text(
        json.dumps({'name': 'copied-skill-native', 'recreated_from_scratch': True}, ensure_ascii=False),
        encoding='utf-8',
    )

    review_skill_draft(cfg, draft_id=draft_id)
    payload = promote_skill_draft(cfg, draft_id=draft_id, target='user', cwd=tmp_path)
    assert payload['status'] == 'blocked'
    assert list_draft_issues(cfg)

    res_check = runner.invoke(skills, ['check', '--json'], obj={'config': cfg})
    assert res_check.exit_code == 1, res_check.output
    check_payload = json.loads(res_check.output)
    assert any(issue.get('code') == 'blocked_promotion' for issue in (check_payload.get('issues') or []))