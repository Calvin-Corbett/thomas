"""A host describes its setup as a diff, not a fork.

Phase 3.2 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md). Thomas configures a
run by passing a different subset of twenty-three constructor arguments at each
call site, so no setup has a name and no two can be compared. A profile names an
ordered composition and every operation on it returns a new one, which makes the
difference between two hosts a thing you can print.
"""

from __future__ import annotations

import pytest

from thomas.core.kernel import Kernel
from thomas.core.kernel.profiles import Entry, Profile, ProfileError, apply_profile


class Provider:
    """Mounts a service whose value says who provided it."""

    inject: tuple[str, ...] = ()

    def __init__(self, service: str, value: str) -> None:
        self.name = f"provider:{service}:{value}"
        self.service = service
        self.value = value

    def apply(self, ctx, config) -> None:
        ctx.set(self.service, config.get("value", self.value))


BASE = Profile(
    name="base",
    entries=(
        Entry("tools", Provider("tools", "real-tools")),
        Entry("llm", Provider("llm", "real-llm")),
    ),
)


# ---------------------------------------------------------------------------
# composition is immutable and inspectable
# ---------------------------------------------------------------------------


def test_a_profile_lists_its_entries_in_order() -> None:
    assert BASE.ids == ("tools", "llm")


def test_extending_leaves_the_original_untouched() -> None:
    web = BASE.extend("web", [Entry("ui", Provider("ui", "browser"))])
    assert web.ids == ("tools", "llm", "ui")
    assert BASE.ids == ("tools", "llm")


def test_patching_replaces_a_row_in_place() -> None:
    fake = BASE.patch("llm", plugin=Provider("llm", "fake-llm"), name="test")
    assert fake.ids == ("tools", "llm")
    assert fake.name == "test"
    assert BASE.entries[1].plugin.value == "real-llm"


def test_patching_config_alone_keeps_the_plugin() -> None:
    tuned = BASE.patch("tools", config={"value": "tuned"})
    assert tuned.entries[0].plugin is BASE.entries[0].plugin
    assert tuned.entries[0].config == {"value": "tuned"}


def test_dropping_a_row_removes_only_that_row() -> None:
    headless = BASE.without("llm", name="headless")
    assert headless.ids == ("tools",)
    assert BASE.ids == ("tools", "llm")


def test_inserting_places_a_row_where_asked() -> None:
    with_audit = BASE.insert_after("tools", Entry("audit", Provider("audit", "on")))
    assert with_audit.ids == ("tools", "audit", "llm")


def test_targeting_a_row_that_is_not_there_is_an_error_not_a_no_op() -> None:
    """A typo in a patch must be loud; a silent miss is how a layer goes missing."""
    with pytest.raises(ProfileError):
        BASE.patch("lmm", plugin=Provider("llm", "typo"))
    with pytest.raises(ProfileError):
        BASE.without("nope")


def test_duplicate_ids_are_refused_at_construction() -> None:
    with pytest.raises(ProfileError):
        Profile(
            name="broken",
            entries=(
                Entry("tools", Provider("tools", "a")),
                Entry("tools", Provider("tools", "b")),
            ),
        )


# ---------------------------------------------------------------------------
# applying and unwinding
# ---------------------------------------------------------------------------


def test_applying_a_profile_mounts_every_entry() -> None:
    kernel = Kernel()
    mounted = apply_profile(kernel, BASE)
    assert kernel.root["tools"] == "real-tools"
    assert kernel.root["llm"] == "real-llm"
    assert len(mounted.forks) == 2


def test_a_later_entry_overrides_an_earlier_one_and_unwinds_cleanly() -> None:
    """Order is the override mechanism, and it has to be reversible."""
    kernel = Kernel()
    overridden = BASE.extend("override", [Entry("llm-fake", Provider("llm", "fake-llm"))])

    mounted = apply_profile(kernel, overridden)
    assert kernel.root["llm"] == "fake-llm"

    mounted.forks[-1].dispose()
    assert kernel.root["llm"] == "real-llm"


def test_disposing_a_profile_removes_everything_it_mounted() -> None:
    kernel = Kernel()
    mounted = apply_profile(kernel, BASE)
    mounted.dispose()
    assert not kernel.root.has("tools")
    assert not kernel.root.has("llm")
    assert kernel.mounted() == []


def test_an_entry_waiting_on_a_missing_service_is_reported_not_hidden() -> None:
    kernel = Kernel()

    class NeedsSessions:
        name = "transcript"
        inject = ("sessions",)

        def apply(self, ctx, config) -> None:  # pragma: no cover - never reached
            raise AssertionError("must not apply without its seam")

    profile = BASE.extend("with-transcript", [Entry("transcript", NeedsSessions())])
    mounted = apply_profile(kernel, profile)

    assert [fork.name for fork in mounted.pending] == ["transcript"]
    assert mounted.pending[0].missing == ("sessions",)


def test_a_failing_entry_unwinds_the_whole_profile() -> None:
    """Half a profile is worse than none: the host would run misconfigured."""
    kernel = Kernel()

    def bad(ctx, config) -> None:
        raise RuntimeError("entry blew up")

    profile = BASE.extend("broken", [Entry("bad", bad)])

    with pytest.raises(RuntimeError):
        apply_profile(kernel, profile)

    assert not kernel.root.has("tools")
    assert not kernel.root.has("llm")
    assert kernel.mounted() == []
