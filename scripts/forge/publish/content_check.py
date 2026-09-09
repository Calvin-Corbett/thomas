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
    # Generated corpora and external benchmark adapters are working material.
    # Nobody downloads Thomas to read 1,500 generated fixture cases.
    'tests/browser_workflow_corpus/', 'benchmarks/',
)
PLAN_TEMPLATES = {'plans/README.md', 'plans/thomas/README.md', 'plans/thomas/WORKBOARD.md'}
BLOCKED_NAMES = re.compile(
    r'(?:^|/)(?:HANDOFF_[^/]*|NEXT_AGENT_HANDOFF|agent_handoff_log|KNOWN_ISSUES)(?:\.md)?$', re.I)
LOCAL_PATH = re.compile(r'(?i)C:(?:\\+|/)Users(?:\\+|/)(<[^>]+>|[^\\/\s`"\'<>]+)')
ALLOWED_USERS = {'example', 'public', 'default', 'test', 'testuser', 'user', 'runneradmin', '<user>', '<username>', '{username}', 'alice', 'bob', 'dev', 'owner', '<name>', '<you>'}
TEXT_EXTENSIONS = {'.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.css', '.html', '.md', '.json', '.jsonl', '.toml', '.yaml', '.yml', '.txt', '.ps1', '.cmd', '.sh'}

# These two files exist to describe the rules below, so they necessarily
# contain the strings the rules match. Exempting them by name (rather than
# letting them silently match) keeps the rules themselves greppable.
RULE_CARRIERS = {
    'scripts/forge/publish/content_check.py',
    'tests/test_public_distribution_content.py',
    # Names the prefixes it exists to strip.
    'docs/repo_hygiene_baseline.json',
}

# A public repository says what the software does. What it does badly is a
# private engineering record -- it belongs on the working branch, not in the
# tree people download and judge the project by.
SELF_CRITICAL = re.compile(
    r'known debt:'
    r'|known rough edges'
    r'|known issues'
    r'|debt, not (?:a |an )?(?:feature|features|furniture|capabilities)'
    r'|burst-generated|generated in one burst'
    r'|no real caller|never invoked'
    r'|not a shipping app|is a scaffold|scaffold-only'
    r'|half-fixed|we lied|is dishonest',
    re.I)

# Identifiers minted by the private coordination board. Real ones carry a
# date; the fictional ids tests are asked to use (HSK-777) do not.
INTERNAL_TASK_ID = re.compile(
    r'HSK-[0-9]{8}-[0-9]{6}'
    r'|[A-Z][A-Z0-9]*(?:-[A-Z0-9]+){2,}-20[0-9]{6}')

# Internal design records are never published, so nothing public should cite
# one -- a live citation points the reader at a file they cannot see.
INTERNAL_PLAN_PATH = re.compile(r'(?:docs/superpowers|\.superpowers)/')

# The same path wrapped across two lines. A line-based rule sees only the head
# and passes; the tail (`praxis-first-design.md §1.5`) sits on the next line and
# is still an internal record name. This cost a real leak once -- an automated
# sweep rewrote every head and left twenty tails behind, and the gate said PASS.
INTERNAL_PLAN_WRAPPED = re.compile(r'(?:docs/superpowers|\.superpowers)/\s*\S')

# A design record's own filename, with or without its directory: a leading
# ISO date then a slug. Published docs in this tree date-suffix instead
# (AGENT_AUDIT_2026-03-19.md), so this shape means an internal plan.
INTERNAL_PLAN_FILE = re.compile(r'\b20[0-9]{2}-[01][0-9]-[0-3][0-9]-[a-z0-9-]+\.md\b')

# An agent claim or board message, wherever it turns up.
COORDINATION_RECORD = re.compile(r'^\s*[-*]?\s*(?:msg_id=msg-[0-9]{8}|agent=[a-z0-9-]+;)')

# Ops ledgers ship their schema so the gates that read them keep working. They
# never ship the history recorded inside them.
LEDGERS = {
    'docs/ops/graveyard.json': 'records',
    'docs/ops/branch_claims.json': 'records',
}


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

    if path in LEDGERS:
        try:
            records = json.loads(text).get(LEDGERS[path]) or []
        except ValueError:
            records = []
        if records:
            errors.append(f'ops ledger carries {len(records)} internal record(s)')

    # Test and tooling sources legitimately contain sample claims, sample task
    # ids and board vocabulary -- they are what exercises the board code.
    working_source = path.startswith(('tests/', 'scripts/')) or path in RULE_CARRIERS
    is_prose = path.endswith('.md') and path not in RULE_CARRIERS

    # Checked against the whole file, not line by line, so a citation that wraps
    # across a line break cannot slip between two passing lines.
    if path not in RULE_CARRIERS and INTERNAL_PLAN_WRAPPED.search(text):
        errors.append('unpublished design-record path (wrapped across lines)')

    for i, line in enumerate(text.splitlines(), 1):
        if path == 'plans/thomas/WORKBOARD.md' and re.search(r'^\s*-\s*(?:msg_id=|agent=)', line):
            errors.append(f'populated coordination record at line {i}')
        if not working_source and COORDINATION_RECORD.search(line):
            errors.append(f'agent conversation record at line {i}')
        if not working_source and INTERNAL_TASK_ID.search(line):
            errors.append(f'internal task identifier at line {i}')
        if path not in RULE_CARRIERS and INTERNAL_PLAN_PATH.search(line):
            errors.append(f'unpublished design-record path at line {i}')
        if path not in RULE_CARRIERS and INTERNAL_PLAN_FILE.search(line):
            errors.append(f'unpublished design-record filename at line {i}')
        if is_prose and SELF_CRITICAL.search(line):
            errors.append(f'self-critical product claim at line {i}')
        for match in LOCAL_PATH.finditer(line):
            if match[1].lower() not in ALLOWED_USERS and not match[1].startswith(('$', '%', '[')):
                errors.append(f'personal machine path at line {i}')
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
