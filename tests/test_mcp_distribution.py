"""Tests for CAP-069: Team MCP distribution.

Acceptance line: "Add central admin distribution, group policy, cross-surface
refresh, and audit history."

Proves, end to end and hermetically (temp dirs, env-redirected stores, no
network, no subprocess):

- an admin distributes an approved set of catalog servers;
- a member in an *allowed* group receives exactly the permitted servers, while
  denied / not-allow-listed servers are withheld *with a reason*;
- an admin update (add + remove servers) followed by a member refresh installs
  the new servers into the member's local registry and prunes the removed ones;
- the audit history records every distribute, policy change, and member refresh
  in order;
- the whole manifest (servers, policy, ordered audit) round-trips from disk.

The member's local compat registry is redirected via ``THOMAS_MCP_REGISTRY_PATH``
(the same store CAP-068 installs into) so installs/prunes are observable and the
CAP-068 loader can read them back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.cli.parity_support import load_mcp_registry
from thomas.core.config import AppConfig, MemoryConfig
from thomas.tools.mcp_client import client_from_server_row
from thomas.tools.mcp_distribution import (
    ACTION_DISTRIBUTE,
    ACTION_REFRESH,
    ACTION_SET_POLICY,
    DistributionAdmin,
    DistributionError,
    DistributionMember,
    GroupPolicy,
    load_manifest,
    manifest_path,
)
from thomas.tools.mcp_registry import REGISTRY_PATH_ENV, registry_store_path


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(memory=MemoryConfig(root=str(tmp_path)))


@pytest.fixture()
def redirected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    """A member config whose local compat registry is redirected to a temp file."""
    config = _config(tmp_path)
    monkeypatch.setenv(REGISTRY_PATH_ENV, str(registry_store_path(config)))
    return config


def _registry_names(config: AppConfig) -> set[str]:
    return {row["name"] for row in load_mcp_registry(config)}


# --- central admin distribution ----------------------------------------------
def test_distribute_publishes_catalog_set(tmp_path: Path) -> None:
    admin = DistributionAdmin(path=tmp_path / "dist.json")
    manifest = admin.distribute(["sqlite", "git", "filesystem"])
    assert set(manifest.servers) == {"sqlite", "git", "filesystem"}
    assert manifest.version == 1
    # Reload from disk: durable and identical.
    reloaded = load_manifest(tmp_path / "dist.json")
    assert reloaded.servers == manifest.servers
    assert reloaded.version == 1


def test_distribute_rejects_unknown_server(tmp_path: Path) -> None:
    admin = DistributionAdmin(path=tmp_path / "dist.json")
    with pytest.raises(DistributionError):
        admin.distribute(["sqlite", "not-a-real-server"])


# --- group policy: permitted vs withheld-with-reason -------------------------
def test_group_policy_permits_and_withholds_with_reason(tmp_path: Path) -> None:
    path = tmp_path / "dist.json"
    admin = DistributionAdmin(path=path)
    admin.distribute(["sqlite", "git", "filesystem", "fetch"])
    # engineering: allow all except filesystem (deny).
    admin.set_group_policy("engineering", deny=["filesystem"])
    # analysts: allow-list of only sqlite + fetch.
    admin.set_group_policy("analysts", allow=["sqlite", "fetch"])

    manifest = admin.load()
    from thomas.tools.mcp_distribution import resolve_for_group

    eng_permitted, eng_withheld = resolve_for_group(manifest, "engineering")
    assert eng_permitted == ["fetch", "git", "sqlite"]
    assert [(w.name, w.reason) for w in eng_withheld] == [("filesystem", "denied by group policy")]

    an_permitted, an_withheld = resolve_for_group(manifest, "analysts")
    assert an_permitted == ["fetch", "sqlite"]
    assert {w.name for w in an_withheld} == {"filesystem", "git"}
    assert all(w.reason == "not in group allow-list" for w in an_withheld)


def test_resolve_unknown_group_raises(tmp_path: Path) -> None:
    admin = DistributionAdmin(path=tmp_path / "dist.json")
    admin.distribute(["sqlite"])
    from thomas.tools.mcp_distribution import resolve_for_group

    with pytest.raises(DistributionError):
        resolve_for_group(admin.load(), "ghost-group")


def test_group_policy_decide_direct() -> None:
    policy = GroupPolicy(allow=("sqlite",), deny=("git",))
    assert policy.decide("sqlite") == (True, "")
    assert policy.decide("git") == (False, "denied by group policy")
    assert policy.decide("fetch") == (False, "not in group allow-list")


# --- member refresh: install permitted, withhold denied ----------------------
def test_member_receives_exactly_permitted_servers(tmp_path: Path, redirected: AppConfig) -> None:
    path = tmp_path / "dist.json"
    admin = DistributionAdmin(path=path)
    admin.distribute(["sqlite", "git", "filesystem"])
    admin.set_group_policy("engineering", deny=["filesystem"])

    member = DistributionMember(config=redirected, manifest_path_override=path)
    result = member.refresh("engineering")

    # Received exactly the permitted set; denied server withheld with a reason.
    assert set(result.permitted) == {"sqlite", "git"}
    assert set(result.installed) == {"sqlite", "git"}
    assert result.updated == ()
    assert [(w.name, w.reason) for w in result.withheld] == [("filesystem", "denied by group policy")]

    # The member's *local* registry holds exactly the two permitted servers,
    # and each is a real, launchable compat row (CAP-068 round-trip).
    assert _registry_names(redirected) == {"sqlite", "git"}
    row = next(r for r in load_mcp_registry(redirected) if r["name"] == "git")
    client = client_from_server_row(row)
    assert client.name == "git"
    assert not client.running


# --- cross-surface refresh: install new, prune removed -----------------------
def test_admin_update_then_refresh_installs_new_and_prunes_removed(tmp_path: Path, redirected: AppConfig) -> None:
    path = tmp_path / "dist.json"
    admin = DistributionAdmin(path=path)
    admin.set_group_policy("everyone", allow=[])  # allow-all
    admin.distribute(["sqlite", "git"])

    member = DistributionMember(config=redirected, manifest_path_override=path)
    first = member.refresh("everyone")
    assert set(first.installed) == {"sqlite", "git"}
    assert _registry_names(redirected) == {"sqlite", "git"}

    # Admin updates the distribution: drop git, add filesystem + fetch.
    admin.distribute(["sqlite", "filesystem", "fetch"])
    second = member.refresh("everyone")

    assert set(second.installed) == {"filesystem", "fetch"}  # newly added
    assert set(second.updated) == {"sqlite"}  # already had it
    assert set(second.pruned) == {"git"}  # removed from distribution
    # Local registry now reflects exactly the new distributed set.
    assert _registry_names(redirected) == {"sqlite", "filesystem", "fetch"}


def test_refresh_prunes_when_policy_now_denies(tmp_path: Path, redirected: AppConfig) -> None:
    path = tmp_path / "dist.json"
    admin = DistributionAdmin(path=path)
    admin.set_group_policy("team", allow=[])
    admin.distribute(["sqlite", "git"])

    member = DistributionMember(config=redirected, manifest_path_override=path)
    member.refresh("team")
    assert _registry_names(redirected) == {"sqlite", "git"}

    # Policy tightens to deny git; refresh must withdraw it from the member.
    admin.set_group_policy("team", deny=["git"])
    result = member.refresh("team")
    assert set(result.pruned) == {"git"}
    assert [w.name for w in result.withheld] == ["git"]
    assert _registry_names(redirected) == {"sqlite"}


# --- audit history: ordered, append-only, round-trips ------------------------
def test_audit_history_records_each_action_in_order(tmp_path: Path, redirected: AppConfig) -> None:
    path = tmp_path / "dist.json"
    admin = DistributionAdmin(path=path, actor="alice")
    admin.distribute(["sqlite", "git"])
    admin.set_group_policy("team", deny=["git"])

    member = DistributionMember(config=redirected, manifest_path_override=path, member_id="bob")
    member.refresh("team")

    history = admin.audit_history()
    actions = [(e.seq, e.action, e.actor) for e in history]
    assert actions == [
        (1, ACTION_DISTRIBUTE, "alice"),
        (2, ACTION_SET_POLICY, "alice"),
        (3, ACTION_REFRESH, "bob"),
    ]
    # Sequence numbers are strictly increasing (append-only, ordered).
    seqs = [e.seq for e in history]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)

    # The refresh entry captures what actually changed.
    refresh_entry = history[-1]
    assert refresh_entry.detail["group"] == "team"
    assert refresh_entry.detail["member"] == "bob"
    assert refresh_entry.detail["installed"] == ["sqlite"]
    assert refresh_entry.detail["pruned"] == []

    # Round-trip: reload from disk and confirm the ordered history survives.
    reloaded = load_manifest(path)
    assert [(e.seq, e.action) for e in reloaded.audit] == [
        (1, ACTION_DISTRIBUTE),
        (2, ACTION_SET_POLICY),
        (3, ACTION_REFRESH),
    ]
    assert reloaded.groups["team"].deny == ("git",)


def test_audit_is_append_only_across_refreshes(tmp_path: Path, redirected: AppConfig) -> None:
    path = tmp_path / "dist.json"
    admin = DistributionAdmin(path=path)
    admin.set_group_policy("team", allow=[])
    admin.distribute(["sqlite"])

    member = DistributionMember(config=redirected, manifest_path_override=path)
    member.refresh("team")
    member.refresh("team")  # second refresh: no changes, but still audited

    history = admin.audit_history()
    refresh_entries = [e for e in history if e.action == ACTION_REFRESH]
    assert len(refresh_entries) == 2
    # Earlier entries are never rewritten: seqs remain contiguous and ordered.
    assert [e.seq for e in history] == list(range(1, len(history) + 1))


# --- path resolution ---------------------------------------------------------
def test_manifest_path_prefers_env_then_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.tools.mcp_distribution import DISTRIBUTION_PATH_ENV

    monkeypatch.delenv(DISTRIBUTION_PATH_ENV, raising=False)
    config = _config(tmp_path)
    assert manifest_path(config) == tmp_path / ".thomas" / "cli" / "mcp_distribution.json"

    override = tmp_path / "custom" / "dist.json"
    monkeypatch.setenv(DISTRIBUTION_PATH_ENV, str(override))
    assert manifest_path(config) == override

    monkeypatch.delenv(DISTRIBUTION_PATH_ENV, raising=False)
    with pytest.raises(DistributionError):
        manifest_path(None)
