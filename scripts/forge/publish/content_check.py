"""Validate public source and Python distributions for internal content."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path

BLOCKED_PREFIXES = (
    'demo/agentic-runs/', 'demo/runs/', 'demo/circuit-courier/progress.md',
    'docs/superpowers/', 'docs/evals/', 'docs/launch/', 'docs/ops/remediation/',
    'runtime/', '.thomas/', '.claude/', 'output/', 'reports/',
)
PLAN_TEMPLATES = {'plans/README.md', 'plans/thomas/README.md', 'plans/thomas/WORKBOARD.md'}
BLOCKED_NAMES = re.compile(r'(?:^|/)(?:HANDOFF_[^/]*|NEXT_AGENT_HANDOFF|agent_handoff_log)(?:\.md)?$', re.I)
LOCAL_PATH = re.compile(r'(?i)C:(?:\\+|/)Users(?:\\+|/)(<[^>]+>|[^\\/\s`"\'<>]+)')
ALLOWED_USERS = {'example', 'public', 'default', 'test', 'testuser', 'user', 'runneradmin', '<user>', '<username>', '{username}', 'alice', 'bob', 'dev', 'owner', '<name>', '<you>'}
TEXT_EXTENSIONS = {'.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.css', '.html', '.md', '.json', '.jsonl', '.toml', '.yaml', '.yml', '.txt', '.ps1', '.cmd', '.sh'}


def inspect(path: str, data: bytes) -> list[str]:
    errors = []
    if path.startswith(BLOCKED_PREFIXES) or BLOCKED_NAMES.search(path):
        errors.append('internal artifact path')
    if path.startswith('plans/') and path not in PLAN_TEMPLATES:
        errors.append('private planning record')
    if Path(path).suffix not in TEXT_EXTENSIONS:
        return errors
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return errors
    for i, line in enumerate(text.splitlines(), 1):
        if path == 'plans/thomas/WORKBOARD.md' and re.search(r'^\s*-\s*(?:msg_id=|agent=)', line):
            errors.append(f'populated coordination record at line {i}')
        for match in LOCAL_PATH.finditer(line):
            if match[1].lower() not in ALLOWED_USERS and not match[1].startswith(('$', '%', '[')):
                errors.append(f'personal machine path at line {i}')
        if not path.startswith(('tests/', 'scripts/')) and re.search(r'^\s*[-*]?\s*msg_id=msg-\d{8}', line):
            errors.append(f'agent conversation record at line {i}')
    return sorted(set(errors))


def source_members(root: Path):
    result = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root, capture_output=True, check=True)
    for rel in sorted(set(result.stdout.decode().split('\0')) - {''}):
        path = root / rel
        if path.is_file():
            yield rel, path.read_bytes()


def archive_members(path: Path):
    if path.suffix == '.whl' or path.suffix == '.zip':
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if not name.endswith('/')]
            roots = {name.split('/', 1)[0] for name in names}
            wrapped = path.suffix == '.zip' and len(roots) == 1 and all('/' in name for name in names)
            for name in names:
                rel = name.split('/', 1)[1] if wrapped else name
                yield rel, archive.read(name)
    elif path.name.endswith('.tar.gz'):
        with tarfile.open(path, 'r:gz') as archive:
            for member in archive.getmembers():
                if member.isfile():
                    stream = archive.extractfile(member)
                    if stream is not None:
                        # Source distributions wrap all files in a versioned root.
                        name = member.name.split('/', 1)[-1]
                        yield name, stream.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--archives', type=Path)
    args = parser.parse_args()
    findings = []
    checked = 0
    inputs = [('source', source_members(args.root.resolve()))]
    if args.archives:
        inputs += [(p.name, archive_members(p)) for p in sorted(args.archives.iterdir()) if p.name.endswith(('.whl', '.tar.gz', '.zip'))]
    for origin, members in inputs:
        for name, data in members:
            checked += 1
            for error in inspect(name, data):
                findings.append({'origin': origin, 'path': name, 'reason': error})
    print(json.dumps({'ok': not findings, 'files_checked': checked, 'findings': findings}, indent=2))
    return 1 if findings else 0


if __name__ == '__main__':
    raise SystemExit(main())
