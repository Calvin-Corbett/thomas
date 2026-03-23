import asyncio
import sys

import pytest

from thomas.marketplace.nodes.p032_node_command_run import (
    LocalSubprocessBackend,
    NodeCommandRunException,
    NodeCommandRunRequest,
    NodeRunErrorCode,
    node_command_run,
    request_from_json,
)


def _run(coro):
    return asyncio.run(coro)


def test_request_from_json_requires_command() -> None:
    with pytest.raises(NodeCommandRunException) as exc:
        request_from_json({})
    assert exc.value.code == NodeRunErrorCode.INVALID_INPUT
    assert "Missing command" in str(exc.value)


def test_request_from_json_rejects_raw_and_argv() -> None:
    with pytest.raises(NodeCommandRunException) as exc:
        request_from_json({"argv": ["echo", "hi"], "raw": "echo hi"})
    assert exc.value.code == NodeRunErrorCode.INVALID_INPUT


def test_request_from_json_env_mapping() -> None:
    req = request_from_json({"raw": "echo hi", "env": {"FOO": "BAR"}})
    assert req.env == {"FOO": "BAR"}


def test_local_backend_runs_argv_success() -> None:
    req = NodeCommandRunRequest(argv=[sys.executable, "-c", "print('hello')"])
    resp = _run(node_command_run(req, LocalSubprocessBackend()))
    assert resp.ok is True
    assert resp.result is not None
    assert resp.result.exit_code == 0
    assert "hello" in resp.result.stdout


def test_local_backend_runs_raw_success() -> None:
    req = NodeCommandRunRequest(raw="echo hello")
    resp = _run(node_command_run(req, LocalSubprocessBackend()))
    assert resp.ok is True
    assert resp.result is not None
    assert resp.result.exit_code == 0
    assert "hello" in resp.result.stdout


def test_local_backend_timeout_is_deterministic() -> None:
    req = NodeCommandRunRequest(
        argv=[sys.executable, "-c", "import time; time.sleep(1); print('done')"],
        command_timeout_ms=200,
    )
    resp = _run(node_command_run(req, LocalSubprocessBackend()))
    assert resp.ok is False
    assert resp.error is not None
    assert resp.error.code == NodeRunErrorCode.COMMAND_TIMEOUT


def test_local_backend_missing_executable_is_invoke_failed() -> None:
    req = NodeCommandRunRequest(argv=["this_executable_should_not_exist_12345"])
    resp = _run(node_command_run(req, LocalSubprocessBackend()))
    assert resp.ok is False
    assert resp.error is not None
    assert resp.error.code == NodeRunErrorCode.INVOKE_FAILED


def test_backend_failure_is_returned_deterministically() -> None:
    class BadBackend:
        async def run(self, req: NodeCommandRunRequest):
            raise NodeCommandRunException(NodeRunErrorCode.NODE_UNAVAILABLE, "no node manager")

    req = NodeCommandRunRequest(raw="echo hello")
    resp = _run(node_command_run(req, BadBackend()))
    assert resp.ok is False
    assert resp.error is not None
    assert resp.error.code == NodeRunErrorCode.NODE_UNAVAILABLE
    assert "no node manager" in resp.error.message
