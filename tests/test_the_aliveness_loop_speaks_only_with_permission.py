"""The aliveness loop speaks only with permission, through the speak gate.

Permission levels are what make the drives load-bearing; the gate decides
whether a candidate message is spoken, briefed or logged. Split from
test_the_aliveness_loop_records_instead_of_speaking.py on 2026-09-07 so each
file stays under the monolith guard's limit.
"""
from __future__ import annotations

import time

from tests._aliveness_fakes import FakeSensor, isolated_gate, obs
from thomas.core.aliveness import (
    AlivenessLoop,
)
from thomas.core.aliveness_drives import Drives
from thomas.core.aliveness_gate import PushBudget
from thomas.core.aliveness_log import (
    MuteLog,
)
from thomas.core.aliveness_permissions import (
    BRIEF_ALWAYS,
    BRIEF_IF_ROOM,
    INTERRUPT,
    NOTIFY,
    SILENT,
    PermissionStore,
)
from thomas.core.aliveness_world import WorldModel

# ---------------------------------------------------------------------------
# Permission — the thing that makes the drives load-bearing
# ---------------------------------------------------------------------------


def test_permission_starts_at_zero_for_everything(tmp_path) -> None:
    store = PermissionStore(tmp_path / "p.json")

    assert store.level_for("ci.status") == SILENT
    assert store.grants() == []


def test_a_grant_survives_a_restart(tmp_path) -> None:
    path = tmp_path / "p.json"
    PermissionStore(path).grant("ci.status", NOTIFY, note="you said so")

    reopened = PermissionStore(path)

    assert reopened.level_for("ci.status") == NOTIFY
    assert reopened.grants()[0].note == "you said so"


def test_a_subtopic_inherits_weakly_and_never_the_full_ceiling(tmp_path) -> None:
    """Caring about ci.status should cover ci.status.nightly — quietly."""
    store = PermissionStore(tmp_path / "p.json")
    store.grant("ci.status", INTERRUPT)

    assert store.level_for("ci.status") == INTERRUPT
    assert store.level_for("ci.status.nightly") == INTERRUPT - 1
    assert store.level_for("unrelated.topic") == SILENT


def test_a_weak_grant_is_not_inherited_at_all(tmp_path) -> None:
    store = PermissionStore(tmp_path / "p.json")
    store.grant("ci.status", BRIEF_IF_ROOM)

    assert store.level_for("ci.status.nightly") == SILENT


def test_evidence_raises_a_proposal_not_a_grant(tmp_path) -> None:
    """Earned permission has to ask. That is what keeps it inspectable."""
    store = PermissionStore(tmp_path / "p.json")

    proposal = store.maybe_propose("deploy.status", samples=6, hit_rate=0.83)

    assert proposal is not None
    assert store.level_for("deploy.status") == SILENT  # still silent!
    assert "Want me to" in proposal.question()

    store.accept("deploy.status")
    assert store.level_for("deploy.status") == NOTIFY


def test_thin_or_unconvincing_evidence_proposes_nothing(tmp_path) -> None:
    store = PermissionStore(tmp_path / "p.json")

    assert store.maybe_propose("a.topic", samples=2, hit_rate=1.0) is None
    assert store.maybe_propose("b.topic", samples=20, hit_rate=0.1) is None


def test_the_same_question_is_not_asked_twice(tmp_path) -> None:
    store = PermissionStore(tmp_path / "p.json")
    assert store.maybe_propose("deploy.status", 6, 0.83) is not None
    assert store.maybe_propose("deploy.status", 9, 0.90) is None

    store.decline("deploy.status")
    assert store.proposals() == []


def test_a_grant_nobody_acts_on_decays(tmp_path) -> None:
    from thomas.core.aliveness_permissions import DECAY_AFTER_S

    store = PermissionStore(tmp_path / "p.json")
    store.grant("stale.project", NOTIFY)

    changed = store.decay(now=time.time() + DECAY_AFTER_S + 1)

    assert changed == [("stale.project", NOTIFY, NOTIFY - 1)]
    assert store.level_for("stale.project") == NOTIFY - 1


def test_acting_on_a_topic_keeps_it_fresh(tmp_path) -> None:
    from thomas.core.aliveness_permissions import DECAY_AFTER_S

    store = PermissionStore(tmp_path / "p.json")
    store.grant("live.project", NOTIFY)
    store.record_outcome("live.project", "acted")

    assert store.decay(now=time.time() + DECAY_AFTER_S - 60) == []


def test_the_loop_can_always_ask_for_permission(tmp_path) -> None:
    """Without a seed the design deadlocks: zero permission for everything
    includes the topic used to ask for permission."""
    store = PermissionStore(tmp_path / "p.json")
    store.ensure_seed()

    assert store.level_for(store.SYSTEM_TOPIC) == BRIEF_ALWAYS
    assert store.level_for("anything.else") == SILENT


# ---------------------------------------------------------------------------
# The speak gate
# ---------------------------------------------------------------------------


def hot_drives(debt: bool = True, freshness: bool = True, contact: bool = False) -> Drives:
    drives = Drives()
    drives.debt.set_level(1.0 if debt else 0.0)
    drives.freshness.set_level(1.0 if freshness else 0.0)
    drives.contact.set_level(1.0 if contact else 0.0)
    return drives


def test_without_permission_nothing_gets_through(tmp_path) -> None:
    gate = isolated_gate(tmp_path)

    decision = gate.decide("ci.status", "ci went red", hot_drives(), ["evidence"], idle_seconds=10_000)

    assert decision.deliver is False
    assert decision.reason == "no permission for this topic"


def test_a_brief_entry_costs_no_budget(tmp_path) -> None:
    """Pull is free. That is the whole reason the brief is the default."""
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("ci.status", BRIEF_ALWAYS)
    before = gate.budget.balance

    decision = gate.decide("ci.status", "ci went red", hot_drives(), ["e"], idle_seconds=10_000)

    assert decision.deliver is True
    assert decision.channel == "brief"
    assert gate.budget.balance == before


def test_silence_alone_can_never_produce_a_message(tmp_path) -> None:
    """Contact supports; it never causes.

    With nothing granted there is nothing for it to lift, however lonely it is.
    """
    gate = isolated_gate(tmp_path)
    only_lonely = hot_drives(debt=False, freshness=False, contact=True)

    decision = gate.decide("nothing.granted", "it has been a while", only_lonely, ["e"], idle_seconds=10_000)

    assert decision.deliver is False
    assert decision.asked_level == SILENT


def test_a_calm_day_settles_for_the_quiet_end_of_a_ceiling(tmp_path) -> None:
    """The drives hold a grant back; they do not build one up."""
    gate = isolated_gate(tmp_path)
    calm = Drives()

    assert gate.asked_level(calm, NOTIFY) == NOTIFY - 1
    assert gate.asked_level(hot_drives(), NOTIFY) == NOTIFY
    # Contact spares it the calm-day downgrade, and can do nothing more.
    lonely = hot_drives(debt=False, freshness=False, contact=True)
    assert gate.asked_level(lonely, NOTIFY) == NOTIFY
    assert gate.asked_level(lonely, SILENT) == SILENT


def test_a_grant_is_never_exceeded_however_hot_the_drives(tmp_path) -> None:
    gate = isolated_gate(tmp_path)

    assert gate.asked_level(hot_drives(contact=True), BRIEF_IF_ROOM) == BRIEF_IF_ROOM
    assert gate.asked_level(hot_drives(contact=True), BRIEF_ALWAYS) == BRIEF_ALWAYS


def test_a_push_is_held_while_you_are_mid_something(tmp_path) -> None:
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("ci.status", NOTIFY)

    decision = gate.decide("ci.status", "ci went red", hot_drives(), ["e"], idle_seconds=5)

    assert decision.deliver is False
    assert decision.reason == "you are mid-something"


def test_an_interrupt_grant_crosses_that_line(tmp_path) -> None:
    """Level 5 is the point of doing this per topic."""
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("prod.down", INTERRUPT)

    decision = gate.decide("prod.down", "prod is down", hot_drives(contact=True), ["e"], idle_seconds=1)

    assert decision.deliver is True
    assert decision.channel == "push"
    assert decision.level == INTERRUPT


def test_the_same_thing_is_not_said_twice(tmp_path) -> None:
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("ci.status", BRIEF_ALWAYS)

    first = gate.decide("ci.status", "ci went red", hot_drives(), ["e"], idle_seconds=10_000)
    second = gate.decide("ci.status", "ci went red", hot_drives(), ["e"], idle_seconds=10_000)

    assert first.deliver is True
    assert second.deliver is False
    assert second.reason == "already said this recently"


def test_nothing_to_say_is_never_said(tmp_path) -> None:
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("ci.status", INTERRUPT)

    decision = gate.decide("ci.status", "   ", hot_drives(), [], idle_seconds=10_000)

    assert decision.deliver is False
    assert decision.reason == "nothing to say"


def test_the_push_budget_binds_and_says_so(tmp_path, caplog) -> None:
    gate = isolated_gate(tmp_path, budget=PushBudget(daily=1.0, balance=1.0))
    gate.permissions.grant("a.topic", NOTIFY)
    gate.permissions.grant("b.topic", NOTIFY)

    first = gate.decide("a.topic", "one", hot_drives(), ["e"], idle_seconds=10_000)
    with caplog.at_level("INFO"):
        second = gate.decide("b.topic", "two", hot_drives(), ["e"], idle_seconds=10_000)

    assert first.deliver is True
    assert second.deliver is False
    assert second.reason == "push budget spent for today"
    assert "too many grants" in caplog.text.lower()


def test_a_message_you_act_on_is_refunded(tmp_path) -> None:
    """Closed loop: what works costs nothing, what is ignored drains extra."""
    gate = isolated_gate(tmp_path, budget=PushBudget(daily=1.0, balance=1.0))
    gate.permissions.grant("ci.status", NOTIFY)
    gate.decide("ci.status", "ci went red", hot_drives(), ["e"], idle_seconds=10_000)
    spent = gate.budget.balance

    gate.record_outcome("ci.status", "acted", channel="push")

    assert gate.budget.balance > spent


def test_being_told_to_stop_puts_the_budget_in_debt(tmp_path) -> None:
    """Not just empty — in debt, so it takes days of daily top-up to recover.
    That debt is the auto-mute period."""
    gate = isolated_gate(tmp_path, budget=PushBudget(daily=1.0, balance=3.0))

    gate.record_outcome("ci.status", "stopped", channel="push")

    assert gate.budget.balance < 0
    assert gate.budget.can_spend() is False


def test_a_drained_budget_does_not_come_back_full_tomorrow(tmp_path) -> None:
    """Resetting daily would erase the closed loop entirely."""
    budget = PushBudget(daily=1.0, balance=-3.0, day="2026-08-01")

    budget._roll(time.time())

    assert budget.balance == -2.0
    assert budget.can_spend() is False


def test_a_granted_topic_actually_gets_delivered_by_the_loop(tmp_path) -> None:
    """End to end: grant, change the world, watch it come out of the gate."""
    sensor = FakeSensor([obs("dev", "green", topic="ci.status")])
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("ci.status", BRIEF_ALWAYS)
    loop = AlivenessLoop(
        world=WorldModel([sensor]),
        drives=Drives(),
        mute_log=MuteLog(tmp_path / "mute.jsonl"),
        gate=gate,
    )
    loop.tick(idle_seconds=10_000)

    sensor.readings = [obs("dev", "red", topic="ci.status")]
    summary = loop.tick(idle_seconds=10_000)

    assert summary["delivered"] == 1
    # The drives are quiet, so it settled for the quiet end of its ceiling
    # rather than all of it. That is the drives doing work.
    assert loop.sink.delivered == [("ci.status", "brief", BRIEF_IF_ROOM)]

    entry = [c for c in loop.mute_log.entries() if c.topic == "ci.status"][-1]
    assert entry.channel == "brief"
    loop.record_outcome(entry.id, entry.topic, "acted")
    assert [c.outcome for c in loop.mute_log.entries() if c.id == entry.id] == ["acted"]


def test_a_held_message_never_costs_the_push_budget(tmp_path) -> None:
    """It was never sent. A fortnight of ignored held candidates drove the
    balance to its floor, which would have silently disabled every push."""
    gate = isolated_gate(tmp_path, budget=PushBudget(daily=1.0, balance=1.0))
    before = gate.budget.balance

    for _ in range(50):
        gate.record_outcome("ungranted.topic", "ignored", channel="held")

    assert gate.budget.balance == before
    assert gate.budget.can_spend() is True


def test_an_ignored_brief_entry_costs_nothing_either(tmp_path) -> None:
    """Pull costs no attention, so ignoring it cannot cost budget."""
    gate = isolated_gate(tmp_path, budget=PushBudget(daily=1.0, balance=1.0))
    before = gate.budget.balance

    gate.record_outcome("ci.status", "ignored", channel="brief")

    assert gate.budget.balance == before


def test_a_notify_grant_actually_reaches_notify(tmp_path) -> None:
    """A granted ceiling above 'brief' has to be reachable, or the escalation
    levels are decoration."""
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("ci.status", NOTIFY)

    decision = gate.decide("ci.status", "ci went red", hot_drives(), ["e"], idle_seconds=10_000)

    assert decision.deliver is True
    assert decision.channel == "push"
    assert decision.level == NOTIFY
