import json

import pytest

from thomas.marketplace.nodes.p040_nodes_notify_action import (
    NodeNotifyResult,
    NodesNotifyActionConfigError,
    NodesNotifyActionInput,
    NodesNotifyActionInvalidInputError,
    notify_action,
    parse_input,
    payload_from_json,
)


class FakeNotifier:
    def __init__(self, *, fail_node: str | None = None, raise_node: str | None = None):
        self.fail_node = fail_node
        self.raise_node = raise_node
        self.calls: list[tuple[str, str]] = []

    async def notify(self, *, node_id: str, action: str, payload, timeout_s: float):
        self.calls.append((node_id, action))
        if self.raise_node == node_id:
            raise RuntimeError("boom")
        if self.fail_node == node_id:
            return NodeNotifyResult(
                node_id=node_id,
                ok=False,
                status=503,
                error_code="remote_error",
                error_message="service unavailable",
            )
        return NodeNotifyResult(node_id=node_id, ok=True, status=204)


def test_notify_action_success_sync_wrapper():
    notifier = FakeNotifier()
    out = notify_action(
        NodesNotifyActionInput(node_ids=["n-1", "n-2"], action="ping", payload={"k": "v"}, timeout_s=1.0),
        notifier=notifier,
    )

    assert out.ok is True
    assert [r.node_id for r in out.results] == ["n-1", "n-2"]
    assert notifier.calls == [("n-1", "ping"), ("n-2", "ping")]

    data = out.to_json_dict()
    assert data["ok"] is True
    assert data["action"] == "ping"
    assert [r["node_id"] for r in data["results"]] == ["n-1", "n-2"]


def test_notify_action_invalid_input_empty_nodes():
    with pytest.raises(NodesNotifyActionInvalidInputError) as ei:
        parse_input({"node_ids": [], "action": "ping"})
    assert ei.value.code == "invalid_input"


def test_notify_action_invalid_payload_string():
    with pytest.raises(NodesNotifyActionInvalidInputError):
        parse_input({"node_ids": ["n-1"], "action": "ping", "payload": "nope"})


def test_payload_from_json_requires_object():
    with pytest.raises(NodesNotifyActionInvalidInputError):
        payload_from_json('["not", "an", "object"]')


def test_notify_action_partial_failure_marks_overall_not_ok():
    notifier = FakeNotifier(fail_node="n-2")
    out = notify_action(
        NodesNotifyActionInput(node_ids=["n-1", "n-2"], action="ping"),
        notifier=notifier,
    )

    assert out.ok is False
    assert [r.ok for r in out.results] == [True, False]
    assert out.results[1].error_code == "remote_error"


def test_notify_action_notifier_exception_is_deterministic_result():
    notifier = FakeNotifier(raise_node="n-2")
    out = notify_action(
        NodesNotifyActionInput(node_ids=["n-1", "n-2"], action="ping"),
        notifier=notifier,
    )
    assert out.ok is False
    assert out.results[1].ok is False
    assert out.results[1].error_code == "notifier_exception"


def test_cli_json_success(monkeypatch, capsys):
    # Import inside the test so monkeypatching affects the module-level import.
    from thomas.cli.commands.nodes import p040_nodes_notify_action as cli
    from thomas.marketplace.nodes.p040_nodes_notify_action import NodesNotifyActionOutput

    def fake_notify_action(inp, *, notifier=None, config=None):
        return NodesNotifyActionOutput(
            ok=True,
            action=inp.action,
            results=[NodeNotifyResult(node_id=nid, ok=True, status=200) for nid in inp.node_ids],
        )

    monkeypatch.setattr(cli, "notify_action", fake_notify_action)

    exit_code = cli.main(["notify-action", "--node", "n-1", "--action", "ping", "--json"])
    assert exit_code == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["action"] == "ping"
    assert payload["results"][0]["node_id"] == "n-1"


def test_cli_json_invalid_input(capsys):
    from thomas.cli.commands.nodes import p040_nodes_notify_action as cli

    # No monkeypatch needed: invalid input is caught before any config/network.
    exit_code = cli.main(["notify-action", "--node", " ", "--action", "ping", "--json"])
    assert exit_code == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"


def test_cli_json_missing_config(monkeypatch, capsys):
    from thomas.cli.commands.nodes import p040_nodes_notify_action as cli

    def fake_notify_action(*args, **kwargs):
        raise NodesNotifyActionConfigError("no config")

    monkeypatch.setattr(cli, "notify_action", fake_notify_action)

    exit_code = cli.main(["notify-action", "--node", "n-1", "--action", "ping", "--json"])
    assert exit_code == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"
