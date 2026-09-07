from __future__ import annotations

import argparse
import json

import pytest
import scripts.active_folders as mod


@pytest.fixture(autouse=True)
def _presence_gate_ok(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_presence_gate", lambda **_: (True, ""))


@pytest.fixture(autouse=True)
def _clear_agent_env(monkeypatch) -> None:
    # GitHub Actions sets AGENT_ID at runner boot (and Claude/Codex/Gemini
    # surfaces set their own *_AGENT_ID vars). The tests assert behavior
    # when the caller does NOT have an explicit agent set — so unset every
    # env key `_explicit_agent_from_env` looks at. Otherwise the runner's
    # AGENT_ID leaks into the test and the explicit-agent-required branch
    # never triggers (only fails on Linux CI, never locally on Windows).
    for env_key in mod.AGENT_ENV_KEYS:
        monkeypatch.delenv(env_key, raising=False)


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


def _claim_args(**overrides) -> argparse.Namespace:
    base: dict[str, object] = {
        "agent": "codex-auto",
        "path": ["thomas/server/routes"],
        "ttl": 60,
        "note": "",
        "replace_agent": True,
        "allow_conflicts": False,
        "json": True,
        "allow_presence_override": False,
        "presence_override_reason": "",
        "require_explicit_agent": True,
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
            require_explicit_agent=False,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert payload["ok"] is False
    assert payload["error"] == "presence gate requires override"


def test_presence_gate_blocks_unread_inbox(monkeypatch) -> None:
    monkeypatch.undo()
    monkeypatch.setattr(
        mod.agent_presence,
        "evaluate_soft_gate",
        lambda **_kwargs: {"ok": True, "warnings": []},
    )
    monkeypatch.setattr(
        mod,
        "_workboard_inbox_gate",
        lambda _agent: (False, "unread workboard messages for `codex` must be acked"),
    )

    ok, message = mod._presence_gate(
        purpose="active_folders_guard_staged",
        agent="codex",
        paths=["scripts"],
        allow_override=False,
        override_reason="",
    )

    assert ok is False
    assert "unread workboard messages" in message


def test_claim_requires_explicit_agent_for_coordinated_claims(capsys) -> None:
    rc = mod._claim(_claim_args(agent=None))
    payload = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert payload["ok"] is False
    assert "explicit agent id required" in payload["error"]


def test_claim_syncs_workboard_and_session(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_claiming_agent", lambda _agent, require_explicit: ("codex-auto", "--agent"))
    monkeypatch.setattr(mod, "_ensure_session", lambda *args, **kwargs: {"session_id": "sess-1"})
    monkeypatch.setattr(mod, "_create_claim", lambda **kwargs: ({"claim_id": "claim-1"}, []))
    monkeypatch.setattr(mod, "_sync_workboard_claim", lambda **kwargs: (True, "ok"))

    heartbeat_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        mod.agent_presence,
        "heartbeat_session",
        lambda **kwargs: heartbeat_calls.append(kwargs) or {"session_id": "sess-1"},
    )

    rc = mod._claim(_claim_args())
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["workboard_synced"] is True
    assert payload["agent_source"] == "--agent"
    assert heartbeat_calls


def test_claim_releases_folder_claim_when_workboard_sync_fails(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_claiming_agent", lambda _agent, require_explicit: ("codex-auto", "--agent"))
    monkeypatch.setattr(mod, "_ensure_session", lambda *args, **kwargs: {"session_id": "sess-1"})
    monkeypatch.setattr(mod, "_create_claim", lambda **kwargs: ({"claim_id": "claim-1"}, []))
    monkeypatch.setattr(mod, "_sync_workboard_claim", lambda **kwargs: (False, "workboard failed"))

    released: list[tuple[str | None, str | None]] = []
    monkeypatch.setattr(mod, "_release_claim", lambda claim_id, agent=None: released.append((claim_id, agent)) or 1)

    rc = mod._claim(_claim_args())
    payload = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert payload["ok"] is False
    assert payload["error"] == "workboard failed"
    assert released == [("claim-1", None)]


# --- coordination threads must only open with someone who can reply -----------


def test_only_addressable_agents_get_coordination_threads() -> None:
    """Presence reports agents and raw OS processes under one field.

    A named agent can run `message.py --ack`. `process:41196` cannot -- nothing
    behind a PID has a workboard identity. Opening a thread with one produced a
    p1 message that stayed open forever, and because the dedup keys on the PAIR,
    every new PID minted a fresh permanent thread. 254 of 303 open messages ended
    up un-ackable, which buried the real ones.
    """
    from scripts.active_folders import _is_addressable_agent

    for identity in ("claude", "codex-auto", "claude-repair", "Codex 1"):
        assert _is_addressable_agent(identity) is True, identity

    for identity in (
        "process:41196",
        "process:7668",
        "pid:900",
        "PID:900",
        "unregistered-worktree",
        "Unregistered-Thing",
        "",
        "   ",
    ):
        assert _is_addressable_agent(identity) is False, identity


def test_presence_only_peers_do_not_create_messages(tmp_path, monkeypatch) -> None:
    """A presence warning naming a PID must notify nobody."""
    import scripts.active_folders as af

    sent: list[str] = []

    class _FakeTool:
        @staticmethod
        def list_messages(path, state=None):
            return True, {"messages": []}

        @staticmethod
        def send_message(path, **kwargs):
            sent.append(str(kwargs.get("recipient")))
            return True, {}

    workboard = tmp_path / "WORKBOARD.md"
    workboard.write_text("# Thomas Workboard\n", encoding="utf-8")
    monkeypatch.setattr(af, "workboard_message_tool", _FakeTool)
    monkeypatch.setattr(af, "_find_conflicts", lambda paths, ignore_agent=None: [])

    notified = af._notify_overlap_coordination(
        "claude",
        ["thomas/core/config.py"],
        presence_warnings=[
            {"agent_id": "process:41196", "message": "Unregistered activity detected"},
            {"agent_id": "unregistered-worktree", "message": "Unregistered worktree"},
        ],
        workboard_path=workboard,
    )

    assert notified == [], notified
    assert sent == [], sent


def test_a_real_agent_peer_still_gets_a_thread(tmp_path, monkeypatch) -> None:
    """The narrowing must not silence genuine agent-to-agent coordination."""
    import scripts.active_folders as af

    sent: list[str] = []

    class _FakeTool:
        @staticmethod
        def list_messages(path, state=None):
            return True, {"messages": []}

        @staticmethod
        def send_message(path, **kwargs):
            sent.append(str(kwargs.get("recipient")))
            return True, {}

    workboard = tmp_path / "WORKBOARD.md"
    workboard.write_text("# Thomas Workboard\n", encoding="utf-8")
    monkeypatch.setattr(af, "workboard_message_tool", _FakeTool)
    monkeypatch.setattr(af, "_find_conflicts", lambda paths, ignore_agent=None: [])

    notified = af._notify_overlap_coordination(
        "claude",
        ["thomas/core/config.py"],
        presence_warnings=[{"agent_id": "codex-auto", "message": "active in this repo"}],
        workboard_path=workboard,
    )

    assert notified == ["codex-auto"], notified
    assert sent == ["codex-auto"], sent
