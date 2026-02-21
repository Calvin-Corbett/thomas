import types
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakePE:
    def __init__(self):
        self.goals = []

    def add_goal(self, text, priority="medium"):
        gid = str(len(self.goals) + 1)
        self.goals.append({
            "id": gid,
            "text": text,
            "priority": priority,
            "status": "open",
            "created": "2026-01-01T00:00:00+00:00",
        })
        return gid

    def close_goal(self, gid):
        for g in self.goals:
            if str(g.get("id")) == str(gid):
                g["status"] = "done"

    def delete_goal(self, gid):
        self.goals = [g for g in self.goals if str(g.get("id")) != str(gid)]


@pytest.fixture()
def client(monkeypatch):
    pe = FakePE()

    from thomas.server.routes import goals as goals_routes
    monkeypatch.setattr(goals_routes, "get_persistence", lambda: pe)

    class Engine:
        def __init__(self):
            self.calls = []

        def queue_goal(self, goal):
            self.calls.append(goal)

    engine = Engine()
    fake_mod = types.SimpleNamespace(get_initiative_engine=lambda: engine)

    real_import = importlib.import_module

    def fake_import(name):
        if name in ("thomas.core.initiative", "thomas.core.initiative_engine", "thomas.initiative", "thomas.initiative_engine"):
            return fake_mod
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    app = FastAPI()
    app.include_router(goals_routes.router)
    c = TestClient(app)
    c._pe = pe
    c._engine = engine
    return c


def test_etag_304(client):
    client.post("/api/goals", json={"text": "a", "priority": "high"})
    r1 = client.get("/api/goals")
    assert r1.status_code == 200
    etag = r1.headers.get("ETag")
    assert etag
    r2 = client.get("/api/goals", headers={"If-None-Match": etag})
    assert r2.status_code == 304


def test_rank_sorting(client):
    client.post("/api/goals", json={"text": "a", "priority": "medium"})
    client.post("/api/goals", json={"text": "b", "priority": "medium"})
    client.patch("/api/goals/1", json={"rank": 10.0})
    client.patch("/api/goals/2", json={"rank": 0.0})
    data = client.get("/api/goals").json()
    assert data["open"][0]["id"] == "2"


def test_done_sets_done_at(client):
    client.post("/api/goals", json={"text": "x", "priority": "medium"})
    r = client.patch("/api/goals/1", json={"status": "done"})
    assert r.status_code == 200
    g = r.json()["goal"]
    assert g["status"] == "done"
    assert "done_at" in g


def test_stats_endpoint(client):
    client.post("/api/goals", json={"text": "x", "priority": "medium"})
    client.patch("/api/goals/1", json={"status": "done"})
    s = client.get("/api/goals/stats")
    assert s.status_code == 200
    body = s.json()
    assert "done" in body and body["done"] == 1


def test_run_endpoint(client):
    client.post("/api/goals", json={"text": "run me", "priority": "medium"})
    r = client.post("/api/goals/1/run")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
