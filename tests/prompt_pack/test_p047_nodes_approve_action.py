from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from thomas.cli.commands.nodes import p047_nodes_approve_action as cli
from thomas.nodes.p047_nodes_approve_action import (
    DEFAULT_APPROVALS_ENV_VAR,
    DEFAULT_LEDGER_FILENAME,
    NodesApproveActionConfigError,
    NodesApproveActionExternalError,
    NodesApproveActionInputError,
    NodesApproveActionRequest,
    approve_action,
    approve_action_from_payload,
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DEFAULT_APPROVALS_ENV_VAR, raising=False)
    monkeypatch.delenv("THOMAS_STATE_DIR", raising=False)
    monkeypatch.delenv("THOMAS_STATE_PATH", raising=False)
    monkeypatch.delenv("THOMAS_HOME", raising=False)


def test_approve_action_success_writes_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "approvals.jsonl"

    _clear_env(monkeypatch)

    approved_at = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    req = NodesApproveActionRequest(
        action_id="act-123",
        node_ids=("node-a", "node-b", "node-a"),
        approver="calvin",
        comment="ship it",
        state_path=str(ledger),
        approved_at=approved_at,
    )

    result = approve_action(req)

    assert result.action_id == "act-123"
    assert result.approved_nodes == ("node-a", "node-b")  # de-duped, order preserved
    assert result.approver == "calvin"
    assert result.comment == "ship it"
    assert result.approved_at == "2025-01-02T03:04:05Z"
    assert result.ledger_path == str(ledger)

    # Verify the ledger contains exactly one JSON line.
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])

    assert record["schema_version"] == 1
    assert record["action_id"] == "act-123"
    assert record["approved"] is True
    assert record["approved_nodes"] == ["node-a", "node-b"]
    assert record["approver"] == "calvin"
    assert record["comment"] == "ship it"
    assert record["approved_at"] == "2025-01-02T03:04:05Z"
    assert record["scope"] == "nodes"


def test_approve_action_rejects_missing_action_id(tmp_path: Path) -> None:
    with pytest.raises(NodesApproveActionInputError) as exc:
        approve_action(NodesApproveActionRequest(action_id="  ", state_path=str(tmp_path / "a.jsonl")))
    assert exc.value.code == "invalid_input"
    assert "action_id" in exc.value.message


def test_approve_action_requires_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    with pytest.raises(NodesApproveActionConfigError) as exc:
        approve_action(NodesApproveActionRequest(action_id="act-1"))
    assert exc.value.code == "missing_config"
    assert DEFAULT_APPROVALS_ENV_VAR in json.dumps(exc.value.details)


def test_approve_action_fallback_state_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("THOMAS_STATE_DIR", str(tmp_path))

    result = approve_action(NodesApproveActionRequest(action_id="act-2"))
    assert Path(result.ledger_path) == tmp_path / DEFAULT_LEDGER_FILENAME
    assert (tmp_path / DEFAULT_LEDGER_FILENAME).exists()


def test_approve_action_external_failure_is_deterministic(tmp_path: Path) -> None:
    # Point the ledger path at a directory to force an OSError.
    with pytest.raises(NodesApproveActionExternalError) as exc:
        approve_action(NodesApproveActionRequest(action_id="act-1", state_path=str(tmp_path)))
    assert exc.value.code == "external_failure"
    assert exc.value.details.get("path") == str(tmp_path)


def test_approve_action_from_payload_validates_payload_type() -> None:
    with pytest.raises(NodesApproveActionInputError):
        approve_action_from_payload(["not", "a", "dict"])  # type: ignore[arg-type]


def test_cli_json_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = tmp_path / "approvals.jsonl"

    exit_code = cli.main(
        [
            "act-55",
            "--node",
            "n1",
            "--approver",
            "robot",
            "--state-path",
            str(ledger),
            "--json",
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["result"]["action_id"] == "act-55"
    assert payload["result"]["approved_nodes"] == ["n1"]


def test_cli_json_error_exit_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _clear_env(monkeypatch)

    exit_code = cli.main(["act-55", "--json"])

    # Config error should be deterministic.
    assert exit_code == NodesApproveActionConfigError.exit_code
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"
