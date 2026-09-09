"""Tests for the programmatic fleet management CRUD registry (CAP-135).

Covers, hermetically (temp store, injected clock, no network):
- full CRUD round-trip for each of the four kinds,
- create rejects a missing required field,
- create rejects a duplicate id,
- get/update/delete of an unknown id error cleanly,
- list filters (equality + tag membership),
- durability: state round-trips across a fresh manager on the same store,
- isolation: an agent id and a policy id do not collide.
"""

from __future__ import annotations

import itertools

import pytest

from thomas.core.fleet_management import (
    FLEET_KINDS,
    FleetConflictError,
    FleetDeletion,
    FleetManager,
    FleetNotFoundError,
    FleetRecord,
    FleetValidationError,
    resolve_fleet_store_path,
)


class _FakeClock:
    """Deterministic monotonically increasing clock."""

    def __init__(self, start: float = 1000.0, step: float = 1.0) -> None:
        self._counter = itertools.count()
        self._start = start
        self._step = step

    def __call__(self) -> float:
        return self._start + self._step * next(self._counter)


def _manager(tmp_path, clock=None):
    return FleetManager(tmp_path / "fleet.json", env={}, clock=clock or _FakeClock())


# One valid sample resource per kind, exercising every required field.
_SAMPLES = {
    "agents": {"id": "a1", "name": "Scout", "model": "gpt", "tags": ["core", "beta"]},
    "automations": {"id": "u1", "trigger": "on_push", "action": "run_tests", "enabled": True},
    "schedules": {"id": "s1", "cron": "0 * * * *", "target": "nightly", "tz": "UTC"},
    "policies": {"id": "p1", "rules": ["deny_all"], "priority": 5},
}
_UPDATES = {
    "agents": {"name": "Scout-2"},
    "automations": {"action": "deploy"},
    "schedules": {"cron": "*/5 * * * *"},
    "policies": {"priority": 9},
}


@pytest.mark.parametrize("kind", sorted(FLEET_KINDS))
def test_crud_round_trip_per_kind(tmp_path, kind):
    """create -> get -> list -> update -> delete for each kind."""
    mgr = _manager(tmp_path)
    sample = _SAMPLES[kind]
    rid = sample["id"]

    created = mgr.create(kind, sample)
    assert isinstance(created, FleetRecord)
    assert created.kind == kind and created.id == rid
    assert created.revision == 1

    # immediately gettable + listable
    got = mgr.get(kind, rid)
    assert got.id == rid
    assert got.data == sample
    assert [r.id for r in mgr.list(kind)] == [rid]

    # updated reflects the change and bumps revision
    changed_field, changed_value = next(iter(_UPDATES[kind].items()))
    updated = mgr.update(kind, rid, _UPDATES[kind])
    assert updated.data[changed_field] == changed_value
    assert updated.revision == 2
    assert mgr.get(kind, rid).data[changed_field] == changed_value

    # deleted is gone
    receipt = mgr.delete(kind, rid)
    assert isinstance(receipt, FleetDeletion)
    assert receipt.deleted is True and receipt.id == rid
    assert mgr.list(kind) == []
    with pytest.raises(FleetNotFoundError):
        mgr.get(kind, rid)


@pytest.mark.parametrize("kind", sorted(FLEET_KINDS))
def test_create_missing_required_field_rejected(tmp_path, kind):
    """A create missing a non-id required field is rejected."""
    mgr = _manager(tmp_path)
    required = FLEET_KINDS[kind]
    # drop the first required field that is not the id
    victim = next(f for f in required if f != "id")
    incomplete = {k: v for k, v in _SAMPLES[kind].items() if k != victim}
    with pytest.raises(FleetValidationError) as exc:
        mgr.create(kind, incomplete)
    assert victim in str(exc.value)


def test_create_missing_id_rejected(tmp_path):
    mgr = _manager(tmp_path)
    with pytest.raises(FleetValidationError):
        mgr.create("agents", {"name": "no-id"})
    with pytest.raises(FleetValidationError):
        mgr.create("agents", {"id": "   ", "name": "blank-id"})


@pytest.mark.parametrize("kind", sorted(FLEET_KINDS))
def test_duplicate_id_rejected(tmp_path, kind):
    """A second create with the same id is rejected and does not overwrite."""
    mgr = _manager(tmp_path)
    mgr.create(kind, _SAMPLES[kind])
    with pytest.raises(FleetConflictError):
        mgr.create(kind, _SAMPLES[kind])
    # still exactly one, unchanged
    assert len(mgr.list(kind)) == 1


def test_get_update_delete_unknown_id_errors_cleanly(tmp_path):
    mgr = _manager(tmp_path)
    with pytest.raises(FleetNotFoundError):
        mgr.get("agents", "ghost")
    with pytest.raises(FleetNotFoundError):
        mgr.update("agents", "ghost", {"name": "x"})
    with pytest.raises(FleetNotFoundError):
        mgr.delete("agents", "ghost")


def test_unknown_kind_errors(tmp_path):
    mgr = _manager(tmp_path)
    with pytest.raises(FleetValidationError):
        mgr.create("widgets", {"id": "x"})
    with pytest.raises(FleetValidationError):
        mgr.get("widgets", "x")


def test_update_cannot_blank_required_field(tmp_path):
    mgr = _manager(tmp_path)
    mgr.create("agents", _SAMPLES["agents"])
    with pytest.raises(FleetValidationError):
        mgr.update("agents", "a1", {"name": None})


def test_update_id_is_immutable(tmp_path):
    mgr = _manager(tmp_path)
    mgr.create("agents", _SAMPLES["agents"])
    with pytest.raises(FleetValidationError):
        mgr.update("agents", "a1", {"id": "a2"})


def test_list_filters_equality_and_tag_membership(tmp_path):
    mgr = _manager(tmp_path)
    mgr.create("agents", {"id": "a1", "name": "One", "team": "red", "tags": ["x", "y"]})
    mgr.create("agents", {"id": "a2", "name": "Two", "team": "blue", "tags": ["y", "z"]})
    mgr.create("agents", {"id": "a3", "name": "Three", "team": "red", "tags": ["z"]})

    # equality filter on a scalar field
    red = mgr.list("agents", {"team": "red"})
    assert {r.id for r in red} == {"a1", "a3"}

    # membership filter against a list-valued field
    tagged_y = mgr.list("agents", {"tags": "y"})
    assert {r.id for r in tagged_y} == {"a1", "a2"}

    # compound filter
    red_z = mgr.list("agents", {"team": "red", "tags": "z"})
    assert {r.id for r in red_z} == {"a3"}

    # no matches
    assert mgr.list("agents", {"team": "green"}) == []


def test_state_round_trips_across_fresh_manager(tmp_path):
    """A new manager on the same store sees all prior state and metadata."""
    store = tmp_path / "fleet.json"
    clock = _FakeClock()
    mgr1 = FleetManager(store, env={}, clock=clock)
    mgr1.create("agents", _SAMPLES["agents"])
    mgr1.create("policies", _SAMPLES["policies"])
    mgr1.update("agents", "a1", {"name": "Scout-2"})

    # brand-new manager, same file, independent in-memory state
    mgr2 = FleetManager(store, env={}, clock=_FakeClock(start=5000.0))
    agent = mgr2.get("agents", "a1")
    assert agent.data["name"] == "Scout-2"
    assert agent.revision == 2
    assert mgr2.get("policies", "p1").data["rules"] == ["deny_all"]

    # a delete by the fresh manager also persists
    mgr2.delete("agents", "a1")
    mgr3 = FleetManager(store, env={}, clock=_FakeClock())
    assert mgr3.list("agents") == []
    assert [r.id for r in mgr3.list("policies")] == ["p1"]


def test_kinds_are_isolated(tmp_path):
    """The same id in different kinds does not collide."""
    mgr = _manager(tmp_path)
    mgr.create("agents", {"id": "shared", "name": "Agent"})
    mgr.create("policies", {"id": "shared", "rules": ["allow"]})
    mgr.create("automations", {"id": "shared", "trigger": "t", "action": "a"})
    mgr.create("schedules", {"id": "shared", "cron": "* * * * *", "target": "tgt"})

    assert mgr.get("agents", "shared").data["name"] == "Agent"
    assert mgr.get("policies", "shared").data["rules"] == ["allow"]
    assert mgr.get("automations", "shared").data["action"] == "a"
    assert mgr.get("schedules", "shared").data["target"] == "tgt"

    # deleting the agent leaves the others untouched
    mgr.delete("agents", "shared")
    with pytest.raises(FleetNotFoundError):
        mgr.get("agents", "shared")
    assert mgr.get("policies", "shared").data["rules"] == ["allow"]
    assert len(mgr.list("automations")) == 1


def test_store_path_env_override(tmp_path):
    """THOMAS_FLEET_STORE overrides the default store path."""
    target = tmp_path / "custom" / "myfleet.json"
    resolved = resolve_fleet_store_path(env={"THOMAS_FLEET_STORE": str(target)})
    assert resolved == target.resolve()

    mgr = FleetManager(env={"THOMAS_FLEET_STORE": str(target)}, clock=_FakeClock())
    assert mgr.store_path == target.resolve()
    mgr.create("agents", {"id": "a1", "name": "n"})
    assert target.exists()


def test_corrupt_store_raises_clear_error(tmp_path):
    store = tmp_path / "fleet.json"
    store.write_text("{ not json", encoding="utf-8")
    with pytest.raises(Exception) as exc:
        FleetManager(store, env={}, clock=_FakeClock())
    assert "JSON" in str(exc.value) or "json" in str(exc.value)


def test_records_are_deep_copies_not_aliases(tmp_path):
    """Mutating a returned record's data must not leak into the store."""
    mgr = _manager(tmp_path)
    created = mgr.create("agents", {"id": "a1", "name": "n", "tags": ["a"]})
    created.data["tags"].append("mutated")
    assert mgr.get("agents", "a1").data["tags"] == ["a"]
