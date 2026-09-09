"""Tests for CAP-124: SCIM 2.0 user/group provisioning with directory sync.

Every test is hermetic: no network, no live IdP, temp dirs only, and injected
deterministic id/clock factories.  A hermetic fake IdP push (a list of desired
SCIM resources) exercises the directory-sync reconcile end to end.
"""

from __future__ import annotations

import itertools

import pytest

from thomas.security.scim import (
    GROUP_SCHEMA,
    LIST_RESPONSE_SCHEMA,
    PATCH_OP_SCHEMA,
    STORE_ENV,
    USER_SCHEMA,
    DirectoryStore,
    ScimError,
    ScimProvider,
)

# --------------------------------------------------------------------------- #
# Fixtures — deterministic id/clock, hermetic store
# --------------------------------------------------------------------------- #


@pytest.fixture
def provider(tmp_path):
    ids = (f"id-{n:03d}" for n in itertools.count(1))
    clock = itertools.count(1000)
    store = DirectoryStore(store_path=tmp_path / "scim.json")
    return ScimProvider(store=store, id_factory=lambda: next(ids), clock=lambda: float(next(clock)))


def _user(user_name, **extra):
    payload = {"schemas": [USER_SCHEMA], "userName": user_name, "active": True}
    payload.update(extra)
    return payload


def _patch(*operations):
    return {"schemas": [PATCH_OP_SCHEMA], "Operations": list(operations)}


# --------------------------------------------------------------------------- #
# create -> GET / list(filter)
# --------------------------------------------------------------------------- #


def test_create_user_then_get_and_list_by_filter(provider):
    created = provider.create_user(_user("alice@corp.com", emails=[{"value": "alice@corp.com", "primary": True}]))
    assert created["id"] == "id-001"
    assert created["schemas"] == [USER_SCHEMA]
    assert created["active"] is True
    assert created["meta"]["resourceType"] == "User"
    assert created["meta"]["version"].startswith('W/"')

    # GET by id round-trips the stored resource.
    assert provider.get_user("id-001") == created

    # A second user, then list filtered by userName eq — SCIM ListResponse shape.
    provider.create_user(_user("bob@corp.com"))
    listed = provider.list_users(filter='userName eq "alice@corp.com"')
    assert listed["schemas"] == [LIST_RESPONSE_SCHEMA]
    assert listed["totalResults"] == 1
    assert [r["userName"] for r in listed["Resources"]] == ["alice@corp.com"]

    # active eq true returns both; unfiltered list returns both.
    assert provider.list_users(filter="active eq true")["totalResults"] == 2
    assert provider.list_users()["totalResults"] == 2


def test_get_missing_user_raises_404(provider):
    with pytest.raises(ScimError) as exc:
        provider.get_user("nope")
    assert exc.value.status == 404


def test_duplicate_username_conflicts(provider):
    provider.create_user(_user("alice@corp.com"))
    with pytest.raises(ScimError) as exc:
        provider.create_user(_user("ALICE@corp.com"))  # userName is case-insensitive
    assert exc.value.status == 409
    assert exc.value.scim_type == "uniqueness"


# --------------------------------------------------------------------------- #
# PATCH replace / add / remove on a user (Okta + Entra dialect)
# --------------------------------------------------------------------------- #


def test_patch_replace_add_remove_on_user(provider):
    provider.create_user(_user("alice@corp.com", emails=[{"value": "alice@corp.com", "type": "work"}]))

    # replace scalar (Okta): path + value.
    patched = provider.patch_user("id-001", _patch({"op": "replace", "path": "active", "value": False}))
    assert patched["active"] is False

    # add appends to a multi-valued attribute.
    patched = provider.patch_user(
        "id-001",
        _patch({"op": "add", "path": "emails", "value": [{"value": "a2@corp.com", "type": "home"}]}),
    )
    assert {e["value"] for e in patched["emails"]} == {"alice@corp.com", "a2@corp.com"}

    # remove by value-filter path (Okta dialect).
    patched = provider.patch_user("id-001", _patch({"op": "remove", "path": 'emails[type eq "home"]'}))
    assert [e["value"] for e in patched["emails"]] == ["alice@corp.com"]

    # Entra path-less replace: value is an attribute map + case-insensitive op.
    patched = provider.patch_user("id-001", _patch({"op": "Replace", "value": {"active": True}}))
    assert patched["active"] is True


def test_patch_group_membership_add_and_remove(provider):
    provider.create_user(_user("alice@corp.com"))
    provider.create_user(_user("bob@corp.com"))
    group = provider.create_group({"schemas": [GROUP_SCHEMA], "displayName": "Engineers", "members": []})

    # add a member.
    group = provider.patch_group(group["id"], _patch({"op": "add", "path": "members", "value": [{"value": "id-001"}]}))
    assert [m["value"] for m in group["members"]] == ["id-001"]

    # add a second, then remove the first by value filter (Okta de-provision of membership).
    group = provider.patch_group(group["id"], _patch({"op": "add", "path": "members", "value": [{"value": "id-002"}]}))
    group = provider.patch_group(group["id"], _patch({"op": "remove", "path": 'members[value eq "id-001"]'}))
    assert [m["value"] for m in group["members"]] == ["id-002"]


def test_malformed_patch_op_rejected(provider):
    provider.create_user(_user("alice@corp.com"))
    # Unknown op verb.
    with pytest.raises(ScimError) as exc:
        provider.patch_user("id-001", _patch({"op": "frobnicate", "path": "active", "value": False}))
    assert exc.value.scim_type == "invalidSyntax"

    # remove without a path is illegal.
    with pytest.raises(ScimError):
        provider.patch_user("id-001", _patch({"op": "remove"}))

    # Empty Operations array.
    with pytest.raises(ScimError):
        provider.patch_user("id-001", {"schemas": [PATCH_OP_SCHEMA], "Operations": []})


# --------------------------------------------------------------------------- #
# PUT (replace) semantics
# --------------------------------------------------------------------------- #


def test_put_replaces_whole_resource(provider):
    provider.create_user(_user("alice@corp.com", emails=[{"value": "old@corp.com"}], displayName="Alice A"))
    replaced = provider.replace_user(
        "id-001",
        _user("alice@corp.com", emails=[{"value": "new@corp.com"}]),
    )
    # displayName present before is gone after a full PUT; emails fully replaced.
    assert "displayName" not in replaced
    assert [e["value"] for e in replaced["emails"]] == ["new@corp.com"]
    # id and creation timestamp preserved across the replace.
    assert replaced["id"] == "id-001"
    assert replaced["meta"]["created"] == 1000.0


# --------------------------------------------------------------------------- #
# de-provision -> active=false (soft, not a delete)
# --------------------------------------------------------------------------- #


def test_deprovision_sets_active_false_without_delete(provider):
    provider.create_user(_user("alice@corp.com"))
    deactivated = provider.deactivate_user("id-001")
    assert deactivated["active"] is False
    # Still present in the directory — soft deactivate, not a hard delete.
    assert provider.get_user("id-001")["active"] is False


def test_delete_user_removes_resource(provider):
    provider.create_user(_user("alice@corp.com"))
    provider.delete_user("id-001")
    with pytest.raises(ScimError):
        provider.get_user("id-001")
    with pytest.raises(ScimError):
        provider.delete_user("id-001")  # second delete -> 404


# --------------------------------------------------------------------------- #
# directory sync: reconcile adds / updates / removes
# --------------------------------------------------------------------------- #


def test_directory_sync_reconciles_adds_updates_removes(provider):
    # Seed: two active users + one group.
    provider.create_user(_user("alice@corp.com", emails=[{"value": "alice@corp.com"}]))
    provider.create_user(_user("bob@corp.com"))
    provider.create_group({"schemas": [GROUP_SCHEMA], "displayName": "OldTeam", "members": []})

    # Hermetic fake IdP push: alice changed (new email), carol is new, bob omitted;
    # groups: Engineers is new, OldTeam omitted.
    result = provider.sync_directory(
        users=[
            _user("alice@corp.com", emails=[{"value": "alice.new@corp.com"}]),
            _user("carol@corp.com"),
        ],
        groups=[{"schemas": [GROUP_SCHEMA], "displayName": "Engineers", "members": [{"value": "id-001"}]}],
    )

    assert result.updated_users == ("id-001",)  # alice updated
    assert result.created_users == ("id-004",)  # carol created (ids 1,2 users, 3 group, 4 carol)
    assert result.deactivated_users == ("id-002",)  # bob de-provisioned

    # Alice's email actually changed in the store.
    assert [e["value"] for e in provider.get_user("id-001")["emails"]] == ["alice.new@corp.com"]
    # Bob soft-deactivated, still present.
    assert provider.get_user("id-002")["active"] is False
    # Group reconcile: Engineers created, OldTeam removed.
    assert result.created_groups and result.removed_groups
    assert provider.list_groups(filter='displayName eq "OldTeam"')["totalResults"] == 0
    assert provider.list_groups(filter='displayName eq "Engineers"')["totalResults"] == 1


def test_sync_reactivates_returning_user(provider):
    provider.create_user(_user("alice@corp.com"))
    provider.deactivate_user("id-001")
    assert provider.get_user("id-001")["active"] is False
    # IdP pushes alice again (no explicit active) -> re-activated.
    result = provider.sync_directory(users=[_user("alice@corp.com")])
    assert "id-001" in result.updated_users
    assert provider.get_user("id-001")["active"] is True


def test_sync_idempotent_no_changes(provider):
    provider.create_user(_user("alice@corp.com"))
    desired = [_user("alice@corp.com")]
    provider.sync_directory(users=desired)
    second = provider.sync_directory(users=desired)
    assert second.created_users == ()
    assert second.updated_users == ()
    assert second.deactivated_users == ()


# --------------------------------------------------------------------------- #
# persistence round-trip
# --------------------------------------------------------------------------- #


def test_store_round_trip(provider, tmp_path):
    provider.create_user(_user("alice@corp.com", emails=[{"value": "alice@corp.com"}]))
    provider.create_group({"schemas": [GROUP_SCHEMA], "displayName": "Engineers", "members": [{"value": "id-001"}]})
    path = provider.store.save()

    reloaded = DirectoryStore.from_store(path)
    other = ScimProvider(store=reloaded, id_factory=lambda: "unused", clock=lambda: 0.0)
    assert other.get_user("id-001")["userName"] == "alice@corp.com"
    assert other.list_groups()["totalResults"] == 1
    # Full store payload round-trips exactly.
    assert reloaded.to_dict() == provider.store.to_dict()


def test_store_env_override(tmp_path, monkeypatch):
    target = tmp_path / "custom" / "dir.json"
    monkeypatch.setenv(STORE_ENV, str(target))
    store = DirectoryStore()
    assert store.store_path == target
