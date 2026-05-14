from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from ._manifest import validate_skill_bundle
from ._runtime import discover_external_skill_sources, resolve_builtin_promotion_root
from ._security import _sha256_file, validate_recreated_skill_bundle

_STOPWORDS = {
    'a',
    'an',
    'and',
    'are',
    'as',
    'at',
    'be',
    'but',
    'by',
    'for',
    'from',
    'how',
    'if',
    'in',
    'into',
    'is',
    'it',
    'of',
    'on',
    'or',
    'that',
    'the',
    'this',
    'to',
    'use',
    'with',
    'you',
}


def _utc_iso() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _slugify(value: str) -> str:
    text = re.sub(r'[^a-z0-9]+', '-', str(value or '').strip().lower())
    return text.strip('-')[:64] or 'distilled-skill'


def _draft_id() -> str:
    return f"draft-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:8]}"


def drafts_root(config: Any) -> Path:
    root = Path(config.memory.root_path) / '.thomas' / 'skills-drafts'
    root.mkdir(parents=True, exist_ok=True)
    return root


def _manifest_path(config: Any, draft_id: str) -> Path:
    return drafts_root(config) / str(draft_id).strip() / 'manifest.json'


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _source_files(source_path: Path) -> list[Path]:
    if source_path.is_file():
        return [source_path]
    files: list[Path] = []
    for child in source_path.rglob('*'):
        if child.is_file():
            files.append(child)
    return sorted(files)


def _source_keywords(text: str) -> list[str]:
    words = re.findall(r'[A-Za-z0-9][A-Za-z0-9._-]{2,40}', str(text or '').lower())
    counts: dict[str, int] = {}
    for word in words:
        if word in _STOPWORDS or word.startswith('http'):
            continue
        counts[word] = counts.get(word, 0) + 1
    return [word for word, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:8]]


def _source_text(source_path: Path) -> str:
    snippets: list[str] = []
    for file_path in _source_files(source_path):
        if file_path.suffix.lower() not in {'.md', '.py', '.txt', '.json', '.toml', '.yaml', '.yml', '.sh', '.ps1'}:
            continue
        try:
            snippets.append(file_path.read_text(encoding='utf-8', errors='replace')[:4000])
        except OSError:
            continue
    return '\n'.join(snippets)


def _distilled_skill_text(skill_name: str, source_label: str, keywords: list[str]) -> str:
    focus = ', '.join(keywords[:4]) if keywords else 'the referenced workflow'
    bullets = [f'- Prefer first-party Thomas tools and native repo workflows for {focus}.']
    for keyword in keywords[:4]:
        bullets.append(f'- Keep the workflow explicit and validated around {keyword}.')
    bullets.append('- Recreate from scratch; do not copy foreign code, assets, or long text verbatim.')
    bullet_block = '\n'.join(dict.fromkeys(bullets))
    lines = [
        '---',
        f'name: {skill_name}',
        (
            'description: Thomas-native recreated skill for tasks related to '
            f'{focus}. Use when Thomas needs to perform or adapt this workflow from a reviewed external '
            'reference without copying it verbatim.'
        ),
        '---',
        '',
        f"# {skill_name.replace('-', ' ').title()}",
        '',
        (
            'Use Thomas-native commands, tools, and validations to handle the workflow described by the reviewed '
            f'external reference at {source_label}. Recreate behavior from scratch and improve it where Thomas has '
            'better native paths.'
        ),
        '',
        '## Workflow',
        '1. Confirm the task inputs, outputs, constraints, and safety requirements.',
        '2. Inspect current Thomas-native capabilities before adding any new logic.',
        '3. Recreate the workflow using native Thomas skills, tools, scripts, and repo conventions.',
        '4. Validate the result and call out blockers or policy risks before promotion or execution.',
        '',
        '## Operating Rules',
        bullet_block,
        '',
        '## Validation',
        "- Verify the recreated workflow against the user's goal and Thomas-native tests.",
        '- Keep provenance in THOMAS_SKILL.json and the draft manifest.',
        '- Require manual review before promotion.',
        '',
    ]
    return '\n'.join(lines)


def scan_external_root(root: str | Path) -> dict[str, Any]:
    source_root = Path(root).expanduser().resolve()
    rows = discover_external_skill_sources(source_root)
    return {'ok': True, 'root': str(source_root), 'count': len(rows), 'skills': rows}


def create_skill_draft(config: Any, *, source: str, name: str = '') -> dict[str, Any]:
    if str(source).strip().startswith(('http://', 'https://')):
        raise ValueError('External skill distillation only accepts local filesystem paths.')
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f'Source path not found: {source_path}')

    draft_id = _draft_id()
    draft_dir = drafts_root(config) / draft_id
    base_name = source_path.stem if source_path.is_file() else source_path.name
    skill_name = _slugify(name or base_name)
    generated_dir = draft_dir / 'skill' / skill_name
    generated_dir.mkdir(parents=True, exist_ok=True)

    raw_text = _source_text(source_path)
    keywords = _source_keywords(raw_text)
    source_files = _source_files(source_path)
    source_hashes = [{'path': str(path), 'sha256': _sha256_file(path)} for path in source_files]
    skill_text = _distilled_skill_text(skill_name, source_label=str(source_path), keywords=keywords)
    (generated_dir / 'SKILL.md').write_text(skill_text, encoding='utf-8')
    metadata = {
        'name': skill_name,
        'kind': 'distilled_external_skill',
        'created_at': _utc_iso(),
        'draft_id': draft_id,
        'source_path': str(source_path),
        'recreated_from_scratch': True,
        'review_required': True,
        'promotion_status': 'draft',
        'review_status': 'pending',
    }
    _write_json(generated_dir / 'THOMAS_SKILL.json', metadata)

    validation_issues = validate_skill_bundle(generated_dir)
    similarity = validate_recreated_skill_bundle(generated_dir, [source_path])
    manifest = {
        'draft_id': draft_id,
        'created_at': _utc_iso(),
        'source': {
            'path': str(source_path),
            'kind': 'bundle' if source_path.is_dir() else 'markdown_template',
            'hashes': source_hashes,
        },
        'generated': {
            'skill_name': skill_name,
            'path': str(generated_dir),
        },
        'keywords': keywords,
        'validation': {'ok': not validation_issues, 'issues': validation_issues},
        'similarity': similarity,
        'status': 'draft',
        'reviewed_at': '',
        'promoted_at': '',
        'promoted_to': '',
        'rejected_reason': '',
    }
    _write_json(_manifest_path(config, draft_id), manifest)
    return manifest


def load_skill_draft_manifest(config: Any, draft_id: str) -> dict[str, Any]:
    path = _manifest_path(config, draft_id)
    if not path.exists():
        raise FileNotFoundError(f'Draft not found: {draft_id}')
    payload = _read_json(path)
    payload['manifest_path'] = str(path)
    return payload


def review_skill_draft(config: Any, *, draft_id: str) -> dict[str, Any]:
    path = _manifest_path(config, draft_id)
    payload = _read_json(path)
    payload['status'] = 'reviewed'
    payload['reviewed_at'] = _utc_iso()
    _write_json(path, payload)
    return payload


def reject_skill_draft(config: Any, *, draft_id: str, reason: str = '') -> dict[str, Any]:
    path = _manifest_path(config, draft_id)
    payload = _read_json(path)
    payload['status'] = 'rejected'
    payload['rejected_reason'] = str(reason or '').strip()
    _write_json(path, payload)
    return payload


def promote_skill_draft(config: Any, *, draft_id: str, target: str, cwd: Path | None = None) -> dict[str, Any]:
    path = _manifest_path(config, draft_id)
    payload = _read_json(path)
    if str(payload.get('status') or '') == 'rejected':
        raise ValueError('Rejected drafts cannot be promoted.')
    if not str(payload.get('reviewed_at') or '').strip():
        raise ValueError('Draft must be reviewed before promotion.')

    generated_dir = Path(str((payload.get('generated') or {}).get('path') or '')).expanduser().resolve()
    source_path = Path(str((payload.get('source') or {}).get('path') or '')).expanduser().resolve()
    validation = validate_recreated_skill_bundle(generated_dir, [source_path])
    payload['similarity'] = validation
    if not validation['ok']:
        payload['status'] = 'blocked'
        _write_json(path, payload)
        return payload

    if str(target).strip().lower() == 'builtin':
        dest_root = resolve_builtin_promotion_root(cwd=cwd)
    else:
        dest_root = Path.home() / '.thomas' / 'skills'
    dest_root.mkdir(parents=True, exist_ok=True)
    destination = dest_root / str((payload.get('generated') or {}).get('skill_name') or generated_dir.name)
    if destination.exists():
        raise FileExistsError(f'Destination skill already exists: {destination}')
    shutil.copytree(generated_dir, destination)
    payload['status'] = 'promoted'
    payload['promoted_at'] = _utc_iso()
    payload['promoted_to'] = str(destination)
    _write_json(path, payload)
    return payload


def list_draft_issues(config: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_path in drafts_root(config).glob('*/manifest.json'):
        payload = _read_json(manifest_path)
        if str(payload.get('status') or '') != 'blocked':
            continue
        rows.append(
            {
                'code': 'blocked_promotion',
                'draft_id': str(payload.get('draft_id') or manifest_path.parent.name),
                'path': str(manifest_path),
            }
        )
    return rows
