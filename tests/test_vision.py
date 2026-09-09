import io
import os
import time

import pytest

pytest.importorskip("PIL")
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from thomas.marketplace.vision.api import (
    cleanup_old_uploads,
    get_upload_dir,
    resolve_upload_paths,
)
from thomas.marketplace.vision.api import (
    router as vision_router,
)
from thomas.marketplace.vision.handler import (
    build_anthropic_payload,
    build_openai_payload,
    build_provider_request,
    extract_image_ids,
)


@pytest.fixture()
def tmp_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("THOMAS_UPLOAD_TTL_SECONDS", "1")
    monkeypatch.setenv("THOMAS_MAX_UPLOAD_MB", "1")  # 1MB
    monkeypatch.setenv("THOMAS_OPENAI_API_STYLE", "responses")
    return get_upload_dir()


@pytest.fixture()
def app(tmp_upload_dir):
    app = FastAPI()
    app.include_router(vision_router)
    return app


@pytest.fixture()
def client(app):
    return TestClient(app)


def _png_bytes():
    img = Image.new("RGB", (220, 80), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_upload_single_file_returns_uploads_list(client, tmp_upload_dir):
    png = _png_bytes()
    r = client.post("/api/chat/upload", files=[("file", ("test.png", png, "image/png"))])
    assert r.status_code == 200, r.text
    data = r.json()
    assert "uploads" in data and isinstance(data["uploads"], list)
    assert len(data["uploads"]) == 1
    item = data["uploads"][0]
    assert item["token"].startswith("thomas-upload://")
    # file exists
    p = resolve_upload_paths([item["image_id"]])
    assert p and p[0].exists()
    # sidecar exists
    side = p[0].with_suffix(p[0].suffix + ".json")
    assert side.exists()


def test_upload_dedupes_same_bytes(client, tmp_upload_dir):
    png = _png_bytes()
    r1 = client.post("/api/chat/upload", files=[("file", ("a.png", png, "image/png"))])
    r2 = client.post("/api/chat/upload", files=[("file", ("b.png", png, "image/png"))])
    assert r1.status_code == 200 and r2.status_code == 200
    id1 = r1.json()["uploads"][0]["image_id"]
    id2 = r2.json()["uploads"][0]["image_id"]
    assert id1 == id2


def test_upload_multiple_files(client):
    png = _png_bytes()
    r = client.post(
        "/api/chat/upload",
        files=[
            ("file", ("a.png", png, "image/png")),
            ("file", ("b.png", png, "image/png")),
        ],
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["uploads"]) == 2


def test_reject_non_image(client):
    r = client.post("/api/chat/upload", files=[("file", ("x.txt", b"hello", "text/plain"))])
    assert r.status_code in (415, 422)


def test_size_limit(client, monkeypatch):
    monkeypatch.setenv("THOMAS_MAX_UPLOAD_MB", "0.0005")  # ~512 bytes
    big = b"0" * 5000
    r = client.post("/api/chat/upload", files=[("file", ("big.png", big, "image/png"))])
    assert r.status_code in (413, 415)


def test_cleanup_old_uploads(tmp_upload_dir):
    tmp_upload_dir.mkdir(parents=True, exist_ok=True)
    old = tmp_upload_dir / "old.png"
    old.write_bytes(b"123")
    old_meta = tmp_upload_dir / "old.png.json"
    old_meta.write_text("{}", encoding="utf-8")
    old_mtime = time.time() - 10
    os.utime(old, (old_mtime, old_mtime))
    os.utime(old_meta, (old_mtime, old_mtime))

    deleted = cleanup_old_uploads(tmp_upload_dir, ttl_seconds=1)
    assert deleted >= 1
    assert not old.exists()
    assert not old_meta.exists()


def test_extract_image_ids_from_text():
    text = "here thomas-upload://2f4b0f1f3f4b4b53a0f37d3f0d3e12aa wow"
    ids = extract_image_ids(text)
    assert ids == ["2f4b0f1f3f4b4b53a0f37d3f0d3e12aa"]


def test_openai_payload_responses_contains_input_image(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_OPENAI_API_STYLE", "responses")
    img = tmp_path / "x.png"
    img.write_bytes(_png_bytes())
    payload = build_openai_payload("what is this", [img], "gpt-4o", max_tokens=200)
    assert "input" in payload
    content = payload["input"][0]["content"]
    assert any(part.get("type") == "input_image" for part in content)


def test_openai_payload_chat_contains_image_url(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_OPENAI_API_STYLE", "chat_completions")
    img = tmp_path / "x.png"
    img.write_bytes(_png_bytes())
    payload = build_openai_payload("what is this", [img], "gpt-4o", max_tokens=200)
    msgs = payload["messages"]
    content = msgs[0]["content"]
    assert any(part.get("type") == "image_url" for part in content)


def test_anthropic_payload_contains_image_block(tmp_path):
    img = tmp_path / "x.png"
    img.write_bytes(_png_bytes())
    payload = build_anthropic_payload("what is this", [img], "claude-sonnet-4-6", max_tokens=200)
    blocks = payload["messages"][0]["content"]
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["type"] == "base64"
    assert blocks[-1]["type"] == "text"


@pytest.mark.asyncio
async def test_ocr_fallback_path(monkeypatch, tmp_path):
    # Force no-vision while still selecting OpenAI provider
    monkeypatch.setenv("THOMAS_MODEL_CAPS_JSON", '{"gpt-4o":{"vision":false,"provider":"openai"}}')
    img = tmp_path / "x.png"
    img.write_bytes(_png_bytes())

    # Mock OCR to avoid requiring tesseract in CI
    monkeypatch.setattr("thomas.marketplace.vision.handler.extract_text_from_images", lambda paths: ["hello from ocr"])

    req = await build_provider_request(
        prompt="read this",
        image_paths=[img],
        active_model="gpt-4o",
        max_tokens=200,
    )
    assert req.used_ocr_fallback is True
    assert "OCR_EXTRACT_FROM_IMAGES" in (req.ocr_text or "")
    assert req.provider == "openai"
