"""TAP: the commit growth guard recognises a move (a split) and does not count it as growth.

scripts/forge/gates/commit_growth_guard.py is protected and sha256-pinned in the
enforcement manifest, so this runs only inside an owner breakglass window. A NEW
file whose non-blank lines are at least 80% lines deleted elsewhere in the same
commit is a move; it is reported as such and not as a violation. Evasion stays
hard: the content has to match line for line.
"""
import hashlib
import json
import pathlib

p = pathlib.Path('scripts/forge/gates/commit_growth_guard.py')
s = p.read_text(encoding='utf-8')
old_call = '        current = _rev_lines(repo_root, sha, rel)\n        prior = _rev_lines(repo_root, parent, rel)\n        growth = current - prior\n        if growth > max_growth:\n            violations.append('
new_call = '        current = _rev_lines(repo_root, sha, rel)\n        prior = _rev_lines(repo_root, parent, rel)\n        growth = current - prior\n        if growth > max_growth and prior == 0 and _moved_share(repo_root, sha, rel, files) >= MOVE_SHARE:\n            moves.append({"path": rel, "lines": current})\n            continue\n        if growth > max_growth:\n            violations.append('
assert s.count(old_call) == 1
s = s.replace(old_call, new_call, 1)
old_init = '    files = _changed_files(repo_root, base=parent, head=sha)\n\n    violations: list[dict] = []\n    scanned = 0\n'
new_init = '    files = _changed_files(repo_root, base=parent, head=sha)\n\n    violations: list[dict] = []\n    moves: list[dict] = []\n    scanned = 0\n'
assert s.count(old_init) == 1
s = s.replace(old_init, new_init, 1)
old_rec = '        "files_scanned": scanned,\n        "violations": violations,\n'
new_rec = '        "files_scanned": scanned,\n        "violations": violations,\n        "moves": moves,\n'
assert s.count(old_rec) == 1
s = s.replace(old_rec, new_rec, 1)
old_def = 'def _evaluate_commit(\n'
new_def = 'MOVE_SHARE = 0.8\n\n\ndef _moved_share(repo_root: Path, sha: str, rel: str, files: list[str]) -> float:\n    """Share of a new file\'s non-blank lines that were deleted elsewhere in the same commit.\n\n    A split moves code; it does not grow the codebase. Lines are compared\n    stripped, so re-indentation (a method moved out of a class) still matches.\n    """\n    others = [f for f in files if f != rel]\n    if not others:\n        return 0.0\n    proc = subprocess.run(\n        ["git", "show", sha, "--format=", "--unified=0", "--", *others],\n        cwd=repo_root,\n        capture_output=True,\n        text=True,\n        encoding="utf-8",\n        errors="replace",\n    )\n    deleted = {\n        line[1:].strip()\n        for line in proc.stdout.splitlines()\n        if line.startswith("-") and not line.startswith("---") and line[1:].strip()\n    }\n    shown = subprocess.run(\n        ["git", "show", f"{sha}:{rel}"], cwd=repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace"\n    )\n    new_lines = [line.strip() for line in shown.stdout.splitlines() if line.strip()]\n    if not new_lines:\n        return 0.0\n    return sum(1 for line in new_lines if line in deleted) / len(new_lines)\n\n\ndef _evaluate_commit(\n'
assert s.count(old_def) == 1
s = s.replace(old_def, new_def, 1)
p.write_text(s, encoding='utf-8', newline='\n')
print('guard patched')
manifest = pathlib.Path('scripts/forge/gates/enforcement_manifest.json')
m = json.loads(manifest.read_text(encoding='utf-8'))
key = 'scripts/forge/gates/commit_growth_guard.py'
assert key in m
m[key] = hashlib.sha256(p.read_bytes()).hexdigest()
manifest.write_text(json.dumps(m, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
print('manifest hash refreshed')
