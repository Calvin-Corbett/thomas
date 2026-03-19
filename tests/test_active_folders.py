from __future__ import annotations

import argparse
import json

import pytest
import scripts.active_folders as mod


@pytest.fixture(autouse=True)
def _presence_gate_ok(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_presence_gate", lambda **_: (True, ""))


def _guard_args(**overrides) -> argparse.Namespace:
    base: dict[str, object] = {
        "agent": None,
        "exclude": [],
        "no_ignore_self": False,
        "require_explicit_agent": False,
        "auto_claim_staged": True,
        "auto_claim_ttl": 900,
        "auto_claim_note": "auto-claim-test",
        "replace_agent": True,
        "json": True,
        "allow_presence_override": False,
        "presence_override_reason": "",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_guard_staged_auto_claim_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_staged_paths", lambda _exclude: ["thomas/server/routes"])
    monkeypatch.setattr(mod, "_resolve_agent", lambda _agent: "codex-auto")
    monkeypatch.setattr(mod, "_require_explicit_agent", lambda _agent: (None, "fallback"))

    captured: dict[str, object] = {}

    def _fake_create_claim(**kwargs):
        captured.update(kwargs)
        return {"claim_id": "claim-1"}, []

    monkeypatch.setattr(mod, "_create_claim", _fake_create_claim)
    monkeypatch.setattr(mod, "_find_conflicts", lambda _paths, ignore_agent=None: [])

    rc = mod._guard_staged(_guard_args())
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["agent_id"] == "codex-auto"
    assert payload["ignore_agent"] == "codex-auto"
    assert payload["auto_claim"]["enabled"] is True
    assert payload["auto_claim"]["created"] is True
    assert payload["auto_claim"]["claim_id"] == "claim-1"
    assert captured["agent"] == "codex-auto"
    assert captured["paths"] == ["thomas/server/routes"]
    assert captured["ttl_seconds"] == 900
    assert captured["replace_agent"] is True
    assert captured["allow_conflicts"] is False


def test_guard_staged_auto_claim_blocks_on_conflict(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_staged_paths", lambda _exclude: ["thomas/server/routes"])
    monkeypatch.setattr(mod, "_resolve_agent", lambda _agent: "codex-auto")
    monkeypatch.setattr(mod, "_require_explicit_agent", lambda _agent: (None, "fallback"))

    conflict = [
        {
            "agent_id": "other-agent",
            "claim_id": "claim-x",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "note": "other lane",
            "overlaps": [{"wanted": "thomas/server/routes", "active": "thomas/server"}],
        }
    ]
    monkeypatch.setattr(mod, "_create_claim", lambda **_kwargs: (None, conflict))
    monkeypatch.setattr(mod, "_find_conflicts", lambda _paths, ignore_agent=None: [])

    rc = mod._guard_staged(_guard_args())
    payload = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert payload["ok"] is False
    assert payload["agent_id"] == "codex-auto"
    assert payload["auto_claim"]["enabled"] is True
    assert payload["auto_claim"]["created"] is False
    assert payload["auto_claim"]["error"] == "folder_conflicts"
    assert len(payload["conflicts"]) == 1
    assert payload["conflicts"][0]["agent_id"] == "other-agent"


def test_guard_staged_respects_require_explicit_agent(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_staged_paths", lambda _exclude: ["thomas/server/routes"])
    monkeypatch.setattr(mod, "_resolve_agent", lambda _agent: "codex-auto")
    monkeypatch.setattr(mod, "_require_explicit_agent", lambda _agent: (None, "fallback"))

    rc = mod._guard_staged(
        _guard_args(
            require_explicit_agent=True,
            auto_claim_staged=False,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert payload["ok"] is False
    assert "explicit agent id required" in payload["error"]


def test_claim_presence_gate_requires_override(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_resolve_agent", lambda _agent: "codex-auto")
    monkeypatch.setattr(mod, "_presence_gate", lambda **_: (False, "presence gate requires override"))

    rc = mod._claim(
        argparse.Namespace(
            agent=None,
            path=["thomas/server/routes"],
            ttl=60,
            note="",
            replace_agent=True,
            allow_conflicts=False,
            json=True,
            allow_presence_override=False,
            presence_override_reason="",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert payload["ok"] is False
    assert payload["error"] == "presence gate requires override"
