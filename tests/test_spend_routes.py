from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from thomas.core.cost_tracker import CostTracker
from thomas.server.routes import spend as spend_routes


def test_spend_routes(tmp_path: Path, monkeypatch):
    spend = tmp_path / "spend.jsonl"
    toml = tmp_path / "thomas.toml"
    toml.write_text("", encoding="utf-8")

    ct = CostTracker(spend_path=spend, toml_path=toml)
    monkeypatch.setattr(spend_routes, "get_cost_tracker", lambda: ct)

    app = FastAPI()
    app.include_router(spend_routes.router)
    client = TestClient(app)

    ct.record(model="gpt-4o", provider="openai", prompt_tokens=10, completion_tokens=5)

    r = client.get("/api/spend/today")
    assert r.status_code == 200
    body = r.json()
    assert "total_usd" in body
    assert "by_model_detail" in body
    assert "tokens" in body

    r2 = client.get("/api/spend/history?days=7")
    assert r2.status_code == 200
    assert isinstance(r2.json(), list)

    r3 = client.get("/api/spend/export.csv?days=7")
    assert r3.status_code == 200
    assert "text/csv" in r3.headers.get("content-type", "")
