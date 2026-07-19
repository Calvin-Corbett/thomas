from __future__ import annotations

import json
from pathlib import Path

from thomas.work import WorkStore


def test_work_store_reads_runtime_workforce_and_user_work_apps(tmp_path: Path) -> None:
    runtime_apps = tmp_path / "legacy-runtime" / "freedom-transit"
    runtime_apps.mkdir(parents=True)
    (runtime_apps / "spec.json").write_text(
        json.dumps(
            {
                "app_id": "freedom-transit",
                "name": "Freedom Transit",
                "goal": "Operate freight dispatch",
                "connector_grants": [
                    {
                        "connector_id": "gmail",
                        "account_id": "ops@example.com",
                        "label": "Operations Gmail",
                        "status": "ready",
                        "scopes": ["mail.read"],
                    }
                ],
                "workflows": [
                    {
                        "workflow_id": "morning-brief",
                        "title": "Morning brief",
                        "detail": "Prepare the morning dispatch brief",
                        "trigger": "08:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (runtime_apps / "jobs.json").write_text(
        json.dumps(
            [
                {
                    "id": "load-monitor",
                    "name": "Load monitor",
                    "payload": {"prompt": "Monitor open loads"},
                    "connector_ids": ["gmail"],
                    "paused": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    user_work_apps = tmp_path / "legacy-user" / "work_apps.json"
    user_work_apps.parent.mkdir(parents=True)
    user_work_apps.write_text(
        json.dumps(
            {
                "apps": [{"id": "mail-digest", "name": "Mail Digest", "goal": "Summarize mail"}],
                "messages": {
                    "mail-digest": [
                        {"role": "user", "text": "Start", "created_at": "2026-07-14T10:00:00Z"},
                        {"role": "thomas", "text": "Ready", "created_at": "2026-07-14T10:01:00Z"},
                    ]
                },
                "sessions": {"mail-digest": "legacy-mail-session"},
                "settings": {"mail-digest": {"autonomy": 3, "reasoning": "high", "unknown": "drop"}},
            }
        ),
        encoding="utf-8",
    )

    store = WorkStore(
        tmp_path / "new-state",
        runtime_apps_root=runtime_apps.parent,
        user_work_apps_path=user_work_apps,
    )

    transit = store.get_app("freedom-transit")
    load_job = store.get_job("freedom-transit", "load-monitor")
    migrated_automation = store.get_job("freedom-transit", "morning-brief")["automations"][0]
    assert transit["goal"] == "Operate freight dispatch"
    assert transit["onboarding"]["phase"] == "ready"
    assert load_job["goal"] == "Monitor open loads"
    assert load_job["status"] == "paused"
    assert load_job["connector_bindings"][0]["provider"] == "gmail"
    assert migrated_automation["delegation"]["state"] == "not_deployed"
    assert store.list_accounts(provider="gmail")[0]["identity"] == "ops@example.com"

    mail_job = store.get_job("mail-digest", "primary")
    assert store.get_app("mail-digest")["onboarding"]["phase"] == "ready"
    assert mail_job["history"]["session_id"] == "legacy-mail-session"
    assert mail_job["history"]["message_count"] == 2
    assert mail_job["settings"] == {"autonomy": 3, "reasoning": "high"}
    assert {row["kind"] for row in store.snapshot()["migrations"]["sources"]} == {
        "runtime_workforce",
        "user_work_apps",
    }
