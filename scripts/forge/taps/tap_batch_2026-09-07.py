"""ONE owner window, four taps. Run from the repo root after `python scripts/breakglass_window.py on`.

1. guard prints seam advice under each .py violation   (tap_guard_seam_hint.py)
2. changelog and release gates accept a staged fragment (tap_changelog_fragments_gates.py)
3. growth guard recognises a move as not-growth         (tap_growth_guard_moves.py)
4. stale repl.py waiver leaves the monolith baseline    (inline below)
Then the xfail marker comes off tests/test_commit_growth_guard_moves.py, and the
verification commands print PASS. Commit with the SKIP env (see taps_ready.txt);
`python scripts/breakglass_window.py off` when the commit is in.
"""
import json
import os
import pathlib
import runpy
import subprocess
import sys

S = pathlib.Path(__file__).resolve().parent
for name in ('tap_guard_seam_hint.py', 'tap_changelog_fragments_gates.py', 'tap_growth_guard_moves.py'):
    print(f'== {name}')
    runpy.run_path(str(S / name), run_name='__main__')
b = pathlib.Path('docs/monolith_guard_baseline.json')
m = json.loads(b.read_text(encoding='utf-8'))
if 'thomas/cli/repl.py' in m.get('allowed_large_files', {}):
    del m['allowed_large_files']['thomas/cli/repl.py']
    b.write_text(json.dumps(m, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print('== baseline: repl.py waiver removed (file is 626 lines)')
t = pathlib.Path('tests/test_commit_growth_guard_moves.py')
s = t.read_text(encoding='utf-8')
marker = '@pytest.mark.xfail(strict=True, reason="waits on the growth-guard tap (tap_growth_guard_moves.py)")\n'
if marker in s:
    t.write_text(s.replace(marker, '', 1), encoding='utf-8', newline='\n')
    print('== xfail marker removed from the move test')
print('== verify')
for cmd in (['python', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests/test_commit_growth_guard_moves.py', 'tests/test_changelog_fragments.py', 'tests/test_monolith_guard.py', 'tests/test_seam_finder.py'], ['python', 'scripts/forge/gates/changelog_gate.py', '--json'], ['ruff', 'check', 'scripts/forge/gates/monolith_guard.py', 'scripts/forge/gates/changelog_gate.py', 'scripts/forge/gates/release_update_gate.py', 'scripts/forge/gates/commit_growth_guard.py']):
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(' '.join(cmd[:4]), '->', (r.stdout + r.stderr).strip().splitlines()[-1][:120] if (r.stdout + r.stderr).strip() else f'exit {r.returncode}')
