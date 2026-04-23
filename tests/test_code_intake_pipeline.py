from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    mod_path = repo_root / "scripts" / "code_intake.py"
    spec = importlib.util.spec_from_file_location("code_intake", mod_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_diff_touched_paths_extracts_paths() -> None:
    mod = _load_module()
    diff = """\
diff --git a/thomas/cli/main.py b/thomas/cli/main.py
index 1111111..2222222 100644
--- a/thomas/cli/main.py
+++ b/thomas/cli/main.py
@@ -1,1 +1,2 @@
 print("old")
+print("new")
"""
    touched = mod.parse_diff_touched_paths(diff)
    assert touched == {"thomas/cli/main.py"}


def test_validate_blocks_name_guard_hit_when_strict(tmp_path: Path) -> None:
    mod = _load_module()
    repo = Path(__file__).resolve().parents[1]
    intake_root = tmp_path / "code_intake"
    drop_dir = intake_root / "queue" / "incoming" / "DTEST_001"
    drop_dir.mkdir(parents=True, exist_ok=True)

    diff_path = drop_dir / "change.diff"
    diff_path.write_text(
        """\
diff --git a/docs/demo.txt b/docs/demo.txt
index 1111111..2222222 100644
--- a/docs/demo.txt
+++ b/docs/demo.txt
@@ -0,0 +1,1 @@
+OpenClaw naming should be blocked by strict guard.
""",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 1,
        "drop_id": "DTEST_001",
        "prompt_id": "P001",
        "batch_id": "B01",
        "title": "test",
        "artifact": {"type": "unified_diff", "path": "change.diff", "sha256": ""},
        "ownership": {"allowed_paths": ["docs"], "forbidden_paths": []},
        "policy": {
            "strict_name_guard": True,
            "name_guard_blocklist": ["openclaw"],
        },
        "tests": {"commands": []},
        "meta": {"source": "test", "created_at": "2026-02-20T00:00:00+00:00", "notes": ""},
    }
    manifest_path = drop_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = mod._validate_manifest(manifest_path, repo, run_git_apply_check=False)
    assert report["ok"] is False
    codes = [e.get("code") for e in report["errors"]]
    assert "name_guard_violation" in codes
