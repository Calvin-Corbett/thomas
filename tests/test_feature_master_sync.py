from __future__ import annotations

import json
from pathlib import Path

from scripts import sync_feature_master_list as sync


def test_feature_master_sync_writes_and_checks(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    (repo / "thomas" / "core").mkdir(parents=True, exist_ok=True)
    (repo / "Inbox").mkdir(parents=True, exist_ok=True)

    (repo / "thomas" / "core" / "tool_factory.py").write_text("# ok\n", encoding="utf-8")
    (repo / "Inbox" / "pack.zip").write_text("zip", encoding="utf-8")

    manifest = {
        "version": 1,
        "foundation": [
            {
                "name": "Tool Factory",
                "location": "thomas/core/tool_factory.py",
                "notes": "foundation",
                "code_paths": ["thomas/core/tool_factory.py"],
            }
        ],
        "features": [
            {
                "id": 1,
                "name": "Feature A",
                "location": "thomas/core/a.py",
                "code_paths": ["thomas/core/a.py"],
                "inbox_globs": ["Inbox/**/pack.zip"],
            }
        ],
        "inbox_packs": [
            {
                "name": "Pack B",
                "location": "thomas/core/b.py",
                "code_paths": ["thomas/core/b.py"],
                "inbox_globs": ["Inbox/**/pack.zip"],
                "source_zip": "pack.zip",
            }
        ],
    }
    manifest_path = repo / "docs" / "feature_master_manifest.json"
    master_path = repo / "docs" / "FEATURE_MASTER_LIST.md"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rc = sync.run(
        [
            "--repo-root",
            str(repo),
            "--manifest",
            str(manifest_path),
            "--master",
            str(master_path),
        ]
    )
    assert rc == 0
    text = master_path.read_text(encoding="utf-8")
    assert "✅ DONE" in text
    assert "📦 INBOX" in text

    rc = sync.run(
        [
            "--repo-root",
            str(repo),
            "--manifest",
            str(manifest_path),
            "--master",
            str(master_path),
            "--check",
        ]
    )
    assert rc == 0

    master_path.write_text(text + "\n# drift\n", encoding="utf-8")
    rc = sync.run(
        [
            "--repo-root",
            str(repo),
            "--manifest",
            str(manifest_path),
            "--master",
            str(master_path),
            "--check",
        ]
    )
    assert rc == 1
