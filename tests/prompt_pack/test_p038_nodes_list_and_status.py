import argparse
import contextlib
import json
import socket
import threading

import pytest

from thomas.nodes.p038_nodes_list_and_status import (
    NodesConfigError,
    NodesExternalFailureError,
    NodesInvalidInputError,
    NodesListAndStatusRequest,
    list_nodes_and_status,
)


@contextlib.contextmanager
def tcp_server(host: str = "127.0.0.1"):
    """Start a tiny TCP server in a background thread.

    The status probe uses asyncio.open_connection(); a successful TCP accept is enough.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, 0))
    sock.listen(5)
    port = sock.getsockname()[1]

    stop = threading.Event()

    def _loop():
        sock.settimeout(0.1)
        while not stop.is_set():
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            else:
                try:
                    conn.close()
                except OSError:
                    pass
        try:
            sock.close()
        except OSError:
            pass

    t = threading.Thread(target=_loop, daemon=True)
    t.start()

    try:
        yield port
    finally:
        stop.set()
        # Unblock accept quickly.
        try:
            with socket.create_connection((host, port), timeout=0.2):
                pass
        except OSError:
            pass
        t.join(timeout=1)


def _allocate_unused_local_port(host: str = "127.0.0.1") -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((host, 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _clear_config_env(monkeypatch):
    for var in ("THOMAS_CONFIG", "THOMAS_CONFIG_PATH", "THOMAS_SETTINGS"):
        monkeypatch.delenv(var, raising=False)


def test_nodes_list_and_status_success_mixed_online_offline(monkeypatch):
    _clear_config_env(monkeypatch)

    with tcp_server() as port_online:
        port_offline = _allocate_unused_local_port()
        assert port_offline != port_online

        config = {
            "nodes": [
                {"id": "node-a", "url": f"http://127.0.0.1:{port_online}"},
                {"id": "node-b", "url": f"http://127.0.0.1:{port_offline}"},
            ]
        }

        req = NodesListAndStatusRequest(timeout_s=0.25, max_concurrency=5, strict=False)
        resp = list_nodes_and_status(req, config=config)

        assert [n.node_id for n in resp.nodes] == ["node-a", "node-b"]
        by_id = {n.node_id: n for n in resp.nodes}
        assert by_id["node-a"].online is True
        assert by_id["node-b"].online is False
        assert resp.online_count == 1
        assert resp.offline_count == 1


def test_nodes_list_and_status_supports_mapping_form(monkeypatch):
    _clear_config_env(monkeypatch)

    with tcp_server() as port_online:
        config = {
            "nodes": {
                "node-a": f"http://127.0.0.1:{port_online}",
            }
        }

        resp = list_nodes_and_status(NodesListAndStatusRequest(timeout_s=0.25), config=config)
        assert resp.online_count == 1
        assert resp.nodes[0].node_id == "node-a"
        assert resp.nodes[0].online is True


def test_nodes_list_and_status_loads_from_env_config_path(tmp_path, monkeypatch):
    _clear_config_env(monkeypatch)

    with tcp_server() as port_online:
        cfg_path = tmp_path / "thomas.json"
        cfg_path.write_text(
            json.dumps({"nodes": [{"id": "node-a", "url": f"http://127.0.0.1:{port_online}"}]}),
            encoding="utf-8",
        )
        monkeypatch.setenv("THOMAS_CONFIG", str(cfg_path))

        resp = list_nodes_and_status(NodesListAndStatusRequest(timeout_s=0.25), config=None)
        assert resp.online_count == 1
        assert resp.nodes[0].node_id == "node-a"
        assert resp.nodes[0].online is True


def test_nodes_list_and_status_missing_config_raises(monkeypatch):
    _clear_config_env(monkeypatch)

    req = NodesListAndStatusRequest(timeout_s=0.1)
    with pytest.raises(NodesConfigError) as ei:
        list_nodes_and_status(req, config=None)
    assert ei.value.code == "missing_config"


def test_nodes_list_and_status_invalid_node_entry_raises(monkeypatch):
    _clear_config_env(monkeypatch)

    config = {"nodes": [{"url": "http://127.0.0.1:1"}]}
    with pytest.raises(NodesInvalidInputError) as ei:
        list_nodes_and_status(NodesListAndStatusRequest(), config=config)
    assert ei.value.code == "invalid_input"


def test_nodes_list_and_status_invalid_address_port_raises(monkeypatch):
    _clear_config_env(monkeypatch)

    config = {"nodes": [{"id": "node-a", "url": "http://127.0.0.1:notaport"}]}
    with pytest.raises(NodesInvalidInputError) as ei:
        list_nodes_and_status(NodesListAndStatusRequest(), config=config)
    assert ei.value.code == "invalid_input"


def test_nodes_list_and_status_strict_mode_raises_external_failure(monkeypatch):
    _clear_config_env(monkeypatch)

    offline_port = _allocate_unused_local_port()
    config = {"nodes": [{"id": "node-off", "url": f"http://127.0.0.1:{offline_port}"}]}

    with pytest.raises(NodesExternalFailureError) as ei:
        list_nodes_and_status(NodesListAndStatusRequest(timeout_s=0.1, strict=True), config=config)

    assert ei.value.code == "external_failure"
    assert ei.value.details and "offline_nodes" in ei.value.details


def test_cli_registers_nodes_list_subcommand():
    from thomas.cli.commands.nodes import p038_nodes_list_and_status as cli_mod

    parser = argparse.ArgumentParser(prog="thomas")
    root_subparsers = parser.add_subparsers(dest="cmd")

    cli_mod.register(root_subparsers)

    assert "nodes" in root_subparsers.choices

    nodes_parser = root_subparsers.choices["nodes"]
    nodes_subparsers = None
    for action in nodes_parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            nodes_subparsers = action
            break
    assert nodes_subparsers is not None
    assert "list" in nodes_subparsers.choices


def test_cli_json_output(capsys):
    from thomas.cli.commands.nodes import p038_nodes_list_and_status as cli_mod

    with tcp_server() as port_online:
        config = {"nodes": [{"id": "node-a", "url": f"http://127.0.0.1:{port_online}"}]}

        parser = argparse.ArgumentParser(prog="thomas")
        root_subparsers = parser.add_subparsers(dest="cmd")
        cli_mod.register(root_subparsers)

        args = parser.parse_args(["nodes", "list", "--timeout", "0.25", "--json"])
        args.thomas_config = config

        exit_code = args.func(args)
        assert exit_code == 0

        out = capsys.readouterr().out.strip()
        payload = json.loads(out)

        assert payload["ok"] is True
        assert payload["result"]["nodes"][0]["id"] == "node-a"
        assert payload["result"]["nodes"][0]["online"] is True
