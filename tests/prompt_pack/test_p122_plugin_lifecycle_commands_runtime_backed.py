from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

from thomas.plugins import p122_plugin_lifecycle_commands_runtime_backed as plc


class _GatewayHandler(BaseHTTPRequestHandler):
    state: dict[str, dict[str, Any]] = {}

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/plugins":
            plugins = [{"name": name, "status": meta.get("status", "unknown")} for name, meta in sorted(self.state.items())]
            self._send_json(200, {"plugins": plugins})
            return

        if self.path.startswith("/plugins/"):
            name = self.path.split("/")[2]
            plugin = self.state.get(name)
            if not plugin:
                self._send_json(404, {"error": {"message": f"Plugin not found: {name}"}})
                return
            self._send_json(200, {"name": name, "status": plugin.get("status", "unknown")})
            return

        self._send_json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        parts = [p for p in self.path.split("/") if p]
        if len(parts) == 3 and parts[0] == "plugins":
            name, action = parts[1], parts[2]
            plugin = self.state.get(name)
            if not plugin:
                self._send_json(404, {"error": {"message": f"Plugin not found: {name}"}})
                return
            if action in {"start", "restart"}:
                plugin["status"] = "running"
            elif action == "stop":
                plugin["status"] = "stopped"
            else:
                self._send_json(404, {"error": {"message": "not found"}})
                return
            self._send_json(200, {"name": name, "status": plugin["status"]})
            return

        self._send_json(404, {"error": {"message": "not found"}})


@contextmanager
def _run_gateway(initial: dict[str, str]) -> Iterator[str]:
    _GatewayHandler.state = {name: {"status": status} for name, status in initial.items()}

    server = ThreadingHTTPServer(("127.0.0.1", 0), _GatewayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    try:
        yield base_url
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_list_plugins_success() -> None:
    with _run_gateway({"alpha": "running", "bravo": "stopped"}) as url:
        result = plc.list_plugins(gateway_url=url)
        assert result.ok is True
        assert result.action == "list"
        assert {p.name: p.status for p in result.plugins} == {"alpha": "running", "bravo": "stopped"}


def test_start_stop_restart_success() -> None:
    with _run_gateway({"alpha": "stopped"}) as url:
        started = plc.start_plugin("alpha", gateway_url=url)
        assert started.ok is True
        assert started.plugin_state is not None
        assert started.plugin_state.status == "running"

        stopped = plc.stop_plugin("alpha", gateway_url=url)
        assert stopped.ok is True
        assert stopped.plugin_state is not None
        assert stopped.plugin_state.status == "stopped"

        restarted = plc.restart_plugin("alpha", gateway_url=url)
        assert restarted.ok is True
        assert restarted.plugin_state is not None
        assert restarted.plugin_state.status == "running"


def test_plugin_not_found_is_deterministic() -> None:
    with _run_gateway({"alpha": "running"}) as url:
        with pytest.raises(plc.PluginNotFound) as exc:
            plc.plugin_status("missing", gateway_url=url)
        assert exc.value.code == "plugin_not_found"


def test_invalid_plugin_id_is_deterministic() -> None:
    with pytest.raises(plc.InvalidPluginLifecycleRequest) as exc:
        plc.plugin_status("bad plugin", gateway_url="http://example.com")
    assert exc.value.code == "invalid_request"


def test_missing_config_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("THOMAS_GATEWAY_URL", "THOMAS_RUNTIME_URL", "THOMAS_API_URL", "THOMAS_URL"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(plc.MissingPluginRuntimeConfig) as exc:
        plc.list_plugins()
    assert exc.value.code == "missing_runtime_config"


def test_config_file_gateway_url_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_GATEWAY_URL", raising=False)

    with _run_gateway({"alpha": "running"}) as url:
        cfg = tmp_path / "thomas.json"
        cfg.write_text(json.dumps({"gateway_url": url}), encoding="utf-8")

        result = plc.list_plugins(config_path=cfg)
        assert result.ok is True
        assert {p.name for p in result.plugins} == {"alpha"}


def test_cli_json_output_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_GATEWAY_URL", raising=False)

    with _run_gateway({"alpha": "running"}) as url:
        from typer.testing import CliRunner
        from thomas.cli.commands.plugins import p122_plugin_lifecycle_commands_runtime_backed as cli

        runner = CliRunner()
        app = cli.get_typer_app()
        result = runner.invoke(app, ["list", "--gateway-url", url, "--json"])
        assert result.exit_code == 0, result.stdout

        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["action"] == "list"
        assert {p["name"] for p in payload["plugins"]} == {"alpha"}


def test_cli_missing_config_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_GATEWAY_URL", raising=False)

    from typer.testing import CliRunner
    from thomas.cli.commands.plugins import p122_plugin_lifecycle_commands_runtime_backed as cli

    runner = CliRunner()
    app = cli.get_typer_app()
    result = runner.invoke(app, ["list", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_runtime_config"
