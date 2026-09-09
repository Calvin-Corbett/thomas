"""Hermetic tests for the persistent server-side sandbox store (CAP-063).

Acceptance (L2): sandboxes survive a server restart via a durable store + a
startup reconciler that adopts provider truth. Every test is hermetic — a
temp-dir SQLite store, an injected clock, and an in-memory FakeProvider. No
network, no container daemon.
"""

from __future__ import annotations

import itertools

import pytest

from thomas.tools.sandbox_store import (
    FakeProvider,
    ProviderSandbox,
    ProviderUnavailable,
    SandboxState,
    SandboxStore,
    SubprocessContainerProvider,
    TeardownPolicy,
    resolve_store_path,
)


@pytest.fixture
def clock():
    counter = itertools.count(1000)
    return lambda: next(counter)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "nested" / "sandbox_store.db"


def test_persists_across_simulated_restart_state_adopted_from_provider(db_path, clock):
    """A sandbox persists across a simulated restart (fresh store, same path)
    and its state is adopted from provider truth."""
    # First "boot": record a running sandbox.
    store = SandboxStore(db_path, clock=clock)
    store.record(
        "sb-1",
        spec={"image": "python:3.12", "cmd": ["sleep", "infinity"]},
        provider_ref="ctr-aaa",
        state=SandboxState.RUNNING,
        volume_metadata={"volume": "vol-aaa"},
    )
    store.close()

    # Simulated restart: brand-new store instance on the SAME path.
    fresh = SandboxStore(db_path, clock=clock)
    survivor = fresh.get("sb-1")
    assert survivor is not None, "sandbox did not survive the restart"
    assert survivor.spec["image"] == "python:3.12"

    # Provider truth says the container is now merely stopped (exited).
    provider = FakeProvider([ProviderSandbox(ref="ctr-aaa", state="exited")])
    report = fresh.reconcile(provider)

    assert report.adopted == ["sb-1"]
    adopted = fresh.get("sb-1")
    assert adopted is not None
    assert adopted.state is SandboxState.STOPPED  # synced from provider truth
    fresh.close()


def test_alive_in_store_but_gone_from_provider_is_marked_gone(db_path, clock):
    """A sandbox alive in the store but GONE from the provider is marked gone
    (and never resurrected on a later pass)."""
    store = SandboxStore(db_path, clock=clock)
    store.record("sb-2", spec={}, provider_ref="ctr-bbb", state=SandboxState.RUNNING)

    empty = FakeProvider([])
    report = store.reconcile(empty)
    assert report.marked_gone == ["sb-2"]
    assert store.get("sb-2").state is SandboxState.GONE

    # Later pass: even if the provider lists the ref again, a dead sandbox is
    # never resurrected.
    resurrected_attempt = FakeProvider([ProviderSandbox(ref="ctr-bbb", state="running")])
    report2 = store.reconcile(resurrected_attempt)
    assert "sb-2" in report2.skipped_dead
    assert "sb-2" not in report2.adopted
    assert store.get("sb-2").state is SandboxState.GONE
    # And it is NOT re-adopted as a brand-new record.
    assert report2.newly_adopted == []
    store.close()


def test_new_to_store_but_present_in_provider_is_adopted(db_path, clock):
    """A sandbox present in the provider but new to the store is adopted."""
    store = SandboxStore(db_path, clock=clock)
    provider = FakeProvider([ProviderSandbox(ref="ctr-ccc", state="running", spec={"image": "alpine"})])
    report = store.reconcile(provider)

    assert report.newly_adopted == ["adopted-ctr-ccc"]
    rec = store.get("adopted-ctr-ccc")
    assert rec is not None
    assert rec.provider_ref == "ctr-ccc"
    assert rec.state is SandboxState.RUNNING
    assert rec.spec["image"] == "alpine"
    store.close()


def test_teardown_policy_selects_durability(db_path, clock):
    """teardown_policy selects durability: volume kept vs removed."""
    store = SandboxStore(db_path, clock=clock)
    store.record(
        "keep",
        spec={},
        provider_ref="ctr-keep",
        state=SandboxState.RUNNING,
        teardown_policy=TeardownPolicy.KEEP_VOLUME,
        volume_metadata={"volume": "vol-keep"},
    )
    store.record(
        "drop",
        spec={},
        provider_ref="ctr-drop",
        state=SandboxState.RUNNING,
        teardown_policy=TeardownPolicy.REMOVE_VOLUME,
        volume_metadata={"volume": "vol-drop"},
    )

    kept = store.teardown("keep")
    dropped = store.teardown("drop")

    assert kept.state is SandboxState.GONE
    assert kept.volume_metadata == {"volume": "vol-keep"}  # durable disk retained
    assert dropped.state is SandboxState.GONE
    assert dropped.volume_metadata == {}  # ephemeral scratch discarded

    # Persisted, not just in-memory.
    assert store.get("keep").volume_metadata == {"volume": "vol-keep"}
    assert store.get("drop").volume_metadata == {}
    store.close()


def test_round_trip_preserves_all_fields(db_path, clock):
    """Round-trip: every recorded field survives a store-and-fetch."""
    store = SandboxStore(db_path, clock=clock)
    store.record(
        "sb-rt",
        spec={"image": "node:20", "env": {"A": "1"}},
        provider_ref="ctr-rt",
        state=SandboxState.RUNNING,
        teardown_policy=TeardownPolicy.REMOVE_VOLUME,
        process_metadata={"pid": 4321, "host": "worker-7"},
        volume_metadata={"volume": "vol-rt", "size_gb": 20},
    )
    rec = store.get("sb-rt")
    assert rec.spec == {"image": "node:20", "env": {"A": "1"}}
    assert rec.provider_ref == "ctr-rt"
    assert rec.state is SandboxState.RUNNING
    assert rec.teardown_policy is TeardownPolicy.REMOVE_VOLUME
    assert rec.process_metadata == {"pid": 4321, "host": "worker-7"}
    assert rec.volume_metadata == {"volume": "vol-rt", "size_gb": 20}
    assert rec.created_at >= 1000
    store.close()


def test_reconcile_mixed_population_and_restart(db_path, clock):
    """End-to-end: a mixed population reconciles correctly across a restart."""
    store = SandboxStore(db_path, clock=clock)
    store.record("survivor", spec={}, provider_ref="ctr-live", state=SandboxState.RUNNING)
    store.record("vanished", spec={}, provider_ref="ctr-dead", state=SandboxState.RUNNING)
    store.close()

    # Restart + reconcile: ctr-live still up, ctr-dead gone, ctr-new appears.
    fresh = SandboxStore(db_path, clock=clock)
    provider = FakeProvider(
        [
            ProviderSandbox(ref="ctr-live", state="running"),
            ProviderSandbox(ref="ctr-new", state="running"),
        ]
    )
    report = fresh.reconcile(provider)

    assert report.adopted == ["survivor"]
    assert report.marked_gone == ["vanished"]
    assert report.newly_adopted == ["adopted-ctr-new"]
    assert fresh.get("survivor").state is SandboxState.RUNNING
    assert fresh.get("vanished").state is SandboxState.GONE
    assert fresh.get("adopted-ctr-new").state is SandboxState.RUNNING
    fresh.close()


def test_env_overrides_store_path(tmp_path, monkeypatch):
    """The store path is env-overridable via THOMAS_SANDBOX_STORE_PATH."""
    target = tmp_path / "override" / "sb.db"
    monkeypatch.setenv("THOMAS_SANDBOX_STORE_PATH", str(target))
    assert resolve_store_path() == target
    store = SandboxStore()  # no explicit path -> uses env
    store.record("sb-env", spec={}, provider_ref="ctr-env", state=SandboxState.RUNNING)
    store.close()
    assert target.exists()


def test_subprocess_provider_parses_injected_runner():
    """The real default provider parses one-JSON-object-per-line lister output
    through an injected runner (no container daemon needed)."""
    lines = "\n".join(
        [
            '{"ID": "ctr-1", "State": "running", "Image": "python:3.12", "Names": "box1"}',
            '{"ID": "ctr-2", "State": "exited", "Image": "alpine", "Names": "box2"}',
            "",  # blank line tolerated
            "not-json",  # unparsable row skipped
        ]
    )
    provider = SubprocessContainerProvider(runner=lambda cmd: lines)
    live = provider.list_live()
    assert [p.ref for p in live] == ["ctr-1", "ctr-2"]
    assert live[0].state == "running"
    assert live[1].spec["image"] == "alpine"


def test_subprocess_provider_raises_provider_unavailable_on_fault():
    """A lister fault surfaces as ProviderUnavailable so reconcile can refuse to
    mass-mark-gone on a transient outage."""

    def boom(cmd):
        raise OSError("docker daemon not reachable")

    provider = SubprocessContainerProvider(runner=boom)
    with pytest.raises(ProviderUnavailable):
        provider.list_live()
