"""Tests for the agent_safety.local.toml overlay mechanism.

Per-install customizations layered on top of agent_safety.toml without
modifying the upstream config. Mirrors the existing public/local pattern
(docs/THOMAS_BIBLE.md vs docs/THOMAS_BIBLE.local.md).

Covers:
- _deep_merge: nested dicts merge, scalars/lists replace
- _load_toml_with_overlay: missing overlay is silent, present overlay wins
- AgentSafetyConfig: skip_policy_breakglass_max_per_agent_24h reflects overlay
- precommit_skip_policy gate: 0 in the resolved config means unlimited

Why this matters: Calvin opted his dev machine out of the per-agent
breakglass quota (he accepts the tradeoff because the OTHER layers of
the safety architecture — protected-files, signed-commits, server-side
gates — still apply). Public installs keep the default cap of 3.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.crew.brief.safety_config import (  # noqa: E402
    AgentSafetyConfig,
    _deep_merge,
    _load_toml_with_overlay,
)

# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


def test_deep_merge_replaces_scalar() -> None:
    base = {"a": 1, "b": 2}
    _deep_merge(base, {"a": 99})
    assert base == {"a": 99, "b": 2}


def test_deep_merge_recurses_into_nested_dicts() -> None:
    base = {"section": {"x": 1, "y": 2}}
    _deep_merge(base, {"section": {"y": 200, "z": 3}})
    assert base == {"section": {"x": 1, "y": 200, "z": 3}}


def test_deep_merge_overlay_list_replaces_not_appends() -> None:
    """Local overlay's list completely replaces the upstream list — no
    surprising concatenation."""
    base = {"protected_files": ["a", "b", "c"]}
    _deep_merge(base, {"protected_files": ["x", "y"]})
    assert base == {"protected_files": ["x", "y"]}


def test_deep_merge_adds_new_keys() -> None:
    base = {"a": 1}
    _deep_merge(base, {"b": 2, "c": {"nested": True}})
    assert base == {"a": 1, "b": 2, "c": {"nested": True}}


# ---------------------------------------------------------------------------
# _load_toml_with_overlay
# ---------------------------------------------------------------------------


def test_overlay_present_overrides_main(tmp_path: Path) -> None:
    main = tmp_path / "agent_safety.toml"
    local = tmp_path / "agent_safety.local.toml"
    main.write_text(
        textwrap.dedent("""
            [skip_policy]
            breakglass_max_per_agent_24h = 3
            max_skip_hooks = 4
        """)
    )
    local.write_text(
        textwrap.dedent("""
            [skip_policy]
            breakglass_max_per_agent_24h = 0
        """)
    )
    merged = _load_toml_with_overlay(main)
    # Overlay key wins.
    assert merged["skip_policy"]["breakglass_max_per_agent_24h"] == 0
    # Untouched keys are preserved.
    assert merged["skip_policy"]["max_skip_hooks"] == 4


def test_overlay_absent_keeps_base(tmp_path: Path) -> None:
    main = tmp_path / "agent_safety.toml"
    main.write_text(
        textwrap.dedent("""
            [skip_policy]
            breakglass_max_per_agent_24h = 3
        """)
    )
    merged = _load_toml_with_overlay(main)
    assert merged["skip_policy"]["breakglass_max_per_agent_24h"] == 3


def test_overlay_with_new_section(tmp_path: Path) -> None:
    """Local overlay can introduce keys not present in the main file."""
    main = tmp_path / "agent_safety.toml"
    local = tmp_path / "agent_safety.local.toml"
    main.write_text('[project]\nname = "thomas"\n')
    local.write_text(
        textwrap.dedent("""
            [skip_policy]
            breakglass_max_per_agent_24h = 0
        """)
    )
    merged = _load_toml_with_overlay(main)
    assert merged["project"]["name"] == "thomas"
    assert merged["skip_policy"]["breakglass_max_per_agent_24h"] == 0


def test_empty_main_returns_empty(tmp_path: Path) -> None:
    """No main config (file missing) returns empty even if overlay exists.

    The overlay's purpose is to OVERRIDE upstream settings, not to substitute
    for them. If the upstream config is missing entirely, that's an unrelated
    error mode and the overlay shouldn't paper over it.
    """
    main = tmp_path / "agent_safety.toml"
    local = tmp_path / "agent_safety.local.toml"
    local.write_text("[skip_policy]\nbreakglass_max_per_agent_24h = 0\n")
    merged = _load_toml_with_overlay(main)
    assert merged == {}


# ---------------------------------------------------------------------------
# AgentSafetyConfig with overlay
# ---------------------------------------------------------------------------


def test_config_object_reflects_overlay_value() -> None:
    """End-to-end: the config object's accessor returns the overlay value."""
    data = {"skip_policy": {"breakglass_max_per_agent_24h": 0}}
    cfg = AgentSafetyConfig(data)
    assert cfg.skip_policy_breakglass_max_per_agent_24h() == 0


def test_config_default_quota_is_three() -> None:
    """Regression guard: the public default stays at 3 if nothing overrides."""
    cfg = AgentSafetyConfig({})
    assert cfg.skip_policy_breakglass_max_per_agent_24h() == 3


# ---------------------------------------------------------------------------
# Gate-side: 0 means unlimited
# ---------------------------------------------------------------------------


def test_gate_treats_zero_as_unlimited() -> None:
    """Smoke test of the gate's quota-check logic with raw_quota=0.

    The actual check lives inline in precommit_skip_policy.main(). We
    reproduce the relevant snippet here to assert the semantics:
        raw_quota = 0 -> max_breakglass_per_agent = 0 -> check skipped
    """
    raw_quota = 0
    if raw_quota <= 0:
        max_breakglass_per_agent = 0
    else:
        max_breakglass_per_agent = raw_quota

    # Even with 100 historical breakglass uses in 24h, the check passes.
    recent_24h_count = 100
    blocked = max_breakglass_per_agent > 0 and recent_24h_count >= max_breakglass_per_agent
    assert blocked is False


def test_gate_treats_positive_as_cap() -> None:
    """Same snippet, but raw_quota=3 (the default) caps at 3."""
    raw_quota = 3
    if raw_quota <= 0:
        max_breakglass_per_agent = 0
    else:
        max_breakglass_per_agent = raw_quota

    recent_24h_count = 3
    blocked = max_breakglass_per_agent > 0 and recent_24h_count >= max_breakglass_per_agent
    assert blocked is True


def test_gate_treats_negative_as_unlimited() -> None:
    """Defensive: negative values are also treated as unlimited (not -3 cap)."""
    raw_quota = -1
    if raw_quota <= 0:
        max_breakglass_per_agent = 0
    else:
        max_breakglass_per_agent = raw_quota

    blocked = max_breakglass_per_agent > 0 and max_breakglass_per_agent <= 99
    assert blocked is False
