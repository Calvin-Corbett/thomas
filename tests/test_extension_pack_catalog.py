from __future__ import annotations

import json
from pathlib import Path

def test_extension_packs_have_valid_manifests_and_hooks() -> None:
    root = Path(__file__).resolve().parents[1] / 'extensions'
    packs = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith('pack-'))
    assert len(packs) >= 480

    ids: set[str] = set()
    for pack in packs:
        manifest_path = pack / 'manifest.json'
        hooks_path = pack / 'hooks.py'
        readme_path = pack / 'README.md'
        assert manifest_path.exists()
        assert hooks_path.exists()
        assert readme_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for key in ['id', 'name', 'version', 'entrypoint', 'capabilities']:
            assert key in manifest
        mid = str(manifest['id'])
        assert mid not in ids
        ids.add(mid)
        assert isinstance(manifest.get('capabilities'), list) and manifest['capabilities']
