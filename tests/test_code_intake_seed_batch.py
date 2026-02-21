from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    mod_path = repo_root / "scripts" / "code_intake_seed_batch.py"
    spec = importlib.util.spec_from_file_location("code_intake_seed_batch", mod_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_channels_domain_uses_channel_ops_path() -> None:
    mod = _load_module()
    allowed = mod._domain_allowed_paths("channels")
    assert "thomas/cli/commands/channel_ops" in allowed
    assert "thomas/cli/commands/channels.py" in allowed


def test_load_rows_has_batch_b01() -> None:
    mod = _load_module()
    repo_root = Path(__file__).resolve().parents[1]
    idx = repo_root / "docs" / "OPENCLAW_CATCHUP_PROMPT_BATCH_INDEX_216_2026-02-20.csv"
    rows = mod._load_rows(idx, "B01")
    assert rows
    assert rows[0]["prompt_id"] == "P001"
