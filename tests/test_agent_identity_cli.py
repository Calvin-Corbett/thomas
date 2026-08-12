from __future__ import annotations

import json

from scripts.crew.brief import identity as mod


def _clear_identity_env(monkeypatch) -> None:
    for key in (*mod.AGENT_ID_ENV_KEYS, *mod.AGENT_NAME_ENV_KEYS):
        monkeypatch.delenv(key, raising=False)


def test_resolve_agent_source_prefers_explicit_agent(monkeypatch) -> None:
    _clear_identity_env(monkeypatch)
    monkeypatch.setenv("THOMAS_AGENT_ID", "Env Agent")

    assert mod.resolve_agent_source(" Explicit Agent ") == ("Explicit Agent", "explicit")
    assert mod.resolve_agent(" Explicit Agent ") == "Explicit Agent"


def test_resolve_agent_source_reports_env_key(monkeypatch) -> None:
    _clear_identity_env(monkeypatch)
    monkeypatch.setenv("AGENT_ID", "Codex Env")

    assert mod.resolve_agent_source(None) == ("Codex Env", "AGENT_ID")
    assert mod.identity_with_env(None) == {"agent": "Codex Env", "source": "AGENT_ID"}


def test_cli_prints_explicit_agent(capsys, monkeypatch) -> None:
    _clear_identity_env(monkeypatch)

    rc = mod.main(["--agent", "codex-upgrade-worker-6"])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() == "codex-upgrade-worker-6"
    assert captured.err == ""


def test_cli_json_reports_name_fallback_source(capsys, monkeypatch) -> None:
    _clear_identity_env(monkeypatch)
    monkeypatch.setenv("THOMAS_AGENT_NAME", "Codex Worker")

    rc = mod.main(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload == {"ok": True, "agent": "Codex Worker", "source": "THOMAS_AGENT_NAME"}


def test_cli_fails_closed_without_identity(capsys, monkeypatch) -> None:
    _clear_identity_env(monkeypatch)

    rc = mod.main([])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "agent identity unavailable" in captured.err
    assert "THOMAS_AGENT_ID" in captured.err
