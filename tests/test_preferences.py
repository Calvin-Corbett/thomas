# ruff: noqa: E402

import sys
from pathlib import Path

# Ensure repo root is on PYTHONPATH when running tests standalone.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
import sqlite3

import pytest
import scripts.breakglass_auth as breakglass_auth
from fastapi import FastAPI
from fastapi.testclient import TestClient

from thomas.preferences.api import router as preferences_router
from thomas.preferences.store import PreferencesStore, ProfilePrefs, profile_prefers_non_coder_mode


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
    assert data["profile"]["profile_type"] == "adaptive"
    assert data["profile"]["review_depth"] == "adaptive"
    assert data["api_keys"]["openai"] is None
    assert data["advanced"]["security"]["guardrails_posture"] == "standard"
    assert data["advanced"]["security"]["enforcement_mode"] == "protected"
    assert data["advanced"]["tools"]["require_command_approval"] is True


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


def test_profile_type_roundtrip_and_alias_normalization(tmp_db):
    app = make_app()
    c = TestClient(app)

    r = c.patch("/api/preferences", json={"profile": {"profile_type": "non-coder"}})
    assert r.status_code == 200
    assert r.json()["profile"]["profile_type"] == "non_coder"

    r = c.patch("/api/preferences", json={"profile": {"profile_type": "coder"}})
    assert r.status_code == 200
    assert r.json()["profile"]["profile_type"] == "coder"

    r = c.patch("/api/preferences", json={"profile": {"profile_type": "unknown-value"}})
    assert r.status_code == 200
    assert r.json()["profile"]["profile_type"] == "adaptive"


def test_profile_review_depth_roundtrip_and_alias_normalization(tmp_db):
    app = make_app()
    c = TestClient(app)

    r = c.patch("/api/preferences", json={"profile": {"review_depth": "simplified"}})
    assert r.status_code == 200
    assert r.json()["profile"]["review_depth"] == "simple"

    r = c.patch("/api/preferences", json={"profile": {"review_depth": "technical"}})
    assert r.status_code == 200
    assert r.json()["profile"]["review_depth"] == "technical"

    r = c.patch("/api/preferences", json={"profile": {"review_depth": "unknown-value"}})
    assert r.status_code == 200
    assert r.json()["profile"]["review_depth"] == "adaptive"


def test_non_coder_profile_forces_strict_quality_runtime_flags(tmp_db):
    app = make_app()
    c = TestClient(app)

    r = c.patch(
        "/api/preferences",
        json={
            "profile": {"profile_type": "non_coder"},
            "advanced": {
                "runtime": {
                    "quality_enforce": False,
                    "quality_require_verification_for_coding": False,
                    "quality_require_tests_for_code_edits": False,
                    "quality_require_monolith_guard_for_coding": False,
                }
            },
        },
    )
    assert r.status_code == 200
    runtime = r.json()["advanced"]["runtime"]
    assert runtime["quality_enforce"] is True
    assert runtime["quality_require_verification_for_coding"] is True
    assert runtime["quality_require_tests_for_code_edits"] is True
    assert runtime["quality_require_monolith_guard_for_coding"] is True

    # Strict values remain locked while profile_type is non_coder.
    r = c.patch("/api/preferences", json={"advanced": {"runtime": {"quality_enforce": False}}})
    assert r.status_code == 200
    assert r.json()["advanced"]["runtime"]["quality_enforce"] is True


def test_profile_type_helper_uses_onboarding_fallback():
    profile = ProfilePrefs(profile_type="adaptive")
    assert profile_prefers_non_coder_mode(profile, onboarding_answers={"experience": "new"}) is True
    assert profile_prefers_non_coder_mode(profile, onboarding_answers={"experience": "expert"}) is False


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
            "current_step": "dependencies",
            "connection_method": "local",
            "dependency_plan": {"node": {"installed": True}, "ollama": {"installed": False}},
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
    assert data["onboarding"]["current_step"] == "dependencies"
    assert data["onboarding"]["connection_method"] == "local"
    assert data["onboarding"]["dependency_plan"]["node"]["installed"] is True
    assert data["onboarding"]["answers"]["experience"] == "builder"

    clear = c.patch(
        "/api/preferences",
        json={
            "onboarding": {
                "dismissed_at": None,
                "connection_method": None,
                "dependency_plan": None,
                "current_step": None,
            }
        },
    )
    assert clear.status_code == 200
    assert clear.json()["onboarding"]["dismissed_at"] is None
    assert clear.json()["onboarding"]["connection_method"] is None
    assert clear.json()["onboarding"]["dependency_plan"] == {}
    assert clear.json()["onboarding"]["current_step"] == ""


def test_advanced_settings_roundtrip(tmp_db):
    app = make_app()
    c = TestClient(app)

    initial = c.get("/api/preferences")
    assert initial.status_code == 200
    assert initial.json()["advanced"]["model"]["temperature"] == 0.7
    assert initial.json()["advanced"]["tools"]["allow_shell"] is True
    assert initial.json()["advanced"]["runtime"]["default_mode"] == "auto"
    assert initial.json()["advanced"]["failover"]["enabled"] is True
    assert initial.json()["advanced"]["interface"]["animation_fidelity"] == "high"
    assert initial.json()["advanced"]["interface"]["animations_enabled"] is True
    assert initial.json()["advanced"]["interface"]["advanced_chat_physics"] is False

    patch_payload = {
        "advanced": {
            "model": {
                "temperature": 0.25,
                "reasoning_effort": "high",
                "deterministic_seed": 1234,
            },
            "tools": {
                "allow_shell": False,
                "allow_network": False,
                "allow_browser": False,
                "allow_channels": False,
                "tool_timeout_s": 45,
            },
            "memory": {
                "include_global_memory": False,
                "pins_only": True,
                "max_pack_tokens": 2400,
                "auto_compact_enabled": False,
            },
            "runtime": {
                "default_mode": "thinking",
                "default_token_economy": "cheap",
                "max_agent_iterations": 22,
                "quality_require_tests_for_code_edits": True,
            },
            "failover": {
                "enabled": False,
                "chat_auto_failover": True,
                "fallback_on_auth_error": True,
                "cooldown_seconds": 42,
            },
            "interface": {
                "ui_density": "dense",
                "event_log_verbosity": "verbose",
                "animation_fidelity": "minimal",
                "advanced_chat_physics": True,
            },
        }
    }
    updated = c.patch("/api/preferences", json=patch_payload)
    assert updated.status_code == 200
    data = updated.json()
    assert data["advanced"]["model"]["temperature"] == 0.25
    assert data["advanced"]["model"]["reasoning_effort"] == "high"
    assert data["advanced"]["model"]["deterministic_seed"] == 1234
    assert data["advanced"]["tools"]["allow_shell"] is False
    assert data["advanced"]["tools"]["allow_network"] is False
    assert data["advanced"]["tools"]["allow_browser"] is False
    assert data["advanced"]["tools"]["allow_channels"] is False
    assert data["advanced"]["tools"]["tool_timeout_s"] == 45
    assert data["advanced"]["memory"]["include_global_memory"] is False
    assert data["advanced"]["memory"]["pins_only"] is True
    assert data["advanced"]["memory"]["max_pack_tokens"] == 2400
    assert data["advanced"]["memory"]["auto_compact_enabled"] is False
    assert data["advanced"]["runtime"]["default_mode"] == "thinking"
    assert data["advanced"]["runtime"]["default_token_economy"] == "cheap"
    assert data["advanced"]["runtime"]["max_agent_iterations"] == 22
    assert data["advanced"]["runtime"]["quality_require_tests_for_code_edits"] is True
    assert data["advanced"]["failover"]["enabled"] is False
    assert data["advanced"]["failover"]["chat_auto_failover"] is True
    assert data["advanced"]["failover"]["fallback_on_auth_error"] is True
    assert data["advanced"]["failover"]["cooldown_seconds"] == 42
    assert data["advanced"]["interface"]["ui_density"] == "dense"
    assert data["advanced"]["interface"]["event_log_verbosity"] == "verbose"
    assert data["advanced"]["interface"]["animation_fidelity"] == "minimal"
    assert data["advanced"]["interface"]["animations_enabled"] is False
    assert data["advanced"]["interface"]["advanced_chat_physics"] is True

    cleared = c.patch("/api/preferences", json={"advanced": {"model": {"deterministic_seed": None}}})
    assert cleared.status_code == 200
    assert cleared.json()["advanced"]["model"]["deterministic_seed"] is None


def test_human_breakglass_toggle_requires_fresh_receipt(tmp_db, monkeypatch):
    store = PreferencesStore(db_path=os.environ["THOMAS_DB_PATH"])

    with pytest.raises(PermissionError):
        store.set_human_breakglass_enabled(True)

    monkeypatch.setattr(
        breakglass_auth,
        "consume_breakglass_toggle_receipt",
        lambda receipt: (
            breakglass_auth.BreakglassToggleReceipt(
                actor="WORKSTATION\\corbe",
                method=breakglass_auth.WINDOWS_CREDENTIAL_METHOD,
            )
            if receipt == "receipt-123"
            else None
        ),
    )

    updated = store.set_human_breakglass_enabled(
        True,
        authorization_receipt="receipt-123",
        changed_by="codex",
    )
    assert updated.advanced.security.human_breakglass_enabled is True
    assert updated.advanced.security.human_breakglass_changed_by == "WORKSTATION\\corbe"


def test_guardrails_allow_strengthening_but_block_weakening_on_generic_patch(tmp_db):
    app = make_app()
    c = TestClient(app)

    tightened = c.patch("/api/preferences", json={"advanced": {"tools": {"allow_shell": False}}})
    assert tightened.status_code == 200
    assert tightened.json()["advanced"]["tools"]["allow_shell"] is False

    blocked = c.patch("/api/preferences", json={"advanced": {"tools": {"require_command_approval": False}}})
    assert blocked.status_code == 400
    assert "guardrails-posture" in str(blocked.json()["detail"])

    runtime_blocked = c.patch(
        "/api/preferences",
        json={"advanced": {"runtime": {"quality_require_verification_for_coding": False}}},
    )
    assert runtime_blocked.status_code == 400
    assert "guardrails-posture" in str(runtime_blocked.json()["detail"])
