from __future__ import annotations

import base64
import io
import json
import os

import pytest
pytest.importorskip("PIL")
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from thomas.intake.api import router
from thomas.intake._internal.config import IntakeStorageConfig
from thomas.intake._internal.store import IntakeStore


@pytest.fixture()
def client(tmp_path: "pytest.PathLike[str]") -> TestClient:
    # isolate store to temp dir for tests
    os.environ["THOMAS_STATE_DIR"] = str(tmp_path)
    app = FastAPI()
    app.include_router(router)
    # initialize store explicitly so it uses tmp_path
    app.state.intake_store = IntakeStore(cfg=IntakeStorageConfig(base_dir=tmp_path / "intake"))
    return TestClient(app)


def test_text_json_intake(client: TestClient) -> None:
    r = client.post(
        "/api/intake/clipboard",
        json={"source": "clipboard", "content_type": "text/plain", "text": "hello thomas"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["deduped"] is False
    assert "Captured clipboard text" in data["summary"]


def test_image_json_intake(client: TestClient) -> None:
    img = Image.new("RGB", (120, 60), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    r = client.post(
        "/api/intake/clipboard",
        json={
            "source": "clipboard",
            "content_type": "image/png",
            "image_b64": b64,
            "ocr_text": "SAMPLE",
            "meta": {"width": 120, "height": 60},
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "Captured image" in data["summary"]


def test_multipart_image_intake(client: TestClient) -> None:
    img = Image.new("RGB", (64, 32), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    files = {"file": ("test.png", buf.getvalue(), "image/png")}
    data = {
        "source": "screenshot",
        "content_type": "image/png",
        "ocr_text": "HELLO",
        "meta_json": json.dumps({"width": 64, "height": 32}),
    }

    r = client.post("/api/intake/clipboard", files=files, data=data)
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] is True
    assert out["deduped"] is False


def test_idempotency_dedupe(client: TestClient) -> None:
    headers = {"Idempotency-Key": "abc123"}
    r1 = client.post("/api/intake/clipboard", headers=headers, json={"source": "clipboard", "content_type": "text/plain", "text": "X"})
    assert r1.status_code == 200
    d1 = r1.json()
    r2 = client.post("/api/intake/clipboard", headers=headers, json={"source": "clipboard", "content_type": "text/plain", "text": "X"})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["deduped"] is True
    assert d2["item_id"] == d1["item_id"]


def test_active_chat_pointer(client: TestClient) -> None:
    r = client.post("/api/intake/active", json={"chat_id": "chat-1"})
    assert r.status_code == 200
    g = client.get("/api/intake/active")
    assert g.status_code == 200
    assert g.json()["chat_id"] == "chat-1"


def test_list_and_get_item(client: TestClient) -> None:
    r = client.post("/api/intake/clipboard", json={"source": "clipboard", "content_type": "text/plain", "text": "A"})
    assert r.status_code == 200
    item_id = r.json()["item_id"]

    lst = client.get("/api/intake/items?limit=10")
    assert lst.status_code == 200
    items = lst.json()["items"]
    assert any(it["item_id"] == item_id for it in items)

    gi = client.get(f"/api/intake/items/{item_id}")
    assert gi.status_code == 200
    assert gi.json()["item_id"] == item_id


