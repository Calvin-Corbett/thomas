"""CAP-080 L2: automation templates with integrated history + configured-channel
exception reports.

Every test drives an injected fake clock and injected channel sinks -- no real
processes, sleeps, or network -- so behaviour is deterministic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.tools.automation_templates import (
    CHANGE_CREATE,
    CHANGE_RESTORE,
    CHANGE_UPDATE,
    TEMPLATES_PATH_ENV,
    AutomationTemplateRegistry,
    ExceptionReport,
    _default_templates_path,
)


class FakeClock:
    """A controllable clock: ``now`` is read and advanced explicitly."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingSink:
    """A channel sink that records every report handed to it."""

    def __init__(self) -> None:
        self.received: list[ExceptionReport] = []

    def __call__(self, report: ExceptionReport) -> None:
        self.received.append(report)


# -- (1) integrated template history -------------------------------------------


def test_edit_history_records_each_version_and_prior_is_recoverable(tmp_path: Path) -> None:
    clock = FakeClock(start=100.0)
    reg = AutomationTemplateRegistry(clock=clock, store_path=tmp_path / "store.json")

    v1 = reg.create("nightly", {"cron": "0 2 * * *", "task": "sync"}, channel="email:ops")
    clock.advance(10.0)
    v2 = reg.update("nightly", {"cron": "0 3 * * *", "task": "sync"})
    clock.advance(10.0)
    reg.update("nightly", {"cron": "0 3 * * *", "task": "sync-v2"})

    # Every change is recorded, each with its own version number + change kind.
    hist = reg.history("nightly")
    assert [v.version for v in hist] == [1, 2, 3]
    assert [v.change for v in hist] == [CHANGE_CREATE, CHANGE_UPDATE, CHANGE_UPDATE]
    assert [v.at for v in hist] == [100.0, 110.0, 120.0]
    assert v1.version == 1 and v2.version == 2

    # A PRIOR version is recoverable, verbatim.
    recovered = reg.version("nightly", 1)
    assert recovered.definition == {"cron": "0 2 * * *", "task": "sync"}
    assert recovered.channel == "email:ops"
    # Current is unchanged by merely reading a prior version.
    assert reg.current("nightly").definition["task"] == "sync-v2"


def test_restore_promotes_prior_version_to_current(tmp_path: Path) -> None:
    clock = FakeClock()
    reg = AutomationTemplateRegistry(clock=clock, store_path=tmp_path / "store.json")

    reg.create("job", {"n": 1}, channel="slack:#a")
    reg.update("job", {"n": 2}, channel="slack:#b")

    restored = reg.restore("job", 1)  # recover v1's definition + channel

    assert restored.version == 3
    assert restored.change == CHANGE_RESTORE
    assert restored.definition == {"n": 1}
    assert restored.channel == "slack:#a"
    assert reg.current("job").definition == {"n": 1}
    # History is appended, never rewound.
    assert [v.version for v in reg.history("job")] == [1, 2, 3]


def test_update_carries_channel_forward_but_can_clear_it(tmp_path: Path) -> None:
    clock = FakeClock()
    reg = AutomationTemplateRegistry(clock=clock, store_path=tmp_path / "store.json")

    reg.create("job", {"n": 1}, channel="email:ops")
    # Omitting channel carries the configured channel forward.
    carried = reg.update("job", {"n": 2})
    assert carried.channel == "email:ops"
    # Passing None explicitly clears it.
    cleared = reg.update("job", {"n": 3}, channel=None)
    assert cleared.channel is None


# -- (2) configured-channel exception reports ----------------------------------


def _boom() -> None:
    raise ValueError("kaboom")


def test_exception_routes_to_configured_channel_only(tmp_path: Path) -> None:
    clock = FakeClock(start=42.0)
    reg = AutomationTemplateRegistry(clock=clock, store_path=tmp_path / "store.json")

    ops = RecordingSink()
    alerts = RecordingSink()
    reg.register_channel("email:ops", ops)
    reg.register_channel("slack:#alerts", alerts)

    reg.create("billing", {"task": "invoice"}, channel="email:ops")

    with pytest.raises(ValueError, match="kaboom"):
        reg.run("billing", _boom, context={"run_id": "r-1"})

    # Routed to the configured channel...
    assert len(ops.received) == 1
    report = ops.received[0]
    assert report.automation_id == "billing"
    assert report.version == 1
    assert report.channel == "email:ops"
    assert report.error_type == "ValueError"
    assert report.error_message == "kaboom"
    assert report.context == {"run_id": "r-1"}
    assert report.at == 42.0
    assert report.delivered is True
    # ...and NOT to any other configured channel.
    assert alerts.received == []


def test_no_configured_channel_report_retained_no_misroute(tmp_path: Path) -> None:
    clock = FakeClock()
    reg = AutomationTemplateRegistry(clock=clock, store_path=tmp_path / "store.json")

    ops = RecordingSink()
    reg.register_channel("email:ops", ops)

    reg.create("orphan", {"task": "x"})  # no configured channel

    with pytest.raises(ValueError):
        reg.run("orphan", _boom, context={"k": "v"})

    # No sink was invoked (no misroute)...
    assert ops.received == []
    # ...but the report is retained for inspection.
    retained = reg.retained_reports()
    assert len(retained) == 1
    assert retained[0].automation_id == "orphan"
    assert retained[0].channel is None
    assert retained[0].delivered is False
    assert retained[0].context == {"k": "v"}


def test_configured_channel_without_registered_sink_is_retained(tmp_path: Path) -> None:
    clock = FakeClock()
    reg = AutomationTemplateRegistry(clock=clock, store_path=tmp_path / "store.json")
    # Channel is configured on the template, but no sink is wired for it.
    reg.create("lonely", {"task": "x"}, channel="pager:oncall")

    with pytest.raises(ValueError):
        reg.run("lonely", _boom)

    retained = reg.retained_reports()
    assert len(retained) == 1
    assert retained[0].channel == "pager:oncall"
    assert retained[0].delivered is False


def test_successful_run_produces_no_report(tmp_path: Path) -> None:
    clock = FakeClock()
    reg = AutomationTemplateRegistry(clock=clock, store_path=tmp_path / "store.json")
    ops = RecordingSink()
    reg.register_channel("email:ops", ops)
    reg.create("ok", {"task": "x"}, channel="email:ops")

    assert reg.run("ok", lambda: 7) == 7
    assert ops.received == []
    assert reg.reports() == []


def test_report_carries_the_running_version(tmp_path: Path) -> None:
    clock = FakeClock()
    reg = AutomationTemplateRegistry(clock=clock, store_path=tmp_path / "store.json")
    ops = RecordingSink()
    reg.register_channel("email:ops", ops)

    reg.create("evolving", {"v": 1}, channel="email:ops")
    reg.update("evolving", {"v": 2})  # now at version 2

    with pytest.raises(ValueError):
        reg.run("evolving", _boom)

    assert ops.received[0].version == 2


# -- (3) durable round-trip ----------------------------------------------------


def test_history_and_templates_round_trip(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    clock = FakeClock(start=1.0)

    reg = AutomationTemplateRegistry(clock=clock, store_path=store)
    reg.create("a", {"n": 1}, channel="email:ops")
    clock.advance(5.0)
    reg.update("a", {"n": 2}, channel="slack:#alerts")
    reg.create("b", {"kind": "b"})
    # Generate a retained report so reports round-trip too.
    with pytest.raises(ValueError):
        reg.run("b", _boom, context={"c": 1})

    before_a = reg.history("a")
    before_reports = reg.reports()

    # Simulate a full process restart: brand-new instance, same store path.
    reg2 = AutomationTemplateRegistry(clock=FakeClock(start=999.0), store_path=store)

    assert reg2.template_ids() == ["a", "b"]
    after_a = reg2.history("a")
    assert after_a == before_a  # versions round-tripped exactly
    assert reg2.current("a").definition == {"n": 2}
    assert reg2.current("a").channel == "slack:#alerts"
    # A prior version is still recoverable after reload.
    assert reg2.version("a", 1).definition == {"n": 1}
    assert reg2.version("a", 1).channel == "email:ops"
    # Reports round-tripped too.
    assert reg2.reports() == before_reports
    assert reg2.retained_reports()[0].context == {"c": 1}

    # And it keeps accumulating from the reloaded baseline.
    reg2.update("a", {"n": 3})
    assert [v.version for v in reg2.history("a")] == [1, 2, 3]


def test_store_path_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "env" / "templates.json"
    monkeypatch.setenv(TEMPLATES_PATH_ENV, str(target))
    assert _default_templates_path() == target

    reg = AutomationTemplateRegistry(clock=FakeClock())  # no explicit path -> uses env
    reg.create("x", {"n": 1}, channel="email:ops")
    assert target.exists()


def test_determinism_via_injected_clock(tmp_path: Path) -> None:
    def run(tag: str) -> list[float]:
        clock = FakeClock(start=0.0)
        reg = AutomationTemplateRegistry(clock=clock, store_path=tmp_path / f"store-{tag}.json")
        reg.create("d", {"n": 1}, channel="email:ops")
        clock.advance(3.0)
        reg.update("d", {"n": 2})
        clock.advance(4.0)
        reg.restore("d", 1)
        return [v.at for v in reg.history("d")]

    assert run("a") == run("b")
    assert run("c") == [0.0, 3.0, 7.0]


# -- error handling ------------------------------------------------------------


def test_create_duplicate_raises(tmp_path: Path) -> None:
    reg = AutomationTemplateRegistry(clock=FakeClock(), store_path=tmp_path / "store.json")
    reg.create("dup", {"n": 1})
    with pytest.raises(ValueError):
        reg.create("dup", {"n": 2})


def test_operations_on_unknown_template_raise(tmp_path: Path) -> None:
    reg = AutomationTemplateRegistry(clock=FakeClock(), store_path=tmp_path / "store.json")
    with pytest.raises(KeyError):
        reg.update("nope", {"n": 1})
    with pytest.raises(KeyError):
        reg.history("nope")
    with pytest.raises(KeyError):
        reg.run("nope", lambda: None)


def test_out_of_range_version_raises(tmp_path: Path) -> None:
    reg = AutomationTemplateRegistry(clock=FakeClock(), store_path=tmp_path / "store.json")
    reg.create("t", {"n": 1})
    with pytest.raises(IndexError):
        reg.version("t", 2)
    with pytest.raises(IndexError):
        reg.version("t", 0)
