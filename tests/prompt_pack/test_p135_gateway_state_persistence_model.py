from pathlib import Path

import pytest

from thomas.server.routes.gateway.p135_gateway_state_persistence_model import (
    GatewayStatePersistence,
    GatewayStatePersistenceError,
)


@pytest.mark.asyncio
async def test_memory_mode_roundtrip():
    p = GatewayStatePersistence()
    resp = await p.configure({"mode": "memory"})
    assert resp["mode"] == "memory"
    assert resp["state_file"] is None

    out1 = await p.set_state({"hello": "world"})
    assert out1["state"] == {"hello": "world"}
    assert out1["version"] == 1

    out2 = await p.get_state()
    assert out2["state"] == {"hello": "world"}
    assert out2["version"] == 1


@pytest.mark.asyncio
async def test_file_mode_persists_to_disk(tmp_path: Path):
    base_dir = tmp_path / "state"
    p = GatewayStatePersistence()
    resp = await p.configure({"mode": "file", "state_dir": str(base_dir)})
    assert resp["mode"] == "file"
    assert resp["state_dir"] == str((base_dir.resolve() / "gateway").resolve())
    assert resp["state_file"].endswith("gateway_state.json")

    out1 = await p.set_state({"a": 1})
    assert out1["state"] == {"a": 1}
    assert out1["version"] == 1

    p2 = GatewayStatePersistence()
    await p2.configure({"mode": "file", "state_dir": str(base_dir)})
    out2 = await p2.get_state()
    assert out2["state"] == {"a": 1}
    assert out2["version"] == 1


@pytest.mark.asyncio
async def test_invalid_mode_is_deterministic_error():
    p = GatewayStatePersistence()
    with pytest.raises(GatewayStatePersistenceError) as ei:
        await p.configure({"mode": "nope"})  # type: ignore[arg-type]
    err = ei.value
    assert err.code == "invalid_mode"
    assert err.http_status == 400


@pytest.mark.asyncio
async def test_file_mode_missing_state_dir_is_deterministic_error(monkeypatch):
    p = GatewayStatePersistence()
    monkeypatch.delenv("THOMAS_STATE_DIR", raising=False)
    with pytest.raises(GatewayStatePersistenceError) as ei:
        await p.configure({"mode": "file"})
    err = ei.value
    assert err.code == "missing_config"
    assert err.http_status == 400


@pytest.mark.asyncio
async def test_state_too_large_returns_413():
    p = GatewayStatePersistence()
    await p.configure({"mode": "memory", "max_state_bytes": 10})
    with pytest.raises(GatewayStatePersistenceError) as ei:
        await p.set_state({"big": "x" * 100})
    err = ei.value
    assert err.code == "state_too_large"
    assert err.http_status == 413


@pytest.mark.asyncio
async def test_version_conflict_returns_409():
    p = GatewayStatePersistence()
    await p.configure({"mode": "memory"})
    await p.set_state({"k": "v"})
    with pytest.raises(GatewayStatePersistenceError) as ei:
        await p.set_state({"k": "v2"}, expected_version=0)
    err = ei.value
    assert err.code == "version_conflict"
    assert err.http_status == 409
