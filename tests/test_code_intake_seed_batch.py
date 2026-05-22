from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    mod_path = repo_root / "scripts" / "forge" / "intake" / "seed_batch.py"
    spec = importlib.util.spec_from_file_location("intake_seed_batch", mod_path)
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
    # The historical batch B01 CSV fixture was deleted in the 2026-05-21
    # pre-public cleanup (it carried 168 competitor-name references in
    # row content). The seed_batch loader is still tested via the smaller
    # fixture battery; this row check is skipped until a non-competitor
    # batch index lands.
    import pytest

    pytest.skip("batch B01 index fixture removed in 0.16.0 pre-public cleanup")
