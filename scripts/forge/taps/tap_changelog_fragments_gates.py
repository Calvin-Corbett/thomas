"""TAP: the changelog gate and the release update gate accept a staged fragment under changelog.d/.

Both gates are protected (agent_safety.toml) and sha256-pinned in
scripts/forge/gates/enforcement_manifest.json, so this runs only inside an owner
breakglass window. Behaviour otherwise unchanged: CHANGELOG.md itself still works.
"""
import hashlib
import json
import pathlib


def patch(path, pairs):
    p = pathlib.Path(path)
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        assert s.count(old) == 1, (path, old[:60])
        s = s.replace(old, new, 1)
    p.write_text(s, encoding='utf-8', newline='\n')
    print('patched', path)
patch('scripts/forge/gates/changelog_gate.py', [('CODE_EXTENSIONS = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css", ".html"}\n', 'CODE_EXTENSIONS = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css", ".html"}\nFRAGMENT_PREFIX = "changelog.d/"\n\n\ndef _is_fragment(path: str) -> bool:\n    """A per-agent changelog fragment counts as the changelog (see scripts/forge/changelog_fragments.py)."""\n    return path.startswith(FRAGMENT_PREFIX) and path.endswith(".md") and not path.endswith("README.md")\n'), ('    diff_args.extend(["--", CHANGELOG_PATH])\n', '    diff_args.extend(["--", CHANGELOG_PATH, FRAGMENT_PREFIX])\n'), ('    changelog_staged = CHANGELOG_PATH in staged\n', '    fragments = [f for f in staged if _is_fragment(f)]\n    changelog_staged = CHANGELOG_PATH in staged or bool(fragments)\n'), ('    if len(code_files) >= threshold and not changelog_staged:\n', '    fragment_problems: list[str] = []\n    if fragments:\n        try:\n            from scripts.forge.changelog_fragments import check_fragment\n\n            fragment_problems = [p for f in fragments for p in check_fragment(ROOT / f)]\n        except ImportError:\n            fragment_problems = []\n    if fragment_problems:\n        ok = False\n        reason = "changelog fragment is malformed: " + "; ".join(fragment_problems)\n    elif len(code_files) >= threshold and not changelog_staged:\n')])
patch('scripts/forge/gates/release_update_gate.py', [('    changed_set = set(changed)\n    missing = sorted(REQUIRED_FILES - changed_set)\n', '    changed_set = set(changed)\n    if any(p.startswith("changelog.d/") and p.endswith(".md") and not p.endswith("README.md") for p in changed_set):\n        changed_set.add("CHANGELOG.md")  # a per-agent fragment is the changelog update\n    missing = sorted(REQUIRED_FILES - changed_set)\n'), ('        ["git", "diff", "--name-only", f"{base}...HEAD", "--", "CHANGELOG.md"],\n', '        ["git", "diff", "--name-only", f"{base}...HEAD", "--", "CHANGELOG.md", "changelog.d"],\n'), ('            ["git", "diff", "--name-only", "--", "CHANGELOG.md"],\n', '            ["git", "diff", "--name-only", "--", "CHANGELOG.md", "changelog.d"],\n')])
manifest = pathlib.Path('scripts/forge/gates/enforcement_manifest.json')
m = json.loads(manifest.read_text(encoding='utf-8'))
for key in ('scripts/forge/gates/changelog_gate.py', 'scripts/forge/gates/release_update_gate.py'):
    assert key in m, key
    m[key] = hashlib.sha256(pathlib.Path(key).read_bytes()).hexdigest()
manifest.write_text(json.dumps(m, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
print('manifest hashes refreshed')
