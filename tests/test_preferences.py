import sys
from pathlib import Path

# Ensure repo root is on PYTHONPATH when running tests standalone.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from thomas.preferences.api import router as preferences_router
from thomas.preferences.store import PreferencesStore


@pytest.fixture()
def tmp_db(tmp_path: Path):
    db = tmp_path / "prefs_test.db"
    os.environ["THOMAS_DB_PATH"] = str(db)
    yield db
    os.environ.pop("THOMAS_DB_PATH", None)


def make_app():
    app = FastAPI()
    app.include_router(preferences_router)
    return app


def test_defaults(tmp_db):
    app = make_app()
    c = TestClient(app)
    r = c.get("/api/preferences")
    assert r.status_code == 200
    data = r.json()
    assert data["appearance"]["theme"] == "auto"
    assert data["appearance"]["font_size"] == 16
    assert data["appearance"]["bubble_style"] == "rounded"
    assert data["memory"]["enabled_global"] is True
    assert data["api_keys"]["openai"] is None


def test_patch_partial_does_not_wipe(tmp_db):
    app = make_app()
    c = TestClient(app)

    # set multiple values
    r = c.patch("/api/preferences", json={"appearance": {"theme": "dark", "font_size": 18}})
    assert r.status_code == 200
    assert r.json()["appearance"]["theme"] == "dark"
    assert r.json()["appearance"]["font_size"] == 18
    assert r.json()["appearance"]["bubble_style"] == "rounded"  # unchanged default

    # patch only one field
    r = c.patch("/api/preferences", json={"appearance": {"bubble_style": "compact"}})
    assert r.status_code == 200
    assert r.json()["appearance"]["theme"] == "dark"
    assert r.json()["appearance"]["font_size"] == 18
    assert r.json()["appearance"]["bubble_style"] == "compact"


def test_thread_memory_override(tmp_db):
    app = make_app()
    c = TestClient(app)

    r = c.get("/api/preferences?thread_id=t1")
    assert r.status_code == 200
    assert r.json()["memory"]["thread_enabled"] is True

    r = c.patch("/api/preferences?thread_id=t1", json={"memory": {"thread_enabled": False}})
    assert r.status_code == 200
    assert r.json()["memory"]["thread_enabled"] is False

    r = c.get("/api/preferences?thread_id=t2")
    assert r.status_code == 200
    assert r.json()["memory"]["thread_enabled"] is True

    r = c.patch("/api/preferences?thread_id=t1", json={"memory": {"thread_enabled": None}})
    assert r.status_code == 200
    assert r.json()["memory"]["thread_enabled"] is True


def test_api_keys_encrypted_and_masked_without_decrypt(tmp_db):
    app = make_app()
    c = TestClient(app)

    key = "sk-test-123456"
    r = c.patch("/api/preferences", json={"api_keys": {"openai": key}})
    assert r.status_code == 200

    masked = r.json()["api_keys"]["openai"]
    assert masked.endswith("3456")
    assert "sk-test" not in masked

    # ensure DB doesn't contain plaintext
    conn = sqlite3.connect(os.environ["THOMAS_DB_PATH"])
    row = conn.execute("SELECT enc_value, mask_tail, key_hash FROM preference_keys WHERE provider='openai'").fetchone()
    assert row is not None
    enc, mask_tail, key_hash = row
    assert "sk-test" not in enc
    assert mask_tail.endswith("3456")
    assert isinstance(key_hash, str) and len(key_hash) == 64
    conn.close()

    # ensure store can decrypt with same key
    store = PreferencesStore(db_path=os.environ["THOMAS_DB_PATH"])
    assert store.get_api_key_plain("default", "openai") == key


def test_delete_key(tmp_db):
    app = make_app()
    c = TestClient(app)

    r = c.patch("/api/preferences", json={"api_keys": {"openai": "sk-test-123456"}})
    assert r.status_code == 200
    assert r.json()["api_keys"]["openai"] is not None

    r = c.patch("/api/preferences", json={"api_keys": {"openai": None}})
    assert r.status_code == 200
    assert r.json()["api_keys"]["openai"] is None


def test_onboarding_patch_roundtrip(tmp_db):
    app = make_app()
    c = TestClient(app)

    completed_at = "2026-02-21T12:00:00Z"
    dismissed_at = "2026-02-20T09:10:11Z"
    payload = {
        "onboarding": {
            "setup_completed": True,
            "version": 2,
            "completed_at": completed_at,
            "dismissed_at": dismissed_at,
            "answers": {"experience": "builder", "autonomy": "balanced"},
        }
    }
    r = c.patch("/api/preferences", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["onboarding"]["setup_completed"] is True
    assert data["onboarding"]["version"] == 2
    assert data["onboarding"]["completed_at"] == completed_at
    assert data["onboarding"]["dismissed_at"] == dismissed_at
    assert data["onboarding"]["answers"]["experience"] == "builder"

    clear = c.patch("/api/preferences", json={"onboarding": {"dismissed_at": None}})
    assert clear.status_code == 200
    assert clear.json()["onboarding"]["dismissed_at"] is None
