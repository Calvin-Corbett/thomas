"""A broken Work app must not disable unrelated Work routes or rewrite durable state."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.work import register_work_routes
from thomas.work import WorkConflictError, WorkCorruptStateError, WorkStore


def _mixed_store(root: Path) -> tuple[Path, str]:
    store = WorkStore(root)
    store.create_app({"id": "healthy", "name": "Healthy", "goal": "Keep going"})
    store.create_job("healthy", {"id": "good-job", "name": "Good job", "goal": "Keep going"})
    store.create_app({"id": "app-75c180040a34", "name": "Stock", "goal": "Track stock"})
    store.create_job(
        "app-75c180040a34",
        {"id": "once-stock-proof-0007", "name": "Stock proof", "goal": "Track stock"},
    )
    store.create_workflow(
        "app-75c180040a34",
        "once-stock-proof-0007",
        {"id": "stock", "name": "Stock", "purpose": "Track stock", "type": "scheduled"},
    )
    store.create_automation(
        "app-75c180040a34",
        "once-stock-proof-0007",
        {"id": "manual-stock", "name": "Manual", "trigger": {"type": "manual"}},
    )
    with pytest.raises(WorkConflictError, match="scheduled workflow cannot use a manual trigger"):
        store.update_workflow(
            "app-75c180040a34",
            "once-stock-proof-0007",
            "stock",
            {"automation_id": "manual-stock"},
        )
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    state["apps"]["app-75c180040a34"]["jobs"]["once-stock-proof-0007"]["memory"]["workflows"][0]["automation_id"] = (
        "manual-stock"
    )
    original = json.dumps(state, indent=2)
    store.state_path.write_text(original, encoding="utf-8")
    return store.state_path, original


@pytest.mark.asyncio
async def test_corrupt_app_isolated_without_rewriting_store(tmp_path: Path) -> None:
    state_path, original = _mixed_store(tmp_path)
    store = WorkStore(tmp_path)
    assert state_path.read_text(encoding="utf-8") == original
    app = web.Application()
    register_work_routes(app, store=store, require_api_access=lambda request: None)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.get("/api/work/apps")
        assert response.status == 200
        data = await response.json()
        assert [row["id"] for row in data["apps"]] == ["healthy"]
        assert data["warnings"] == [
            {
                "app_id": "app-75c180040a34",
                "job_id": "once-stock-proof-0007",
                "workflow_id": "stock",
                "reason": "scheduled workflow cannot use a manual trigger",
            }
        ]
        assert (await client.get("/api/work/apps/healthy/jobs/good-job")).status == 200
        assert (await client.get("/api/work/accounts")).status == 200
        assert (await client.get("/api/work/connectors")).status == 200
        assert (await client.get("/api/work/apps/app-75c180040a34")).status != 200
        assert (await client.get("/api/work/apps/healthy/jobs/good-job/automations")).status == 200
        assert state_path.read_text(encoding="utf-8") == original
        assert (
            await client.post("/api/work/apps", json={"id": "app-75c180040a34", "name": "Replacement"})
        ).status == 409
        assert state_path.read_text(encoding="utf-8") == original
        assert (await client.patch("/api/work/apps/healthy", json={"goal": "Still working"})).status == 200
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert saved["apps"]["app-75c180040a34"] == json.loads(original)["apps"]["app-75c180040a34"]
        assert WorkStore(tmp_path).work_warnings[0]["workflow_id"] == "stock"
    finally:
        await client.close()


def test_isolation_does_not_miss_other_bad_links(tmp_path: Path) -> None:
    state_path, _ = _mixed_store(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    job = state["apps"]["app-75c180040a34"]["jobs"]["once-stock-proof-0007"]
    job["memory"]["workflows"].append(
        {
            **job["memory"]["workflows"][0],
            "id": "stock-extra",
            "name": "Stock extra",
            "purpose": "Another stock check",
            "status": "planned",
            "automation_id": "missing",
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    store = WorkStore(tmp_path)
    assert {(row["workflow_id"], row["reason"]) for row in store.work_warnings} == {
        ("stock", "scheduled workflow cannot use a manual trigger"),
        ("stock-extra", "workflow automation must exist in the same job"),
    }
    assert [row["id"] for row in store.list_apps()] == ["healthy"]
    assert state_path.read_text(encoding="utf-8") == json.dumps(state)


@pytest.mark.parametrize("apps", [None, []], ids=["null", "list"])
def test_non_object_apps_are_store_faults(tmp_path: Path, apps: object) -> None:
    store = WorkStore(tmp_path)
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    state["apps"] = apps
    store.state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(WorkCorruptStateError):
        WorkStore(tmp_path)


def test_missing_apps_are_store_faults(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    del state["apps"]
    store.state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(WorkCorruptStateError):
        WorkStore(tmp_path)


def test_bad_link_followed_by_unlinked_workflow_is_isolated(tmp_path: Path) -> None:
    state_path, _ = _mixed_store(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    job = state["apps"]["app-75c180040a34"]["jobs"]["once-stock-proof-0007"]
    unlinked = {
        **job["memory"]["workflows"][0],
        "id": "stock-unlinked",
        "name": "Unlinked stock",
        "status": "planned",
    }
    del unlinked["automation_id"]
    job["memory"]["workflows"].append(unlinked)
    original = json.dumps(state)
    state_path.write_text(original, encoding="utf-8")

    store = WorkStore(tmp_path)
    assert [app["id"] for app in store.list_apps()] == ["healthy"]
    assert store.work_warnings == [
        {
            "app_id": "app-75c180040a34",
            "job_id": "once-stock-proof-0007",
            "workflow_id": "stock",
            "reason": "scheduled workflow cannot use a manual trigger",
        }
    ]
    assert state_path.read_text(encoding="utf-8") == original


def test_work_page_displays_isolated_record_and_reason() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "node",
            str(root / "tests/web_node/work_corrupt_app_warning.mjs"),
            str(root / "thomas/server/web/js/unified_work_mode.js"),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_scheduled_workflow_accepts_once_link_and_survives_reload(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    store.create_app({"id": "stock-app", "name": "Stock", "goal": "Check stock"})
    store.create_job("stock-app", {"id": "stock-job", "name": "Check", "goal": "Check stock"})
    store.create_automation(
        "stock-app",
        "stock-job",
        {"id": "once-stock", "name": "Once", "trigger": {"type": "once", "run_at": "2026-07-15T13:00:00Z"}},
    )
    workflow = store.create_workflow(
        "stock-app",
        "stock-job",
        {
            "id": "stock",
            "name": "Stock",
            "purpose": "Check stock once",
            "type": "scheduled",
            "automation_id": "once-stock",
        },
    )
    assert workflow["automation_id"] == "once-stock"
    reloaded = WorkStore(tmp_path)
    assert reloaded.get_workflow("stock-app", "stock-job", "stock")["automation_id"] == "once-stock"
    assert reloaded.work_warnings == []
    script = (Path(__file__).resolve().parents[1] / "thomas/server/web/js/unified_work_support.js").read_text(
        encoding="utf-8"
    )
    scheduled_options = script.split("const triggerOptions = selected && selected.type === 'scheduled'", 1)[1].split(
        ": selected && selected.type === 'event'", 1
    )[0]
    assert '<option value="once">Once</option>' in scheduled_options
    mode = (Path(__file__).resolve().parents[1] / "thomas/server/web/js/unified_work_mode.js").read_text(
        encoding="utf-8"
    )
    assert "if (kind === 'once') trigger.run_at = detail;" in mode


@pytest.mark.asyncio
async def test_mixed_store_with_once_link_keeps_both_apps_available(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    store.create_app({"id": "healthy", "name": "Healthy", "goal": "Keep going"})
    store.create_app({"id": "app-75c180040a34", "name": "Stock", "goal": "Track stock"})
    store.create_job(
        "app-75c180040a34",
        {"id": "once-stock-proof-0007", "name": "Stock proof", "goal": "Track stock"},
    )
    store.create_workflow(
        "app-75c180040a34",
        "once-stock-proof-0007",
        {"id": "stock", "name": "Stock", "purpose": "Track stock", "type": "scheduled"},
    )
    store.create_automation(
        "app-75c180040a34",
        "once-stock-proof-0007",
        {"id": "once-stock", "name": "Once", "trigger": {"type": "once", "run_at": "2026-07-15T13:00:00Z"}},
    )
    store.update_workflow("app-75c180040a34", "once-stock-proof-0007", "stock", {"automation_id": "once-stock"})
    before = store.state_path.read_bytes()
    reloaded = WorkStore(tmp_path)
    app = web.Application()
    register_work_routes(app, store=reloaded, require_api_access=lambda request: None)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.get("/api/work/apps")
        assert response.status == 200
        result = await response.json()
        assert {row["id"] for row in result["apps"]} == {"healthy", "app-75c180040a34"}
        assert result["warnings"] == []
        assert (await client.get("/api/work/accounts")).status == 200
        assert (await client.get("/api/work/connectors")).status == 200
        assert store.state_path.read_bytes() == before
    finally:
        await client.close()


def test_unrelated_corruption_is_not_silently_isolated(tmp_path: Path) -> None:
    state_path, _ = _mixed_store(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["apps"]["app-75c180040a34"]["jobs"]["once-stock-proof-0007"]["history"] = []
    original = json.dumps(state)
    state_path.write_text(original, encoding="utf-8")
    store = WorkStore(tmp_path)
    assert [app["id"] for app in store.list_apps()] == ["healthy"]
    assert store.work_warnings == [
        {
            "app_id": "app-75c180040a34",
            "job_id": "once-stock-proof-0007",
            "workflow_id": "",
            "reason": "durable Work job metadata is invalid",
        }
    ]
    assert state_path.read_text(encoding="utf-8") == original
    store.update_app("healthy", {"goal": "Keep working"})
    assert (
        json.loads(state_path.read_text(encoding="utf-8"))["apps"]["app-75c180040a34"]
        == state["apps"]["app-75c180040a34"]
    )


@pytest.mark.parametrize(
    ("fault", "reason", "job_id"),
    [
        ("onboarding", "durable Work onboarding phase is invalid", ""),
        ("automation", "durable Work automation definitions are invalid", "once-stock-proof-0007"),
        ("second_job", "durable Work job entries are invalid", "broken-job"),
    ],
)
def test_other_app_faults_leave_healthy_app_available(tmp_path: Path, fault: str, reason: str, job_id: str) -> None:
    state_path, _ = _mixed_store(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    bad_app = state["apps"]["app-75c180040a34"]
    if fault == "onboarding":
        bad_app["onboarding"]["phase"] = "unknown"
    elif fault == "automation":
        bad_app["jobs"]["once-stock-proof-0007"]["automations"][0]["trigger"] = []
    else:
        bad_app["jobs"]["broken-job"] = "not a job"
    original = json.dumps(state)
    state_path.write_text(original, encoding="utf-8")
    store = WorkStore(tmp_path)
    assert [app["id"] for app in store.list_apps()] == ["healthy"]
    assert {"app_id": "app-75c180040a34", "job_id": job_id, "workflow_id": "", "reason": reason} in (
        store.work_warnings
    )
    if fault == "second_job":
        assert len(store.work_warnings) == 2  # Also reports the fixture's incompatible stock link.
    else:
        assert len(store.work_warnings) == 1
    assert state_path.read_text(encoding="utf-8") == original


def test_unhashable_workflow_type_does_not_disable_healthy_app(tmp_path: Path) -> None:
    state_path, _ = _mixed_store(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    job = state["apps"]["app-75c180040a34"]["jobs"]["once-stock-proof-0007"]
    job["memory"]["workflows"][0]["type"] = []
    original = json.dumps(state)
    state_path.write_text(original, encoding="utf-8")
    store = WorkStore(tmp_path)
    assert [app["id"] for app in store.list_apps()] == ["healthy"]
    assert store.work_warnings == [
        {
            "app_id": "app-75c180040a34",
            "job_id": "once-stock-proof-0007",
            "workflow_id": "stock",
            "reason": "unhashable type: 'list'",
        }
    ]
    assert state_path.read_text(encoding="utf-8") == original
    store.update_app("healthy", {"goal": "Still healthy"})
    assert (
        json.loads(state_path.read_text(encoding="utf-8"))["apps"]["app-75c180040a34"]
        == state["apps"]["app-75c180040a34"]
    )


@pytest.mark.parametrize(
    ("collection", "bad_value", "reason"),
    [
        ("connector_accounts", {"broken": []}, "connector accounts"),
        ("global_skills", {"broken": []}, "global skills"),
        ("migrations", {"sources": "broken"}, "migration receipts"),
    ],
)
def test_store_level_fault_still_fails_whole_store(
    tmp_path: Path, collection: str, bad_value: dict, reason: str
) -> None:
    state_path, _ = _mixed_store(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state[collection] = bad_value
    original = json.dumps(state)
    state_path.write_text(original, encoding="utf-8")
    with pytest.raises(WorkCorruptStateError, match=reason):
        WorkStore(tmp_path)
    assert state_path.read_text(encoding="utf-8") == original
