"""TAP: teach the monolith guard to print the seam finder's advice under each Python violation.

scripts/forge/gates/monolith_guard.py is protected (agent_safety.toml) and hashed in
scripts/forge/gates/enforcement_manifest.json (also protected), so this runs only inside an
owner breakglass window. It edits the guard's violation loop and refreshes the manifest hash.
Advice only: any failure in the finder is swallowed so the guard's verdict never changes.
"""
import hashlib
import json
import pathlib
import re

guard = pathlib.Path('scripts/forge/gates/monolith_guard.py')
s = guard.read_text(encoding='utf-8')
old = '                print(\n                    f"- {row.get(\'path\')}: {row.get(\'lines\')} lines "\n                    f"(hard {hard}{max_part}{growth_part}) -> {row.get(\'reason\')}"\n                )\n    return 0 if result["ok"] else 1\n'
new = '                print(\n                    f"- {row.get(\'path\')}: {row.get(\'lines\')} lines "\n                    f"(hard {hard}{max_part}{growth_part}) -> {row.get(\'reason\')}"\n                )\n                _print_seam_advice(str(row.get("path") or ""), int(hard or 0))\n    return 0 if result["ok"] else 1\n\n\ndef _print_seam_advice(path: str, hard_limit: int) -> None:\n    """The guard says a file is too big; the seam finder says where it wants to be cut.\n\n    Advice for whoever splits, indented under the violation. Any failure here\n    is swallowed: the guard\'s verdict is size, and this must never change it.\n    """\n    if not path.endswith(".py"):\n        return\n    try:\n        from scripts.forge.seam_finder import find_seams\n\n        limit = min(hard_limit or 800, 800)\n        for line in find_seams(path, limit).render().splitlines()[1:]:\n            print(f"    {line}")\n    except Exception as exc:  # noqa: BLE001 - advice must not fail the gate\n        print(f"    (seam finder unavailable: {exc})")\n'
assert s.count(old) == 1, 'guard print block not found; re-read the file'
guard.write_text(s.replace(old, new, 1), encoding='utf-8', newline='\n')
print('guard patched:', guard, s.count('\n') + 1, '->', guard.read_text(encoding='utf-8').count('\n') + 1, 'lines')
manifest = pathlib.Path('scripts/forge/gates/enforcement_manifest.json')
m = json.loads(manifest.read_text(encoding='utf-8'))
digest = hashlib.sha256(guard.read_bytes()).hexdigest()
key = 'scripts/forge/gates/monolith_guard.py'
assert key in m, 'manifest is a flat path->sha256 map; key missing'
m[key] = digest
print('manifest hash updated:', m[key] == digest)
manifest.write_text(json.dumps(m, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
