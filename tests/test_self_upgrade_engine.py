from typing import Any, Dict, List

from thomas.core.self_upgrade_engine import SelfUpgradeEngine


class _FakeIssueEngine:
    def __init__(self, report: dict[str, Any]) -> None:
        self._report = dict(report)
        self.calls: list[dict[str, Any]] = []

    def run_cycle_once(self, *, reason: str = "manual", force: bool = False) -> dict[str, Any]:
        self.calls.append({"reason": reason, "force": force})
        return dict(self._report)


class _FakePersistence:
    def __init__(self) -> None:
        self.goals: dict[str, dict[str, Any]] = {}
        self.facts: dict[str, Any] = {}

    def upsert_goal(self, goal_id: str, text: str, status: str = "open") -> None:
        self.goals[goal_id] = {"id": goal_id, "text": text, "status": status}

    def close_goal(self, goal_id: str) -> None:
        if goal_id in self.goals:
            self.goals[goal_id]["status"] = "done"

    def open_goals(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.goals.values() if str(item.get("status")) == "open"]

    def set_fact(self, key: str, value: Any) -> None:
        self.facts[key] = value


def test_self_upgrade_engine_creates_upgrade_goals(monkeypatch) -> None:
    issue_engine = _FakeIssueEngine(
        {
            "ok": True,
            "clean": False,
            "unresolved_count": 2,
            "unresolved": [
                {"name": "python_compile"},
                {"name": "architecture_fitness"},
            ],
        }
    )
    fake_persistence = _FakePersistence()

    engine = SelfUpgradeEngine(
        issue_engine=issue_engine,  # type: ignore[arg-type]
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
    )

    def fake_module_check(module: str) -> dict[str, Any]:
        if module == "thomas.system.config_validator":
            return {"ok": False, "summary": {"error_count": 1, "warning_count": 0}}
        if module == "thomas.system.release_contracts":
            return {"ok": True, "summary": {"error_count": 0, "warning_count": 2}}
        return {"ok": True, "summary": {"error_count": 0, "warning_count": 0}}

    engine._run_json_module_check = fake_module_check  # type: ignore[method-assign]
    engine._run_ui_workflow_check = lambda: {  # type: ignore[method-assign]
        "ok": True,
        "score": 95,
        "warning_count": 0,
        "warnings": [],
    }
    monkeypatch.setattr("thomas.core.self_upgrade_engine.get_persistence", lambda: fake_persistence)

    report = engine.run_cycle_once(reason="test", force=True)

    assert report.get("ok") is True
    assert int(report.get("opportunity_count") or 0) == 3
    open_goals = fake_persistence.open_goals()
    assert len(open_goals) == 3
    assert all(str(row.get("id") or "").startswith("self-upgrade:") for row in open_goals)
    assert "self_upgrade.last_report" in fake_persistence.facts


def test_self_upgrade_engine_closes_stale_goals_when_clean(monkeypatch) -> None:
    issue_engine = _FakeIssueEngine(
        {
            "ok": True,
            "clean": True,
            "unresolved_count": 0,
            "unresolved": [],
        }
    )
    fake_persistence = _FakePersistence()
    fake_persistence.upsert_goal("self-upgrade:code_issues:oldgoal", "old upgrade goal", status="open")

    engine = SelfUpgradeEngine(
        issue_engine=issue_engine,  # type: ignore[arg-type]
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
    )
    engine._run_json_module_check = lambda module: {  # type: ignore[method-assign]
        "ok": True,
        "summary": {"error_count": 0, "warning_count": 0},
    }
    engine._run_ui_workflow_check = lambda: {  # type: ignore[method-assign]
        "ok": True,
        "score": 97,
        "warning_count": 0,
        "warnings": [],
    }
    monkeypatch.setattr("thomas.core.self_upgrade_engine.get_persistence", lambda: fake_persistence)

    report = engine.run_cycle_once(reason="test-clean", force=True)

    assert report.get("ok") is True
    assert int(report.get("opportunity_count") or 0) == 0
    assert fake_persistence.goals["self-upgrade:code_issues:oldgoal"]["status"] == "done"


def test_self_upgrade_engine_manual_cycle_returns_busy_when_active() -> None:
    engine = SelfUpgradeEngine(
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
    )
    engine._active_cycle = True
    report = engine.run_cycle_once(reason="manual", force=True)
    assert report.get("ok") is False
    assert report.get("reason") == "busy"


def test_self_upgrade_engine_adds_ui_quality_opportunity(monkeypatch) -> None:
    issue_engine = _FakeIssueEngine(
        {
            "ok": True,
            "clean": True,
            "unresolved_count": 0,
            "unresolved": [],
        }
    )
    fake_persistence = _FakePersistence()
    engine = SelfUpgradeEngine(
        issue_engine=issue_engine,  # type: ignore[arg-type]
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
    )
    engine._run_json_module_check = lambda module: {  # type: ignore[method-assign]
        "ok": True,
        "summary": {"error_count": 0, "warning_count": 0},
    }
    engine._run_ui_workflow_check = lambda: {  # type: ignore[method-assign]
        "ok": True,
        "score": 62,
        "warning_count": 3,
        "warnings": [
            {"id": "tokens.unresolved"},
            {"id": "motion.reduced"},
            {"id": "a11y.focus_visible"},
        ],
    }
    monkeypatch.setattr("thomas.core.self_upgrade_engine.get_persistence", lambda: fake_persistence)

    report = engine.run_cycle_once(reason="test-ui", force=True)

    assert report.get("ok") is True
    assert int(report.get("opportunity_count") or 0) == 1
    opportunities = list(report.get("opportunities") or [])
    assert opportunities
    first = opportunities[0] if isinstance(opportunities[0], dict) else {}
    assert str(first.get("kind") or "") == "ui_quality_hardening"
    open_goals = fake_persistence.open_goals()
    assert len(open_goals) == 1
    assert str(open_goals[0].get("id") or "").startswith("self-upgrade:ui_quality_hardening:")
