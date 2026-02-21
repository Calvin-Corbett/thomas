# tests/test_webhooks.py
import importlib
import json
import hmac
import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakePersistence:
    def __init__(self):
        self.goals = []

    def create_goal(self, goal_text: str, source: str, metadata: dict, goal_id: str):
        self.goals.append(
            {"id": goal_id, "text": goal_text, "source": source, "metadata": metadata}
        )
        return goal_id


def _hmac_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _stripe_sig(secret: str, body: bytes, ts: int) -> str:
    signed = (f"{ts}.".encode("utf-8") + body)
    v1 = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    return _build_webhooks_app(tmp_path, monkeypatch, admin_token="adm")


def _build_webhooks_app(tmp_path, monkeypatch, *, admin_token: str | None):
    monkeypatch.setenv("THOMAS_WEBHOOKS_FILE", str(tmp_path / "thomas_webhooks.json"))
    monkeypatch.setenv("THOMAS_WEBHOOK_RECEIPTS_FILE", str(tmp_path / "thomas_webhook_receipts.json"))
    monkeypatch.setenv("THOMAS_WEBHOOK_STATS_FILE", str(tmp_path / "thomas_webhook_stats.json"))
    monkeypatch.setenv("THOMAS_WEBHOOK_INBOX_FILE", str(tmp_path / "thomas_webhook_inbox.jsonl"))
    if admin_token is None:
        monkeypatch.delenv("THOMAS_WEBHOOK_ADMIN_TOKEN", raising=False)
    else:
        monkeypatch.setenv("THOMAS_WEBHOOK_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("THOMAS_WEBHOOK_STORE_RAW_PAYLOAD", "0")  # keep tests lean

    import thomas.server.routes.webhooks as webhooks_mod
    importlib.reload(webhooks_mod)

    fake_p = FakePersistence()
    monkeypatch.setattr(webhooks_mod, "get_persistence", lambda: fake_p)

    a = FastAPI()
    a.include_router(webhooks_mod.webhook_router)
    return a, fake_p, webhooks_mod, tmp_path


@pytest.fixture()
def app_without_admin_token(tmp_path, monkeypatch):
    return _build_webhooks_app(tmp_path, monkeypatch, admin_token=None)


def test_register_list_patch_get(app):
    a, _fake_p, _mod, _tmp = app
    c = TestClient(a)

    r = c.post("/webhooks/register", headers={"X-Admin-Token": "adm"}, json={"id": "abc", "goal_template": "Hi {payload.name}", "rate_limit_per_min": 10})
    assert r.status_code == 200

    r = c.get("/webhooks", headers={"X-Admin-Token": "adm"})
    assert r.status_code == 200
    assert r.json()[0]["rate_limit_per_min"] == 10

    r = c.patch("/webhooks/abc", headers={"X-Admin-Token": "adm"}, json={"goal_template": "Hello {payload.name} from {payload.org}"})
    assert r.status_code == 200

    r = c.get("/webhooks/abc", headers={"X-Admin-Token": "adm"})
    assert r.status_code == 200
    assert "Hello" in r.json()["goal_template"]


def test_template_dotpath_and_test_endpoint(app):
    a, fake_p, _mod, _tmp = app
    c = TestClient(a)

    c.post("/webhooks/register", headers={"X-Admin-Token": "adm"}, json={"id": "abc", "secret": "s3cr3t", "goal_template": "Lead {payload.name} email {payload.customer.email}"})

    payload = {"name": "Calvin", "customer": {"email": "c@example.com"}}
    r = c.post("/webhooks/test/abc", headers={"X-Admin-Token": "adm"}, json=payload)
    assert r.status_code == 200
    assert r.json()["signature"].startswith("sha256=")
    assert len(fake_p.goals) == 1
    assert "Lead Calvin email c@example.com" in fake_p.goals[0]["text"]


def test_receive_generic_signature_and_dedupe_and_inbox(app):
    a, fake_p, _mod, tmp = app
    c = TestClient(a)

    c.post("/webhooks/register", headers={"X-Admin-Token": "adm"}, json={"id": "abc", "secret": "s3cr3t", "goal_template": "X {payload.x}"})
    body = json.dumps({"x": 1}).encode("utf-8")
    sig = _hmac_hex("s3cr3t", body)

    r1 = c.post("/webhooks/receive/abc", data=body, headers={"content-type": "application/json", "X-Webhook-Signature": f"sha256={sig}", "X-Webhook-Delivery": "d1"})
    assert r1.status_code == 200
    gid = r1.json()["goal_id"]
    assert len(fake_p.goals) == 1

    r2 = c.post("/webhooks/receive/abc", data=body, headers={"content-type": "application/json", "X-Webhook-Signature": f"sha256={sig}", "X-Webhook-Delivery": "d1"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
    assert r2.json()["goal_id"] == gid
    assert len(fake_p.goals) == 1

    # inbox recent should show entries
    r = c.get("/webhooks/inbox/recent", headers={"X-Admin-Token": "adm"})
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_github_push_and_dedupe(app, monkeypatch):
    a, fake_p, _mod, _tmp = app
    c = TestClient(a)

    monkeypatch.setenv("THOMAS_GITHUB_WEBHOOK_SECRET", "ghsecret")

    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "owner/repo"},
        "commits": [{"message": "fix bug"}, {"message": "add feature"}],
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _hmac_hex("ghsecret", body)

    headers = {
        "content-type": "application/json",
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": f"sha256={sig}",
        "X-GitHub-Delivery": "delivery-1",
    }
    r1 = c.post("/webhooks/receive/github", data=body, headers=headers)
    assert r1.status_code == 200
    gid = r1.json()["goal_id"]
    assert len(fake_p.goals) == 1
    assert "owner/repo" in fake_p.goals[0]["text"]

    r2 = c.post("/webhooks/receive/github", data=body, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
    assert r2.json()["goal_id"] == gid
    assert len(fake_p.goals) == 1


def test_stripe_signature_optional_and_zero_decimal(app, monkeypatch):
    a, fake_p, mod, _tmp = app
    c = TestClient(a)

    monkeypatch.setenv("THOMAS_STRIPE_WEBHOOK_SECRET", "sk_test")
    importlib.reload(mod)
    monkeypatch.setattr(mod, "get_persistence", lambda: fake_p)
    monkeypatch.setattr(mod, "_unix_now", lambda: 1700000000)

    payload = {
        "id": "evt_123",
        "type": "payment_intent.succeeded",
        "data": {"object": {"amount_received": 500, "currency": "jpy", "customer": "cus_123"}},
    }
    body = json.dumps(payload).encode("utf-8")
    stripe_sig = _stripe_sig("sk_test", body, 1700000000)

    r = c.post("/webhooks/receive/stripe", data=body, headers={"content-type": "application/json", "Stripe-Signature": stripe_sig})
    assert r.status_code == 200
    assert len(fake_p.goals) == 1
    assert "500 JPY" in fake_p.goals[0]["text"]


def test_inbox_retry_generic(app):
    a, fake_p, _mod, _tmp = app
    c = TestClient(a)

    c.post("/webhooks/register", headers={"X-Admin-Token": "adm"}, json={"id": "abc", "goal_template": "Y {payload.y}"})
    r = c.post("/webhooks/receive/abc", json={"y": 2})
    assert r.status_code == 200
    assert len(fake_p.goals) == 1

    inbox = c.get("/webhooks/inbox/recent", headers={"X-Admin-Token": "adm"}).json()
    event_id = inbox[-1]["event_id"]

    r2 = c.post(f"/webhooks/inbox/retry/{event_id}", headers={"X-Admin-Token": "adm"})
    assert r2.status_code == 200
    assert len(fake_p.goals) == 2


def test_management_routes_fail_closed_without_admin_token(app_without_admin_token):
    a, _fake_p, _mod, _tmp = app_without_admin_token
    c = TestClient(a)

    r = c.get("/webhooks")
    assert r.status_code == 503
    assert "THOMAS_WEBHOOK_ADMIN_TOKEN" in r.json()["detail"]
