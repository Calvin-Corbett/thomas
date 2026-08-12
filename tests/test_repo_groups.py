"""Tests for named repo groups with pinned revisions and access boundaries.

Covers the exact CAP-057 Level-2 acceptance line: named groups with pinned
revisions and enforced read/write boundaries. All hermetic -- no network, no
live repos; only temp files and in-memory registries.
"""

from __future__ import annotations

import json

import pytest

from thomas.tools.repo_groups import (
    ACCESS_READ_ONLY,
    ACCESS_READ_WRITE,
    MODE_READ,
    MODE_WRITE,
    STORE_PATH_ENV,
    RepoGroupError,
    RepoGroupRegistry,
    RepoMember,
    build_member,
    classify_pin,
    with_revision,
)

_SHA = "a" * 40  # a valid 40-hex commit sha
_SHA2 = "0123456789abcdef0123456789abcdef01234567"


def _registry_with_group(store_path=None) -> RepoGroupRegistry:
    reg = RepoGroupRegistry(store_path=store_path)
    reg.define_group(
        "core-stack",
        [
            build_member("https://example.com/org/app.git", _SHA, access=ACCESS_READ_WRITE, name="app"),
            build_member("https://example.com/org/lib.git", "v1.2.3", access=ACCESS_READ_ONLY, name="lib"),
        ],
        description="app plus its vendored library",
    )
    return reg


# -- named group + pinned members + resolve -----------------------------------
def test_resolve_returns_members_and_pins() -> None:
    reg = _registry_with_group()
    resolved = reg.resolve("core-stack")
    assert resolved.name == "core-stack"
    assert len(resolved.members) == 2
    pins = resolved.pins
    assert pins["https://example.com/org/app.git"] == _SHA
    assert pins["https://example.com/org/lib.git"] == "v1.2.3"


def test_unknown_group_raises() -> None:
    reg = RepoGroupRegistry()
    with pytest.raises(RepoGroupError):
        reg.resolve("nope")


def test_empty_group_rejected() -> None:
    reg = RepoGroupRegistry()
    with pytest.raises(RepoGroupError):
        reg.define_group("empty", [])


# -- read/write boundary enforcement ------------------------------------------
def test_write_to_read_only_member_denied_with_reason() -> None:
    reg = _registry_with_group()
    decision = reg.check_access("core-stack", "https://example.com/org/lib.git", MODE_WRITE)
    assert decision.allowed is False
    assert bool(decision) is False
    assert "read-only" in decision.reason
    assert "lib" in decision.reason


def test_read_to_read_only_member_allowed() -> None:
    reg = _registry_with_group()
    decision = reg.check_access("core-stack", "https://example.com/org/lib.git", MODE_READ)
    assert decision.allowed is True
    assert bool(decision) is True


def test_write_to_read_write_member_allowed() -> None:
    reg = _registry_with_group()
    decision = reg.check_access("core-stack", "https://example.com/org/app.git", MODE_WRITE)
    assert decision.allowed is True


def test_access_to_non_member_repo_denied() -> None:
    reg = _registry_with_group()
    decision = reg.check_access("core-stack", "https://example.com/org/other.git", MODE_READ)
    assert decision.allowed is False
    assert "not a member" in decision.reason


def test_unrecognised_mode_denied() -> None:
    reg = _registry_with_group()
    decision = reg.check_access("core-stack", "https://example.com/org/app.git", "delete")
    assert decision.allowed is False
    assert "unrecognised access mode" in decision.reason


def test_dot_git_and_trailing_slash_normalize_to_same_member() -> None:
    reg = _registry_with_group()
    # stored as ".../lib.git"; query without .git and with trailing slash
    decision = reg.check_access("core-stack", "https://example.com/org/lib/", MODE_WRITE)
    assert decision.allowed is False
    assert "read-only" in decision.reason


def test_member_name_alias_matches() -> None:
    reg = _registry_with_group()
    decision = reg.check_access("core-stack", "lib", MODE_WRITE)
    assert decision.allowed is False
    assert "read-only" in decision.reason


# -- pin integrity ------------------------------------------------------------
def test_verify_pins_all_pinned_ok() -> None:
    reg = _registry_with_group()
    report = reg.verify_pins("core-stack")
    assert report.ok is True
    assert report.issues == ()


def test_verify_pins_flags_unpinned_member() -> None:
    reg = RepoGroupRegistry()
    reg.define_group(
        "floating",
        [
            build_member("repoA", _SHA, access=ACCESS_READ_ONLY),
            build_member("repoB", "", access=ACCESS_READ_WRITE),  # accidental floating member
        ],
    )
    report = reg.verify_pins("floating")
    assert report.ok is False
    assert len(report.unpinned) == 1
    issue = report.unpinned[0]
    assert issue.repo == "repoB"
    assert "unpinned" in issue.reason.lower()


def test_verify_pins_flags_malformed_revision() -> None:
    reg = RepoGroupRegistry()
    reg.define_group("bad", [build_member("repoX", "not a valid ref~^", access=ACCESS_READ_ONLY)])
    report = reg.verify_pins("bad")
    assert report.ok is False
    assert report.unpinned[0].kind == "unpinned"
    assert "malformed" in report.unpinned[0].reason


def test_classify_pin() -> None:
    assert classify_pin(_SHA) == "sha"
    assert classify_pin(_SHA2) == "sha"
    assert classify_pin("v2.0.0") == "tag"
    assert classify_pin("release-2024") == "tag"
    assert classify_pin("") == "unpinned"
    assert classify_pin("bad ref") == "unpinned"
    # a 39-char hex string is NOT a full sha -> treated as a tag, still pinned
    assert classify_pin("a" * 39) == "tag"


# -- persistence round-trip ---------------------------------------------------
def test_state_round_trips_via_json_store(tmp_path) -> None:
    store = tmp_path / "sub" / "repo_groups.json"
    reg = _registry_with_group(store_path=store)
    saved = reg.save()
    assert saved == store
    assert store.exists()

    # persisted as JSON with the expected shape
    payload = json.loads(store.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert [g["name"] for g in payload["groups"]] == ["core-stack"]

    # a fresh registry loads back identical definitions
    reloaded = RepoGroupRegistry(store_path=store).load()
    assert reloaded.group_names() == ("core-stack",)
    resolved = reloaded.resolve("core-stack")
    assert resolved.pins == {
        "https://example.com/org/app.git": _SHA,
        "https://example.com/org/lib.git": "v1.2.3",
    }
    # boundaries survive the round-trip
    assert reloaded.check_access("core-stack", "https://example.com/org/lib.git", MODE_WRITE).allowed is False
    assert reloaded.check_access("core-stack", "https://example.com/org/app.git", MODE_WRITE).allowed is True


def test_load_missing_file_is_empty_not_error(tmp_path) -> None:
    store = tmp_path / "absent.json"
    reg = RepoGroupRegistry(store_path=store).load()
    assert reg.group_names() == ()


def test_load_unparseable_file_raises(tmp_path) -> None:
    store = tmp_path / "broken.json"
    store.write_text("{ not json", encoding="utf-8")
    with pytest.raises(RepoGroupError):
        RepoGroupRegistry(store_path=store).load()


def test_from_env_uses_override(tmp_path, monkeypatch) -> None:
    store = tmp_path / "env_store.json"
    monkeypatch.setenv(STORE_PATH_ENV, str(store))
    reg = RepoGroupRegistry.from_env()
    reg.define_group("g", [build_member("r", _SHA, access=ACCESS_READ_ONLY)])
    reg.save()
    assert store.exists()
    reloaded = RepoGroupRegistry.from_env().load()
    assert reloaded.group_names() == ("g",)


def test_save_without_path_raises() -> None:
    reg = RepoGroupRegistry()
    reg.define_group("g", [build_member("r", _SHA)])
    with pytest.raises(RepoGroupError):
        reg.save()


# -- member/group validation --------------------------------------------------
def test_invalid_access_rejected() -> None:
    with pytest.raises(RepoGroupError):
        RepoMember(repo="r", revision=_SHA, access="admin")


def test_duplicate_member_rejected() -> None:
    reg = RepoGroupRegistry()
    with pytest.raises(RepoGroupError):
        reg.define_group(
            "dup",
            [build_member("repo.git", _SHA), build_member("repo", _SHA2)],
        )


def test_with_revision_helper() -> None:
    member = build_member("r", "", access=ACCESS_READ_WRITE)
    assert member.is_pinned is False
    pinned = with_revision(member, _SHA)
    assert pinned.is_pinned is True
    assert pinned.revision == _SHA
    assert pinned.access == ACCESS_READ_WRITE
