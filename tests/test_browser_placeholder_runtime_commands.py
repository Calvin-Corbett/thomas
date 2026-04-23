from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from thomas.cli.commands.browser import (
    p002_browser_action_navigate_and_open as p002,
)
from thomas.cli.commands.browser import (
    p027_browser_action_evaluate_script as p027,
)
from thomas.cli.commands.browser import (
    p031_browser_network_set_offline as p031,
)
from thomas.cli.commands.browser import (
    p033_browser_permissions_grant as p033,
)
from thomas.cli.commands.browser import (
    p034_browser_permissions_revoke as p034,
)
from thomas.cli.commands.browser import (
    p035_browser_artifact_har_export as p035,
)


class _FakeContext:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.offline: bool = False
        self.clears: int = 0
        self.grants: list[tuple[list[str], str]] = []

    async def set_extra_http_headers(self, headers: dict[str, str]) -> None:
        self.headers = dict(headers)

    async def set_offline(self, offline: bool) -> None:
        self.offline = bool(offline)

    async def clear_permissions(self) -> None:
        self.clears += 1

    async def grant_permissions(self, permissions: list[str], origin: str | None = None) -> None:
        self.grants.append((list(permissions), str(origin or "")))


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com/"
        self.viewport: dict[str, int] | None = None

    async def evaluate(self, script: str, arg: object | None = None) -> dict[str, object]:
        return {"script": script, "arg": arg}

    async def set_viewport_size(self, viewport: dict[str, int]) -> None:
        self.viewport = dict(viewport)

    async def title(self) -> str:
        return "Example Domain"


def _install_fake_browser_runtime(monkeypatch) -> tuple[types.SimpleNamespace, types.SimpleNamespace]:
    context = _FakeContext()
    page = _FakePage()
    session = types.SimpleNamespace(context=context, page=page)
    state = types.SimpleNamespace(active_session="default", sessions={"default": session})

    async def _ensure_session_page(session_name: str):
        selected = str(session_name or "").strip() or "default"
        if selected not in state.sessions:
            state.sessions[selected] = types.SimpleNamespace(context=context, page=page)
        return state.sessions[selected], state.sessions[selected].page

    runtime = types.SimpleNamespace(_STATE=state, _ensure_session_page=_ensure_session_page)
    monkeypatch.setitem(sys.modules, "thomas.tools.browser", runtime)
    return runtime, session


def test_p027_evaluate_script_executes_runtime_and_emits_json(monkeypatch, capsys) -> None:
    _install_fake_browser_runtime(monkeypatch)

    rc = p027.main(["--script", "1 + 1", "--arg", '{"k":"v"}', "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["result"]["script"] == "1 + 1"
    assert payload["result"]["arg"] == {"k": "v"}


def test_p002_missing_url_returns_structured_json_error(capsys) -> None:
    rc = p002.main(["--json"])

    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "browser.navigate_open.invalid_input"


def test_p031_offline_returns_structured_error_when_context_method_missing(monkeypatch, capsys) -> None:
    page = _FakePage()
    context = types.SimpleNamespace()
    session = types.SimpleNamespace(context=context, page=page)
    state = types.SimpleNamespace(active_session="default", sessions={"default": session})

    async def _ensure_session_page(session_name: str):
        return session, page

    runtime = types.SimpleNamespace(_STATE=state, _ensure_session_page=_ensure_session_page)
    monkeypatch.setitem(sys.modules, "thomas.tools.browser", runtime)

    rc = p031.main(["--json"])

    assert rc == 4
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["category"] == "not_supported"
    assert payload["error"]["code"] == "browser_context_offline_unsupported"


def test_p033_p034_permissions_grant_then_revoke_updates_runtime(monkeypatch, capsys) -> None:
    runtime, _session = _install_fake_browser_runtime(monkeypatch)

    rc_grant = p033.main(["notifications", "--origin", "https://example.com", "--json"])
    payload_grant = json.loads(capsys.readouterr().out)
    assert rc_grant == 0
    assert payload_grant["ok"] is True
    assert payload_grant["tracked_permissions"]["https://example.com"] == ["notifications"]

    rc_revoke = p034.main(["notifications", "--origin", "https://example.com", "--json"])
    payload_revoke = json.loads(capsys.readouterr().out)
    assert rc_revoke == 0
    assert payload_revoke["ok"] is True
    assert payload_revoke["tracked_permissions"] == {}

    context = runtime._STATE.sessions["default"].context
    assert context.clears == 1


def test_p035_har_export_writes_artifact(monkeypatch, capsys, tmp_path: Path) -> None:
    _runtime, session = _install_fake_browser_runtime(monkeypatch)
    session._thomas_user_agent = "ThomasTest/1.0"
    session._thomas_network_profile = {"profile": "wifi", "offline": False}

    out_path = tmp_path / "capture.har"
    rc = p035.main(["--out", str(out_path), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert Path(payload["artifact_path"]).exists()

    har_payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert har_payload["log"]["version"] == "1.2"
    assert har_payload["_thomas"]["user_agent"] == "ThomasTest/1.0"
    assert har_payload["_thomas"]["session"] == "default"
