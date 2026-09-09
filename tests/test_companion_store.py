from __future__ import annotations

from pathlib import Path

import pytest

from thomas.marketplace.companion.kernel import CompanionKernel
from thomas.marketplace.companion.store import (
    ModuleStore,
    ModuleStoreError,
    ModuleStoreQuotaError,
    StoreQuota,
)


def _kernel(tmp_path: Path) -> CompanionKernel:
    kernel = CompanionKernel(tmp_path / "companion")
    kernel.init_layout()
    return kernel


def test_init_layout_creates_data_dir(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    assert kernel.paths.data_dir.exists()
    assert kernel.paths.data_dir.is_dir()


def test_set_get_roundtrip(tmp_path: Path) -> None:
    store = ModuleStore(_kernel(tmp_path))
    store.set("fit.tracker", "workouts", [{"lift": "squat", "kg": 100}])
    assert store.get("fit.tracker", "workouts") == [{"lift": "squat", "kg": 100}]


def test_get_missing_key_returns_default(tmp_path: Path) -> None:
    store = ModuleStore(_kernel(tmp_path))
    assert store.get("fit.tracker", "nothing") is None
    assert store.get("fit.tracker", "nothing", "fallback") == "fallback"


def test_modules_cannot_see_each_other(tmp_path: Path) -> None:
    store = ModuleStore(_kernel(tmp_path))
    store.set("fit.tracker", "secret", "mine")
    assert store.get("other.module", "secret") is None
    assert store.keys("other.module") == []


def test_keys_and_delete(tmp_path: Path) -> None:
    store = ModuleStore(_kernel(tmp_path))
    store.set("fit.tracker", "a", 1)
    store.set("fit.tracker", "b", 2)
    assert store.keys("fit.tracker") == ["a", "b"]
    assert store.delete("fit.tracker", "a") is True
    assert store.delete("fit.tracker", "a") is False
    assert store.keys("fit.tracker") == ["b"]


def test_clear_drops_namespace(tmp_path: Path) -> None:
    store = ModuleStore(_kernel(tmp_path))
    store.set("fit.tracker", "a", 1)
    store.set("fit.tracker", "b", 2)
    assert store.clear("fit.tracker") == 2
    assert store.keys("fit.tracker") == []
    assert store.clear("fit.tracker") == 0


def test_usage_reports_quota(tmp_path: Path) -> None:
    store = ModuleStore(_kernel(tmp_path))
    store.set("fit.tracker", "a", "x")
    usage = store.usage("fit.tracker")
    assert usage["module_id"] == "fit.tracker"
    assert usage["key_count"] == 1
    assert usage["used_bytes"] > 0
    assert usage["quota"]["max_bytes"] > 0


@pytest.mark.parametrize("bad_id", ["", "ab", "../escape", "Upper", "with/slash", "with\\slash"])
def test_rejects_bad_module_ids(tmp_path: Path, bad_id: str) -> None:
    store = ModuleStore(_kernel(tmp_path))
    with pytest.raises(ModuleStoreError):
        store.set(bad_id, "key", "value")


@pytest.mark.parametrize("bad_key", ["", "has space", "has/slash", "_leading", "x" * 200])
def test_rejects_bad_keys(tmp_path: Path, bad_key: str) -> None:
    store = ModuleStore(_kernel(tmp_path))
    with pytest.raises(ModuleStoreError):
        store.set("fit.tracker", bad_key, "value")


def test_rejects_unserializable_value(tmp_path: Path) -> None:
    store = ModuleStore(_kernel(tmp_path))
    with pytest.raises(ModuleStoreError):
        store.set("fit.tracker", "key", {"fn": object()})


def test_byte_quota_enforced(tmp_path: Path) -> None:
    store = ModuleStore(_kernel(tmp_path), quota=StoreQuota(max_bytes=256, max_keys=100))
    with pytest.raises(ModuleStoreQuotaError):
        store.set("fit.tracker", "big", "x" * 2048)


def test_key_quota_enforced(tmp_path: Path) -> None:
    store = ModuleStore(_kernel(tmp_path), quota=StoreQuota(max_bytes=1_000_000, max_keys=2))
    store.set("fit.tracker", "a", 1)
    store.set("fit.tracker", "b", 2)
    with pytest.raises(ModuleStoreQuotaError):
        store.set("fit.tracker", "c", 3)


def test_quota_rejection_leaves_prior_value_intact(tmp_path: Path) -> None:
    store = ModuleStore(_kernel(tmp_path), quota=StoreQuota(max_bytes=400, max_keys=10))
    store.set("fit.tracker", "keep", "small")
    with pytest.raises(ModuleStoreQuotaError):
        store.set("fit.tracker", "big", "x" * 4096)
    assert store.get("fit.tracker", "keep") == "small"


def test_corrupt_document_reads_as_empty(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    store = ModuleStore(kernel)
    store.set("fit.tracker", "a", 1)
    (kernel.paths.data_dir / "fit.tracker.json").write_text("{not json", encoding="utf-8")
    assert store.keys("fit.tracker") == []
    store.set("fit.tracker", "b", 2)
    assert store.get("fit.tracker", "b") == 2
