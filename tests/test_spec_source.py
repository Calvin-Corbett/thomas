"""CAP-122 acceptance tests: spec-as-source-of-truth rebuilds.

Proves the exact acceptance line -- "Promote prompts into a maintained app spec
with deterministic regeneration and behavioral diff":

1. prompts promote into a versioned spec;
2. regenerate is deterministic (same spec twice -> byte-identical);
3. a spec change produces a behavioral diff naming the changed capability;
4. an unchanged spec yields an empty behavioral diff;
5. the spec round-trips.

Everything is hermetic: pure in-memory values, an injected deterministic
generator, no network / model / filesystem.
"""

from __future__ import annotations

import pytest

from thomas.tools.spec_source import (
    AppSpec,
    Capability,
    SpecError,
    behavioral_diff,
    default_generator,
    promote,
    regenerate,
)

# ---------------------------------------------------------------------------
# 1. Promotion into a versioned spec
# ---------------------------------------------------------------------------


def test_prompts_promote_into_versioned_spec():
    prompts = [
        "export: produce a PDF report",
        "login: authenticate a user by email",
        {"name": "search", "summary": "full text search", "inputs": ["query"], "outputs": ["hits"]},
    ]
    spec = promote(prompts, name="reporting-app", version=1)

    assert isinstance(spec, AppSpec)
    assert spec.name == "reporting-app"
    assert spec.version == 1  # versioned
    # Every prompt became a stably-named capability.
    assert spec.capability_names() == ("export", "login", "search")
    caps = spec.capability_map()
    assert caps["export"].summary == "produce a PDF report"
    assert caps["search"].inputs == ("query",)
    assert caps["search"].outputs == ("hits",)


def test_promote_is_order_independent_over_a_set():
    # A set has no defined iteration order; promotion must still be deterministic.
    prompts_a = ["alpha: does A", "beta: does B", "gamma: does C"]
    spec_from_list = promote(prompts_a, name="app")
    spec_from_set = promote(set(prompts_a), name="app")
    assert spec_from_list == spec_from_set
    assert spec_from_list.fingerprint() == spec_from_set.fingerprint()


def test_promote_rejects_duplicate_capability_names():
    with pytest.raises(SpecError):
        promote(["dup: first", "dup: second"], name="app")


def test_promote_rejects_empty_prompt_set():
    with pytest.raises(SpecError):
        promote([], name="app")


def test_bump_produces_maintained_successor_version():
    spec = promote(["export: pdf"], name="app", version=3)
    caps = list(spec.capabilities) + [Capability(name="import", summary="csv")]
    successor = spec.bump(capabilities=caps)
    assert successor.version == 4
    assert successor.capability_names() == ("export", "import")
    # Original is untouched (immutable source of truth revisions).
    assert spec.version == 3
    assert spec.capability_names() == ("export",)


# ---------------------------------------------------------------------------
# 2. Deterministic regeneration
# ---------------------------------------------------------------------------


def test_regenerate_default_generator_is_deterministic():
    spec = promote(["export: pdf", "login: auth"], name="app")
    first = regenerate(spec)
    second = regenerate(spec)
    assert isinstance(first, bytes)
    assert first == second  # byte-identical for the same spec


def test_regenerate_injected_generator_is_deterministic():
    # An injectable deterministic generator: pure function of the spec.
    def generator(spec: AppSpec) -> bytes:
        body = "|".join(f"{c.name}={c.summary}" for c in spec.capabilities)
        return f"{spec.name}@{spec.version}::{body}".encode()

    spec = promote(["a: does a", "b: does b"], name="app", version=2)
    out1 = regenerate(spec, generator)
    out2 = regenerate(spec, generator)
    assert out1 == out2
    assert out1 == b"app@2::a=does a|b=does b"


def test_regenerate_equal_specs_yield_identical_bytes():
    # Two independently-promoted-but-equal specs regenerate identically.
    spec1 = promote(["x: one", "y: two"], name="app")
    spec2 = promote(set(["y: two", "x: one"]), name="app")
    assert regenerate(spec1) == regenerate(spec2)


def test_regenerate_string_generator_is_encoded():
    def generator(spec: AppSpec) -> str:
        return default_generator(spec)

    spec = promote(["x: one"], name="app")
    assert regenerate(spec, generator) == regenerate(spec)


def test_regenerate_rejects_bad_generator_return():
    def generator(spec: AppSpec):
        return 12345

    spec = promote(["x: one"], name="app")
    with pytest.raises(SpecError):
        regenerate(spec, generator)


# ---------------------------------------------------------------------------
# 3. Behavioral diff names the changed capability
# ---------------------------------------------------------------------------


def test_spec_change_produces_behavioral_diff_naming_changed_capability():
    old = promote(
        ["export: produce a PDF report", "login: authenticate a user"],
        name="app",
    )
    # Same capability names, but 'export' now behaves differently (CSV, not PDF).
    new = promote(
        ["export: produce a CSV report", "login: authenticate a user"],
        name="app",
    )

    diff = behavioral_diff(old, new)

    assert not diff.is_empty
    assert diff.added == ()
    assert diff.removed == ()
    # The behavioral diff names the changed capability specifically.
    assert diff.changed_names == ("export",)
    change = diff.changed[0]
    assert change.name == "export"
    assert change.old.summary == "produce a PDF report"
    assert change.new.summary == "produce a CSV report"
    assert diff.artifact_changed is True
    assert "export" in diff.summary()


def test_behavioral_diff_reports_added_and_removed_capabilities():
    old = promote(["a: does a", "b: does b"], name="app")
    new = promote(["a: does a", "c: does c"], name="app")

    diff = behavioral_diff(old, new)
    assert diff.added == ("c",)
    assert diff.removed == ("b",)
    assert diff.changed_names == ()
    assert not diff.is_empty


def test_behavioral_diff_uses_injected_generator():
    calls: list[str] = []

    def generator(spec: AppSpec) -> bytes:
        calls.append(spec.name)
        return regenerate(spec)

    old = promote(["a: does a"], name="app")
    new = promote(["a: does a different way"], name="app")
    diff = behavioral_diff(old, new, generator)
    assert diff.changed_names == ("a",)
    # Both artifacts were regenerated through the injected generator.
    assert calls == ["app", "app"]


def test_behavioral_diff_ignores_pure_metadata_edits():
    # Reworded app metadata is a text change but not a behavioral change.
    old = promote(["a: does a"], name="app", metadata={"owner": "alice"})
    new = promote(["a: does a"], name="app", metadata={"owner": "bob"})
    diff = behavioral_diff(old, new)
    assert diff.is_empty  # no capability behavior changed
    assert diff.artifact_changed is True  # but the rendered text did change


# ---------------------------------------------------------------------------
# 4. Unchanged spec -> empty behavioral diff
# ---------------------------------------------------------------------------


def test_unchanged_spec_yields_empty_behavioral_diff():
    spec = promote(["export: pdf", "login: auth"], name="app")
    diff = behavioral_diff(spec, spec)
    assert diff.is_empty
    assert diff.added == ()
    assert diff.removed == ()
    assert diff.changed == ()
    assert diff.artifact_changed is False
    assert diff.summary() == "no behavioral change"


def test_equal_but_distinct_specs_yield_empty_behavioral_diff():
    old = promote(["a: one", "b: two"], name="app")
    new = promote(set(["b: two", "a: one"]), name="app")
    assert old is not new
    diff = behavioral_diff(old, new)
    assert diff.is_empty


# ---------------------------------------------------------------------------
# 5. Spec round-trips
# ---------------------------------------------------------------------------


def test_spec_round_trips_through_dict():
    spec = promote(
        [
            {"name": "search", "summary": "fts", "inputs": ["q"], "outputs": ["hits"], "effects": ["log"]},
            "export: pdf",
        ],
        name="app",
        version=5,
        metadata={"owner": "team"},
    )
    restored = AppSpec.from_dict(spec.to_dict())
    assert restored == spec
    assert restored.fingerprint() == spec.fingerprint()


def test_spec_round_trips_through_json():
    spec = promote(["a: one", "b: two"], name="app", version=2)
    restored = AppSpec.from_json(spec.to_json())
    assert restored == spec
    # Round-tripping preserves deterministic regeneration.
    assert regenerate(restored) == regenerate(spec)


def test_canonical_bytes_are_stable_and_order_independent():
    spec1 = promote(["a: one", "b: two"], name="app")
    spec2 = promote(set(["b: two", "a: one"]), name="app")
    assert spec1.canonical_bytes() == spec2.canonical_bytes()
