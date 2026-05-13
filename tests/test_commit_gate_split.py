from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parent.parent
agent_commit = _load_module('agent_commit', ROOT / 'scripts' / 'agent_commit.py')
merge_readiness = _load_module('check_merge_readiness', ROOT / 'scripts' / 'forge' / 'gates' / 'merge_readiness.py')


def test_precommit_config_moves_global_gates_to_merge_readiness() -> None:
    content = (ROOT / '.pre-commit-config.yaml').read_text(encoding='utf-8')

    assert 'id: thomas-merge-readiness' in content
    assert 'entry: python scripts/forge/gates/merge_readiness.py' in content
    assert 'stages: [pre-push]' in content
    assert 'id: thomas-repo-hygiene-gate' not in content
    assert 'id: thomas-release-hygiene-gate' not in content
    assert 'id: thomas-architecture' not in content
    assert 'id: thomas-workboard-audit-backstop-gate' not in content


def test_agent_commit_local_gate_commands_ignore_release_metadata() -> None:
    local_gates = dict(agent_commit.LOCAL_GATE_COMMANDS)
    merge_gates = dict(merge_readiness.MERGE_GATE_COMMANDS)
    changed_gate = local_gates['workboard_changed_files']
    claim_gate = local_gates['workboard_agent_claim']
    folder_guard = local_gates['active_folder_guard']

    assert '--ignore' in changed_gate
    assert 'CHANGELOG.md,pyproject.toml,thomas/__init__.py' in changed_gate
    assert '--staged-scope-ignore' in claim_gate
    assert 'CHANGELOG.md,pyproject.toml,thomas/__init__.py' in claim_gate
    assert '--allow-presence-override' in folder_guard
    assert '--presence-override-reason' in folder_guard
    assert 'scoped local commit isolates claimed changes from unrelated dirty repo activity' in folder_guard
    assert 'plan_structure' not in local_gates
    assert 'auto_checks_quick' not in local_gates
    assert merge_gates['plan_structure'] == (sys.executable, 'scripts/forge/gates/plan_structure_gate.py')
    assert merge_gates['auto_checks_quick'] == (sys.executable, 'scripts/auto_checks.py', '--quick')


def test_merge_readiness_can_fail_while_local_scoped_commit_path_stays_separate(tmp_path, monkeypatch) -> None:
    repo = tmp_path / 'repo'
    repo.mkdir()

    monkeypatch.setattr(
        merge_readiness,
        'MERGE_GATE_COMMANDS',
        ((
            'architecture',
            (sys.executable, '-c', 'import sys; sys.exit(1)'),
        ),),
    )
    ok, results = merge_readiness.evaluate_merge_readiness(repo_root=repo, commands=merge_readiness.MERGE_GATE_COMMANDS)

    assert ok is False
    assert results[0]['name'] == 'architecture'
    assert results[0]['ok'] is False
