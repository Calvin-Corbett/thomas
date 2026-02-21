import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from thomas.notifications.api import init_notifications


@pytest.fixture()
def app_and_client():
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "notifications.sqlite")
        app = FastAPI()
        init_notifications(app, db_path=db_path)
        client = TestClient(app)
        yield app, client


def test_create_and_list(app_and_client):
    _, client = app_and_client

    # create
    r = client.post("/api/notifications", json={
        "type": "task.complete",
        "title": "Done",
        "body": "Your task completed.",
        "severity": "info",
        "action_url": "/tasks/1"
    })
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["type"] == "task.complete"
    assert created["read"] is False

    # list
    r = client.get("/api/notifications")
    assert r.status_code == 200
    data = r.json()
    assert data["unread_count"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == created["id"]


def test_mark_read_and_unread_count(app_and_client):
    _, client = app_and_client

    r = client.post("/api/notifications", json={
        "type": "reminder.fired",
        "title": "Reminder",
        "body": "Time to do the thing",
        "severity": "warn"
    })
    nid = r.json()["id"]

    r = client.get("/api/notifications/unread_count")
    assert r.status_code == 200
    assert r.json()["unread_count"] == 1

    r = client.post(f"/api/notifications/{nid}/read")
    assert r.status_code == 200
    assert r.json()["read"] is True

    r = client.get("/api/notifications/unread_count")
    assert r.status_code == 200
    assert r.json()["unread_count"] == 0


def test_filters(app_and_client):
    _, client = app_and_client
    client.post("/api/notifications", json={
        "type": "autonomy.done",
        "title": "Auto job finished",
        "body": "All good",
        "severity": "info"
    })
    client.post("/api/notifications", json={
        "type": "error",
        "title": "Boom",
        "body": "Something failed",
        "severity": "error"
    })

    r = client.get("/api/notifications?severity=error")
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["severity"] == "error"

    r = client.get("/api/notifications?type=autonomy.done")
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["type"] == "autonomy.done"


def test_clear(app_and_client):
    _, client = app_and_client
    client.post("/api/notifications", json={
        "type": "file.ingested",
        "title": "Ingested",
        "body": "File imported",
        "severity": "info"
    })
    r = client.delete("/api/notifications/clear?mode=all")
    assert r.status_code == 200
    assert r.json()["deleted"] == 1

    r = client.get("/api/notifications")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 0


def test_service_worker_endpoint(app_and_client):
    _, client = app_and_client
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "addEventListener('push'" in r.text
